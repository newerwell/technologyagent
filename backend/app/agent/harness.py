"""P05工作阶段状态转换；Run.status仍由运行服务单独管理。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, TypedDict

from backend.app.contracts.workflow import PlanItem, QueryEvidence, TaskType, source_refs
from backend.app.ports.tools import ToolResult
from backend.app.ports.executor import EventSink
AgentPhase = Literal["planning", "executing", "reviewing", "result"]
MAX_REVISIONS = 2


class InvalidPhaseTransition(ValueError):
    """阶段转换违反Harness有限状态机。"""


class StateUpdate(TypedDict):
    phase: AgentPhase
    phase_changed: bool
    task_type: str
    plan: list[dict[str, Any]]
    evidence_refs: list[dict[str, Any]]
    review: dict[str, Any] | None
    revision_count: int
    plan_signature: str


def transition_phase(state: dict[str, Any], target: AgentPhase) -> StateUpdate:
    """返回最小阶段状态补丁；同阶段不产生重复事件。"""
    current = state.get("phase")
    revisions = int(state.get("revision_count", 0))
    if revisions < 0 or revisions > MAX_REVISIONS:
        raise InvalidPhaseTransition("revision limit state is invalid")
    if current == target:
        return {
            "phase": target,
            "phase_changed": False,
            "task_type": str(state.get("task_type") or "general"),
            "plan": list(state.get("plan") or []),
            "evidence_refs": list(state.get("evidence_refs") or []),
            "review": state.get("review"),
            "revision_count": revisions,
            "plan_signature": str(state.get("plan_signature") or ""),
        }
    if state.get("run_status") == "waiting_input":
        raise InvalidPhaseTransition("waiting_input cannot be completed by a phase transition")
    allowed = {
        None: {"planning"},
        "planning": {"executing"},
        "executing": {"reviewing"},
        "reviewing": {"executing", "result"},
        "result": set(),
    }
    failure_result = target == "result" and state.get("run_status") in {"failed", "cancelled"}
    if target not in allowed.get(current, set()) and not failure_result:
        raise InvalidPhaseTransition(f"invalid phase transition {current!r} -> {target!r}")
    if current == "reviewing" and target == "executing":
        if revisions >= MAX_REVISIONS:
            raise InvalidPhaseTransition("revision limit reached")
        revisions += 1
    return {
        "phase": target,
        "phase_changed": True,
        "task_type": str(state.get("task_type") or "general"),
        "plan": list(state.get("plan") or []),
        "evidence_refs": list(state.get("evidence_refs") or []),
        "review": state.get("review"),
        "revision_count": revisions,
        "plan_signature": str(state.get("plan_signature") or ""),
    }


def classify_task(message: str) -> TaskType:
    text = message.lower()
    intent_text = re.sub(
        r"(?:不要|无需|不需要|不必|暂不|禁止|拒绝|不考虑)[^，,。；;!?]{0,60}",
        "",
        text,
    )
    if re.search(r"下单|创建订单|提交订单|生成订单|采购订单", intent_text):
        return "order"
    constraints = extract_request_constraints(message)
    if constraints.get("intent") == "supplier_recommendation":
        return "supplier"
    if re.search(r"供应商|报价|供货", intent_text):
        return "supplier"
    if re.search(r"分析|比较|趋势|汇总", intent_text):
        return "analysis"
    if re.search(r"库存|在手|缺口|缺货|缺多少|短缺|缺少|补货", intent_text):
        return "inventory"
    return "general"


def extract_request_constraints(message: str) -> dict[str, Any]:
    """Keep user filters separate from observed tool facts."""
    text = message or ""
    intent_text = re.sub(
        r"(?:不要|无需|不需要|不必|暂不|禁止|拒绝|不考虑)[^，,。；;!?]{0,60}",
        "",
        text.lower(),
    )
    warehouse_ids = sorted({value.upper() for value in re.findall(r"(?<![A-Za-z0-9])W\d{2}(?![A-Za-z0-9])", text, re.I)})
    part_ids = sorted({value.upper() for value in re.findall(r"(?<![A-Za-z0-9])P\d{3}(?![A-Za-z0-9])", text, re.I)})
    lead = re.search(r"(?:不超过|以内|天内|最多|交期上限|max_lead_days\s*[:=]?\s*)(\d+|[一二三四五六七八九十]+)\s*(?:天|日|days?)?", text, re.I)
    if not lead:
        lead = re.search(r"(\d+|[一二三四五六七八九十]+)\s*(?:天|日)内", text)
    lead_value = lead.group(1) if lead else None
    if lead_value and lead_value.isdigit():
        max_lead_days = int(lead_value)
    elif lead_value:
        digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        max_lead_days = 10 if lead_value == "十" else digits.get(lead_value, -1)
        if "十" in lead_value and lead_value != "十":
            before, _, after = lead_value.partition("十")
            max_lead_days = (digits.get(before, 1) * 10) + digits.get(after, 0)
        if max_lead_days < 0:
            max_lead_days = None
    else:
        max_lead_days = None
    if re.search(r"预警", intent_text):
        intent = "inventory_warning"
    elif re.search(r"(?:哪些|哪几个|所有|全部).{0,16}(?:零件|物料).{0,16}(?:补货|缺口)|(?:需要补货|要补货)", intent_text):
        intent = "target_replenishment"
    elif re.search(r"(?:推荐|供应商|报价|到货|最便宜)", intent_text):
        intent = "supplier_recommendation"
    else:
        intent = "query"
    return {
        "warehouse_ids": warehouse_ids,
        "part_ids": part_ids,
        "max_lead_days": max_lead_days,
        "intent": intent,
    }


def query_matches_constraints(query: QueryEvidence, constraints: dict[str, Any]) -> bool:
    args = query.arguments
    warehouses = {str(value).upper() for value in constraints.get("warehouse_ids") or []}
    parts = {str(value).upper() for value in constraints.get("part_ids") or []}
    arg_warehouses = {str(value).upper() for value in [args.get("warehouse_id"), *(args.get("warehouse_ids") or [])] if value}
    arg_parts = {str(value).upper() for value in [args.get("part_id"), *(args.get("part_ids") or [])] if value}
    if warehouses and not warehouses.intersection(arg_warehouses):
        return False
    if parts and not parts.intersection(arg_parts):
        return False
    max_lead = constraints.get("max_lead_days")
    if max_lead is not None:
        return query.tool_name == "replenishment_preview" and args.get("max_lead_days") == max_lead
    if constraints.get("intent") == "inventory_warning":
        return query.tool_name == "inventory_warning"
    if constraints.get("intent") == "target_replenishment":
        return query.tool_name in {"inventory_page", "replenishment_preview"}
    return True


def query_scope_complete(queries: list[QueryEvidence]) -> bool:
    """Require complete server pagination for a scope, not just a first page."""
    if not queries:
        return False
    totals = {item.total for item in queries if item.total is not None}
    page_counts = {item.pages for item in queries if item.pages is not None}
    if len(totals) != 1 or len(page_counts) != 1:
        return False
    total, pages = next(iter(totals)), next(iter(page_counts))
    if total == 0:
        return pages in {0, 1}
    page_ids: dict[int, set[str]] = {}
    for item in queries:
        if item.page is None or item.pages != pages:
            return False
        page_ids.setdefault(item.page, set()).update(item.record_ids)
    if set(page_ids) != set(range(1, pages + 1)):
        return False
    return len(set().union(*page_ids.values())) >= total


def build_plan(task_type: TaskType) -> list[PlanItem]:
    templates: dict[TaskType, list[tuple[str, str, str]]] = {
        "general": [],
        "inventory": [("read_inventory", "读取只读业务数据并核对目标范围", "inventory_page,inventory_warning,inventory_get,supplier_query,supplier_get,part_search,part_query,quote_list,replenishment_preview")],
        "supplier": [("read_supplier", "读取供应商、零件或报价依据", "supplier_query,supplier_get,quote_list,part_search,part_query,replenishment_preview,inventory_page,inventory_warning,inventory_get")],
        "analysis": [("read_analysis", "收集分析范围内的数据", "*")],
        "order": [
            ("prepare_draft", "准备并校验订单草稿", "order_draft_prepare"),
            ("human_approval", "等待人工审批", "approval"),
            ("verify_order", "查询已提交订单结果", "order_result_read"),
        ],
    }
    return [
        PlanItem(id=step_id, title=title, required_action=action)
        for step_id, title, action in templates[task_type]
    ]


def sanitize_plan(plan: list[PlanItem | dict[str, Any]]) -> list[PlanItem]:
    """丢弃模型/外部候选状态与来源，只保留受控步骤定义。"""
    clean: list[PlanItem] = []
    seen: set[str] = set()
    for raw in plan:
        item = raw if isinstance(raw, PlanItem) else PlanItem.model_validate(raw)
        if item.id in seen:
            continue
        seen.add(item.id)
        clean.append(item.model_copy(update={"status": "pending", "evidence_refs": [], "query_evidence": []}))
    return clean


def update_plan_from_result(
    plan: list[PlanItem], tool_result: ToolResult,
    request_constraints: dict[str, Any] | None = None,
) -> list[PlanItem]:
    name = str(tool_result.meta.get("tool_name") or "")
    refs = source_refs(list(tool_result.meta.get("evidence_refs") or []))
    updated = list(plan)
    for index, item in enumerate(updated):
        required = set((item.required_action or "").split(","))
        matches = item.status in {"pending", "running", "failed"} and ("*" in required or name in required)
        if not matches:
            continue
        query_raw = tool_result.meta.get("query_evidence")
        query_evidence = list(item.query_evidence)
        if query_raw:
            current = QueryEvidence.model_validate(query_raw)
            query_evidence = [query for query in query_evidence if not (
                query.tool_name == current.tool_name
                and query.page == current.page
                and {key: value for key, value in query.arguments.items() if key not in {"page", "page_size"}}
                == {key: value for key, value in current.arguments.items() if key not in {"page", "page_size"}}
                and query.as_of == current.as_of
            )] + [current]
        constraints_met = True
        if request_constraints and query_evidence:
            matching = [query for query in query_evidence if query_matches_constraints(query, request_constraints)]
            if request_constraints.get("intent") == "target_replenishment":
                grouped: dict[str, list[QueryEvidence]] = {}
                for query in matching:
                    args = {key: value for key, value in query.arguments.items() if key not in {"page", "page_size"}}
                    key = json.dumps([query.tool_name, args, query.as_of], sort_keys=True, separators=(",", ":"))
                    grouped.setdefault(key, []).append(query)
                constraints_met = any(query_scope_complete(group) for group in grouped.values())
            elif request_constraints.get("max_lead_days") is not None:
                constraints_met = bool(matching)
            elif request_constraints.get("intent") == "inventory_warning":
                grouped: dict[str, list[QueryEvidence]] = {}
                for query in matching:
                    args = {key: value for key, value in query.arguments.items() if key not in {"page", "page_size"}}
                    key = json.dumps([query.tool_name, args, query.as_of], sort_keys=True, separators=(",", ":"))
                    grouped.setdefault(key, []).append(query)
                constraints_met = any(query_scope_complete(group) for group in grouped.values())
        elif request_constraints and request_constraints.get("intent") in {"target_replenishment", "inventory_warning", "supplier_recommendation"}:
            constraints_met = False
        if tool_result.ok and tool_result.call_id and (refs or query_evidence):
            updated[index] = item.model_copy(update={
                "status": "done" if constraints_met else "running",
                "evidence_refs": refs,
                "query_evidence": query_evidence,
            })
        elif not tool_result.ok:
            updated[index] = item.model_copy(update={"status": "failed"})
        return updated
    return updated


def mark_plan_running(plan: list[PlanItem], tool_name: str) -> list[PlanItem]:
    updated = list(plan)
    for index, item in enumerate(updated):
        required = set((item.required_action or "").split(","))
        if item.status in {"pending", "failed"} and ("*" in required or tool_name in required):
            updated[index] = item.model_copy(update={"status": "running"})
            break
    return updated


def skip_pending(plan: list[PlanItem]) -> list[PlanItem]:
    return [
        item.model_copy(update={"status": "skipped"})
        if item.status in {"pending", "running"}
        else item
        for item in plan
    ]


def _parse_plan(state: dict[str, Any]) -> list[PlanItem]:
    return [item if isinstance(item, PlanItem) else PlanItem.model_validate(item) for item in state.get("plan") or []]


async def publish_phase(state: dict[str, Any], target: AgentPhase, sink: EventSink) -> bool:
    update = transition_phase(state, target)
    state.update(update)
    if not update["phase_changed"]:
        return False
    await sink.emit("phase", {
        "phase": update["phase"],
        "iteration": update["revision_count"],
        "task_type": update["task_type"],
        "revision_count": update["revision_count"],
    })
    return True


async def publish_plan(state: dict[str, Any], sink: EventSink, *, force: bool = False) -> bool:
    plan = _parse_plan(state)
    serialized = [item.model_dump(mode="json") for item in plan]
    evidence = source_refs(list(state.get("evidence_refs") or []))
    signature = json.dumps({"task_type": state.get("task_type", "general"), "items": serialized,
                            "evidence": [item.model_dump(mode="json") for item in evidence],
                            "request_constraints": state.get("request_constraints") or {}},
                           sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    if not force and state.get("plan_signature") == digest:
        return False
    state["plan"] = serialized
    state["plan_signature"] = digest
    await sink.emit("plan", {
        "items": serialized,
        "task_type": state.get("task_type", "general"),
        "evidence_refs": [item.model_dump(mode="json") for item in evidence],
        "request_constraints": state.get("request_constraints") or {},
    })
    return True


async def publish_review(state: dict[str, Any], result: Any, sink: EventSink) -> None:
    state["review"] = result.model_dump(mode="json")
    state["revision_count"] = result.revision_count
    await sink.emit("review", {
        "passed": result.passed,
        "checks": [item.check_id for item in result.checks],
        "revision_count": result.revision_count,
        "details": [item.model_dump(mode="json") for item in result.checks],
        "result": result.model_dump(mode="json"),
        "incomplete_items": result.incomplete_items,
    })
