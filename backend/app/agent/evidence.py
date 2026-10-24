"""结构化收集只读工具事实，并拒绝无来源或数值不匹配的业务结论。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.app.ports.tools import ToolResult

_ORDER_CLAIM = re.compile(r"(已(?:经)?(?:下单|创建订单|提交订单)|订单已(?:创建|提交|成立))")
_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")
_IDS = re.compile(r"\b(P\d{3}|W\d{2})\b", re.IGNORECASE)
_ANY_ID = re.compile(r"\b[A-Z]\d{2,3}\b", re.IGNORECASE)

_FIELD_HINTS: tuple[tuple[tuple[str, ...], frozenset[str]], ...] = (
    (("预计可用", "预测可用", "projected"), frozenset({"projected"})),
    (("缺口", "短缺", "不足", "shortage"), frozenset({"shortage"})),
    (("可用", "available"), frozenset({"available"})),
    (("在手", "现有库存", "on_hand"), frozenset({"on_hand"})),
    (("单价", "unit price"), frozenset({"unit_price_cents"})),
    (("总额", "总价", "金额", "合计", "元", "分"), frozenset({"total_cents", "line_total_cents"})),
    (("交期", "到货", "天", "lead time"), frozenset({"lead_days", "max_lead_days"})),
    (("数量", "件", "套", "quantity"), frozenset({"quantity", "shortage"})),
)


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    passed: bool
    violations: list[str] = field(default_factory=list)
    cited_facts: list[dict[str, Any]] = field(default_factory=list)


def _fact_value(field: str, value: Any, *, base: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    unit = "cents" if field.endswith("_cents") or field in {"unit_price_cents", "total_cents"} else "count"
    return {**base, "field": field, "value": value, "unit": unit}


def _walk_facts(value: Any, *, base: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if isinstance(value, dict):
        local = {
            **base,
            **{key: value[key] for key in ("part_id", "warehouse_id", "id") if value.get(key) is not None},
        }
        for key, item in value.items():
            fact = _fact_value(str(key), item, base=local)
            if fact:
                facts.append(fact)
            elif isinstance(item, (dict, list)):
                facts.extend(_walk_facts(item, base=local))
    elif isinstance(value, list):
        for item in value:
            facts.extend(_walk_facts(item, base=base))
    return facts


def _ref(ref: dict[str, Any], *, call_id: str, default_entity: str) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "entity": ref.get("entity", default_entity),
        "id": str(ref.get("id", "")),
        "data_source": ref.get("data_source", "local_seed"),
        "as_of": ref.get("as_of") or datetime.now(timezone.utc).isoformat(),
    }


def collect_evidence(
    name: str, result: ToolResult, *, call_id: str, arguments: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    if not result.ok or not isinstance(result.data, dict):
        return []
    data = result.data
    default_entity = "preview" if name == "replenishment_preview" else "inventory"
    refs: list[dict[str, Any]] = []
    for source in data.get("source_refs") or []:
        refs.append(_ref(source, call_id=call_id, default_entity=default_entity))
    records = data.get("records") or []
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and record.get("id"):
                refs.append(_ref({"id": record["id"], "entity": default_entity}, call_id=call_id, default_entity=default_entity))
    if data.get("id"):
        refs.append(_ref({"id": data["id"], "entity": default_entity}, call_id=call_id, default_entity=default_entity))
    if name == "replenishment_preview":
        for line in data.get("lines") or []:
            if not isinstance(line, dict):
                continue
            line_refs = [ref for ref in refs if ref.get("id") in {str(line.get("part_id", "")), str(line.get("inventory_id", ""))}]
            if not line_refs:
                line_refs = refs or [_ref({}, call_id=call_id, default_entity="preview")]
            facts = _walk_facts(line, base={
                "call_id": call_id,
                "entity": "replenishment",
                "record_id": line.get("inventory_id") or line.get("part_id"),
                "part_id": line.get("part_id"),
                "warehouse_id": line.get("warehouse_id"),
                "as_of": result.meta.get("as_of"),
                "data_source": result.meta.get("data_source", "local_seed"),
            })
            for fact in facts:
                fact["source_refs"] = line_refs
            refs.extend(facts)
    # Keep a source reference and numeric facts together in the same evidence records.
    facts = _walk_facts(data, base={
        "call_id": call_id,
        "entity": default_entity,
        "as_of": result.meta.get("as_of"),
        "data_source": result.meta.get("data_source", "local_seed"),
    })
    if name == "replenishment_preview" and isinstance((arguments or {}).get("max_lead_days"), int):
        facts.append({
            "call_id": call_id,
            "entity": "replenishment_query",
            "field": "max_lead_days",
            "value": arguments["max_lead_days"],
            "unit": "days",
            "part_id": ",".join(arguments.get("part_ids", [])),
            "warehouse_id": arguments.get("warehouse_id"),
            "data_source": result.meta.get("data_source", "local_seed"),
            "as_of": result.meta.get("as_of"),
        })
    return refs + facts


def _rendered_values(fact: dict[str, Any]) -> set[str]:
    value = fact.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return set()
    values = {str(value)}
    if fact.get("unit") == "cents" and isinstance(value, int):
        values.add(f"{value / 100:.2f}")
    return values


def validate_business_claims(answer: str, evidence: list[dict[str, Any]]) -> ClaimCheck:
    violations: list[str] = []
    if _ORDER_CLAIM.search(answer):
        violations.append("P03 is read-only and cannot create or submit orders")
    refs = [item for item in evidence if item.get("id")]
    facts = [item for item in evidence if "value" in item and item.get("call_id")]
    identifiers = list(_ANY_ID.finditer(answer))
    numbers = [
        match
        for match in _NUMBER.finditer(answer)
        if not any(identifier.start() <= match.start() and match.end() <= identifier.end() for identifier in identifiers)
    ]
    cited: list[dict[str, Any]] = []
    for numeric_match in numbers:
        number = numeric_match.group(0)
        start = numeric_match.start()
        context = answer[max(0, start - 24):numeric_match.end() + 12].lower()
        hinted_fields = set().union(*(
            fields for hints, fields in _FIELD_HINTS if any(hint in context for hint in hints)
        ))
        if not hinted_fields:
            violations.append(f"numeric claim {number} has no recognized fact field or unit")
            continue
        matches = [fact for fact in facts if fact.get("field") in hinted_fields and number in _rendered_values(fact)]
        if not matches:
            violations.append(f"numeric claim {number} does not match a structured tool fact")
            continue
        mentioned_ids = {value.upper() for value in _IDS.findall(answer)}
        scoped = [fact for fact in matches if not mentioned_ids or mentioned_ids.issubset({str(fact.get("part_id", "")).upper(), str(fact.get("warehouse_id", "")).upper()})]
        if not scoped:
            violations.append(f"numeric claim {number} does not match the stated entity/scope")
            continue
        cited.extend(scoped)
    if numbers and not refs:
        violations.append("numeric business claim has no record reference")
    return ClaimCheck(passed=not violations, violations=violations, cited_facts=cited)
