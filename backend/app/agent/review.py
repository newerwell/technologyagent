"""确定性业务硬检查与补充性语义评审。"""

from __future__ import annotations

import asyncio
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.app.agent.budget import RunBudget
from backend.app.contracts.agent import ModelMessage
from backend.app.contracts.common import RequestContext
from backend.app.agent.evidence import validate_business_claims
from backend.app.ports.model import ModelPort
from backend.app.contracts.workflow import ReviewCheck, ReviewResult

_ORDER_CLAIM = re.compile(r"已(?:经)?(?:下单|创建订单|提交订单)|订单已(?:创建|提交|成立)")


def _valid_source_keys(evidence: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    return {
        (str(item.get("call_id", "")), str(item.get("entity", "")), str(item.get("id", "")))
        for item in evidence
        if item.get("call_id") and item.get("entity") and item.get("id")
    }


def _check(
    check_id: str,
    passed: bool,
    reason: str = "",
    refs: list[str] | None = None,
    kind: str = "deterministic",
) -> ReviewCheck:
    return ReviewCheck(
        check_id=check_id, passed=passed, reason=reason, evidence_refs=refs or [], kind=kind
    )


def _semantic_facts(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = (
        "call_id", "entity", "id", "record_id", "field", "value", "unit",
        "part_id", "warehouse_id", "data_source", "as_of", "source_refs",
    )
    return [{key: item[key] for key in allowed if key in item} for item in evidence]


def _semantic_order_facts(value: Any) -> Any:
    allowed_fields = {
        "order": ("id", "_id", "number", "status", "total_cents", "supplier_id", "warehouse_id", "items"),
        "operation": ("id", "_id", "status", "order_id", "action"),
        "approval": ("id", "_id", "state", "status", "operation_id", "order_id"),
    }
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("orders"), list):
        return [
            {key: {field: record.get(field) for field in allowed_fields[key] if field in record}
             for key in allowed_fields if isinstance((record := entry.get(key)), dict)}
            for entry in value["orders"] if isinstance(entry, dict)
        ]
    return {
        key: {field: value[key][field] for field in allowed_fields[key] if field in value[key]}
        for key in allowed_fields if isinstance(value.get(key), dict)
    }


def deterministic_review(state: dict[str, Any]) -> ReviewResult:
    """检查候选答案，只读事实、计划依据与已提交订单的持久事实。"""
    answer = str(state.get("final_answer") or "")
    evidence = list(state.get("evidence") or [])
    sources = _valid_source_keys(evidence)
    verified_order = state.get("order_verification")
    order_write = state.get("last_mutation_result")
    checked_answer = answer
    if state.get("task_type") == "order" and order_write and verified_order:
        checked_answer = _ORDER_CLAIM.sub("订单", answer)
    claim = validate_business_claims(checked_answer, evidence)

    numeric_issues = [item for item in claim.violations if "numeric claim" in item or "contradicts" in item]
    scope_issues = [item for item in claim.violations if "scope" in item]
    source_issues = [item for item in claim.violations if "source" in item or "reference" in item]
    operation_issues = [item for item in claim.violations if "read-only" in item]
    numeric_calls = {str(item.get("call_id")) for item in claim.cited_facts if item.get("call_id")}
    numeric_refs = sorted({
        f"{call_id}/{record_id}"
        for call_id, _, record_id in sources
        if call_id in numeric_calls
    })
    checks = [
        _check(
            "NUMERIC_MATCH",
            not numeric_issues,
            "; ".join(numeric_issues),
            numeric_refs,
        ),
        _check("SCOPE_MATCH", not scope_issues, "; ".join(scope_issues)),
        _check(
            "SOURCE_EXISTS",
            not source_issues,
            "; ".join(source_issues) if source_issues else "所有引用均可追溯到成功工具结果。",
            sorted({call for call, _, _ in sources}),
        ),
        _check("READ_ONLY_BOUNDARY", not operation_issues, "; ".join(operation_issues)),
    ]

    plan_issues: list[str] = []
    incomplete_plan: list[str] = []
    for item in state.get("plan") or []:
        raw = item if isinstance(item, dict) else item.model_dump(mode="json")
        if raw.get("required_action") and raw.get("status") != "done":
            incomplete_plan.append(f"{raw.get('id')}: required action is {raw.get('status', 'pending')}")
        if raw.get("status") == "done":
            refs = raw.get("evidence_refs") or []
            query_evidence = raw.get("query_evidence") or []
            if not refs and not query_evidence:
                plan_issues.append(f"{raw.get('id')}: completed step has no source reference")
                continue
            for ref in refs:
                ref_data = ref if isinstance(ref, dict) else ref.model_dump(mode="json")
                key = (str(ref_data.get("call_id", "")), str(ref_data.get("entity", "")), str(ref_data.get("id", "")))
                if key not in sources:
                    plan_issues.append(f"{raw.get('id')}: source {key[2] or '(missing id)'} is absent")
            for query in query_evidence:
                if not query.get("call_id") or not query.get("tool_name") or not query.get("data_source"):
                    plan_issues.append(f"{raw.get('id')}: query evidence is incomplete")
    checks.append(_check("PLAN_EVIDENCE", not plan_issues, "; ".join(plan_issues)))
    checks.append(_check("PLAN_COMPLETE", not incomplete_plan, "; ".join(incomplete_plan)))

    if order_write:
        operation_id = str(order_write.get("operation_id") or "")
        order_id = str(order_write.get("order_id") or "")
        order = (verified_order or {}).get("order") or {}
        operation = (verified_order or {}).get("operation") or {}
        approval = (verified_order or {}).get("approval") or {}
        order_exists = bool(
            operation_id and order_id
            and str(order.get("id") or order.get("_id") or "") == order_id
            and str(order.get("operation_id") or "") == operation_id
            and str(operation.get("id") or operation.get("_id") or "") == operation_id
            and operation.get("status") == "succeeded"
            and str(operation.get("order_id") or "") == order_id
        )
        approval_exists = bool(
            approval.get("state") == "consumed"
            and str(approval.get("operation_id") or "") == operation_id
        )
        checks.extend([
            _check("ORDER_EXISTS", order_exists, "订单结果必须由持久订单和成功operation核对。" if not order_exists else "已从持久订单记录核对成功operation。", [operation_id] if operation_id else []),
            _check("APPROVAL_EXISTS", approval_exists, "订单operation必须关联已消费审批。" if not approval_exists else "审批消费记录与订单operation一致。", [operation_id] if operation_id else []),
        ])

    passed = all(item.passed for item in checks)
    revision_count = int(state.get("revision_count", 0))
    failed = [item.check_id for item in checks if not item.passed]
    non_revisable = any(item.check_id == "READ_ONLY_BOUNDARY" and not item.passed for item in checks)
    return ReviewResult(
        passed=passed,
        checks=checks,
        needs_revision=not passed and not non_revisable and revision_count < 2,
        revision_count=revision_count,
        incomplete_items=failed,
    )


def combine_reviews(deterministic: ReviewResult, semantic: ReviewResult) -> ReviewResult:
    """语义结果只能收紧结论，不能覆盖确定性失败。"""
    checks = [*deterministic.checks, *semantic.checks]
    passed = deterministic.passed and semantic.passed
    failed = [item.check_id for item in checks if not item.passed]
    revisions = max(deterministic.revision_count, semantic.revision_count)
    return ReviewResult(
        passed=passed,
        checks=checks,
        needs_revision=not passed and revisions < 2,
        revision_count=revisions,
        incomplete_items=failed,
    )


@lru_cache(maxsize=1)
def _rubrics() -> dict[str, list[str]]:
    loaded = yaml.safe_load(Path(__file__).with_name("rubrics.yaml").read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or loaded.get("version") != 1:
        raise ValueError("unsupported review rubric version")
    return {str(key): [str(item) for item in value] for key, value in loaded.items() if key != "version"}


async def semantic_review(
    state: dict[str, Any], model: ModelPort, budget: RunBudget, ctx: RequestContext
) -> ReviewResult:
    """按任务rubric检查遗漏与表达；不接受工具调用或自由格式推理。"""
    task_type = str(state.get("task_type") or "general")
    rubrics = _rubrics()
    rubric = rubrics.get(task_type, rubrics["general"])
    checks_text = "\n".join(f"- {item}" for item in rubric)
    messages = [
        ModelMessage(
            role="system",
            content=(
                "你是语义完整性检查器，只返回JSON对象 {\"passed\": boolean, \"issues\": [string]}。"
                "只判断遗漏和表达；不要提供 private reasoning，不得重算或更改数值、来源、审批或业务状态。"
                "给定的verified_facts和order_verification是服务端核验结果。不得要求上下文之外的额外来源；"
                "order.number是用户可见单号，order.id是数据库标识，两者含义不同。"
                "只判断答案是否清晰覆盖请求、说明结果或限制；不要重新验证结构化事实。Rubric:\n" + checks_text
            ),
        ),
        ModelMessage(
            role="user",
            content=json.dumps({
                "task_type": task_type,
                "request": str(state.get("original_request") or state.get("task_summary") or state.get("user_message") or ""),
                "answer": str(state.get("final_answer") or ""),
                "plan": [
                    (item if isinstance(item, dict) else item.model_dump(mode="json"))
                    for item in state.get("plan") or []
                ],
                "source_refs": state.get("evidence_refs") or [],
                "verified_facts": _semantic_facts(list(state.get("evidence") or [])),
                "order_verification": _semantic_order_facts(
                    state.get("order_verification") or state.get("verified_orders")
                ),
                "workflow_outcome": state.get("workflow_outcome"),
            }, ensure_ascii=False, default=str),
        ),
    ]
    await budget.charge_model()
    parts: list[str] = []

    async def consume() -> None:
        async for delta in model.stream(messages, [], ctx):
            await budget.check_cancelled()
            await budget.check_active()
            if delta.kind == "token" and delta.content:
                parts.append(delta.content)

    try:
        await asyncio.wait_for(consume(), timeout=budget.bounded_timeout(60))
    except asyncio.TimeoutError:
        await budget.check_active()
        return ReviewResult(
            passed=False,
            checks=[_check("SEMANTIC_COMPLETE", False, "语义评审模型调用超时。", kind="semantic")],
            needs_revision=True,
            revision_count=int(state.get("revision_count", 0)),
            incomplete_items=["SEMANTIC_COMPLETE"],
        )
    raw = "".join(parts).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    issues = payload.get("issues") if isinstance(payload, dict) else None
    safe_issues = (
        isinstance(issues, list)
        and all(isinstance(item, str) and len(item) <= 240 for item in issues)
        and not any(re.search(r"chain[- ]of[- ]thought|private reasoning|思维链|逐步推理", item, re.I) for item in issues)
    )
    model_passed = (
        isinstance(payload, dict)
        and payload.get("passed") is True
        and safe_issues
        and not issues
    )
    reason = (
        "语义评审通过。"
        if model_passed
        else "; ".join(issues)[:1000]
        if safe_issues and isinstance(issues, list)
        else "语义评审未返回有效JSON结果。"
    )
    passed = bool(model_passed)
    revision_count = int(state.get("revision_count", 0))
    return ReviewResult(
        passed=passed,
        checks=[_check("SEMANTIC_COMPLETE", passed, reason, kind="semantic")],
        needs_revision=not passed and revision_count < 2,
        revision_count=revision_count,
        incomplete_items=[] if passed else ["SEMANTIC_COMPLETE"],
    )
