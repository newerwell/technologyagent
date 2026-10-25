"""结构化收集只读工具事实，并拒绝无来源或数值不匹配的业务结论。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.app.agent.fact_checks import build_fact_index, validate_answer
from backend.app.ports.tools import ToolResult

_ORDER_CLAIM = re.compile(r"(已(?:经)?(?:下单|创建订单|提交订单)|订单已(?:创建|提交|成立))")
_NUMBER = re.compile(r"(?<![A-Za-z])-?\d+(?:\.\d+)?")
_TIMESTAMP = re.compile(
    r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?",
    re.IGNORECASE,
)
# Python's Unicode \b treats adjacent Chinese letters as word characters, so a
# Chinese sentence immediately followed by P001/W01/S01 otherwise loses ID boundaries.
_IDS = re.compile(r"(?<![A-Za-z0-9])(P\d{3}|W\d{2})(?![A-Za-z0-9])", re.IGNORECASE)
_ANY_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z]\d{2,3}(?![A-Za-z0-9])", re.IGNORECASE)

_FIELD_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("projected", ("预计可用", "预测可用", "预计库存", "预测库存", "projected")),
    ("shortage", ("缺口", "短缺", "缺货", "不足", "shortage")),
    ("available", ("可用库存", "可用", "available")),
    ("on_hand", ("在手", "现有库存", "库存", "on_hand")),
    ("reserved", ("预留", "reserved")),
    ("inbound", ("在途", "inbound")),
    ("safety_stock", ("安全库存", "safety stock")),
    ("target_stock", ("目标库存", "target stock")),
    ("unit_price_cents", ("单价", "unit price")),
    ("max_lead_days", ("要求", "最多", "不超过", "以内", "上限", "筛选", "天内", "max_lead_days")),
    ("total_cents", ("总额", "总价", "金额", "合计", "total")),
    ("lead_days", ("交期", "到货", "lead time")),
    ("min_order_qty", ("起订量", "最低订购量", "minimum order quantity")),
    ("quantity", ("数量", "采购量", "quantity")),
)


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    passed: bool
    violations: list[str] = field(default_factory=list)
    cited_facts: list[dict[str, Any]] = field(default_factory=list)


def _fact_value(field: str, value: Any, *, base: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if field in {"schema_version", "version", "page", "page_size", "pages", "total"}:
        return None
    if field.endswith("_cents") or field in {"unit_price_cents", "total_cents", "order_total_cents"}:
        unit = "cents"
    elif field in {"lead_days", "max_lead_days"}:
        unit = "days"
    else:
        unit = "count"
    return {**base, "field": field, "value": value, "unit": unit}


def _walk_facts(value: Any, *, base: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    display_fields = {"part_name", "supplier_name", "unit", "quote_id", "recommended_quote_id"}
    boolean_fields = {"is_valid", "warning", "active"}
    if isinstance(value, dict):
        local = {
            **base,
            **{key: value[key] for key in (
                "part_id", "warehouse_id", "supplier_id", "order_id", "id", "quote_id", "inventory_id",
            ) if value.get(key) is not None},
        }
        for key, item in value.items():
            fact = _fact_value(str(key), item, base=local)
            if fact:
                facts.append(fact)
            elif key in boolean_fields and isinstance(item, bool):
                facts.append({**local, "field": str(key), "value": item, "unit": "boolean"})
            elif key in display_fields and isinstance(item, str) and item.strip():
                facts.append({**local, "field": str(key), "value": item, "unit": "identifier" if key.endswith("quote_id") else "label"})
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
    default_entity = {
        "replenishment_preview": "preview",
        "quote_list": "quote",
        "supplier_query": "supplier",
        "supplier_get": "supplier",
        "part_search": "part",
        "part_query": "part",
        "inventory_page": "inventory",
        "inventory_warning": "inventory",
        "inventory_get": "inventory",
    }.get(name, "tool_result")
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
    # Replenishment lines are already walked above with their business scope
    # attached. Walking the envelope again creates duplicate facts with a
    # second entity identity and can make one row look ambiguous.
    facts = [] if name == "replenishment_preview" else _walk_facts(data, base={
        "call_id": call_id,
        "entity": default_entity,
        "as_of": result.meta.get("as_of"),
        "data_source": result.meta.get("data_source", "local_seed"),
    })
    aggregate_field = {
        "inventory_page": "inventory_count",
        "inventory_warning": "warning_count",
        "quote_list": "quote_count",
        "supplier_query": "supplier_count",
        "part_search": "part_count",
    }.get(name)
    if aggregate_field and isinstance(data.get("total"), int) and not isinstance(data.get("total"), bool):
        facts.append({
            "call_id": call_id, "entity": "query_aggregate", "field": aggregate_field,
            "value": data["total"], "unit": "count", "metric": name,
            "part_id": (arguments or {}).get("part_id"),
            "warehouse_id": (arguments or {}).get("warehouse_id"),
            "supplier_id": (arguments or {}).get("supplier_id"),
            "data_source": result.meta.get("data_source", "local_seed"),
            "as_of": result.meta.get("as_of"),
        })
    for fact in facts:
        if "source_refs" not in fact:
            fact["source_refs"] = refs
    if name == "replenishment_preview" and isinstance((arguments or {}).get("max_lead_days"), int):
        facts.append({
            "call_id": call_id,
            "entity": "request_constraint",
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


def _field_for_claim(answer: str, match: re.Match[str]) -> tuple[set[str], str | None, str]:
    """Bind a number only to a nearby explicit field label and unit."""
    start, end = match.span()
    left = max(answer.rfind(mark, 0, start) for mark in ("，", ",", "；", ";", "。", "!", "?", "\n")) + 1
    right_candidates = [answer.find(mark, end) for mark in ("，", ",", "；", ";", "。", "!", "?", "\n")]
    right = min((position for position in right_candidates if position >= 0), default=len(answer))
    clause = answer[left:right]
    local_start, local_end = start - left, end - left
    before = clause[max(0, local_start - 32):local_start].lower()
    after = clause[local_end:].lower()
    line_start = answer.rfind("\n", 0, start) + 1
    line_end = answer.find("\n", end)
    if line_end < 0:
        line_end = len(answer)
    row = answer[line_start:line_end]
    if "|" in row:
        previous_lines = answer[:line_start].splitlines()
        separators = [index for index, line in enumerate(previous_lines)
                      if "|" in line and re.fullmatch(r"[\s|:-]+", line)]
        header = previous_lines[separators[-1] - 1] if separators and separators[-1] > 0 else ""
        columns_before = row[:start - line_start].count("|")
        header_cells = [cell.strip() for cell in header.strip().strip("|").split("|")]
        header_index = max(0, columns_before - 1)
        if header_index < len(header_cells):
            before = f"{header_cells[header_index]} {before}"
        clause = f"{header} {row}"
    labels: list[tuple[int, int, str]] = []
    for field, hints in _FIELD_LABELS:
        for hint in hints:
            position = before.rfind(hint.lower())
            if position >= 0:
                labels.append((position + len(hint), len(hint), field))
    field = max(labels, default=(-1, -1, ""))[2]
    unit: str | None = None
    suffix = after[:12]
    if re.match(r"\s*(?:人民币|yuan)", suffix, re.IGNORECASE) or suffix.lstrip().startswith("元"):
        unit = "yuan"
    elif re.match(r"\s*(?:分|cents?)\b", suffix, re.IGNORECASE):
        unit = "cents"
    elif re.match(r"\s*(?:unit|units)\b", suffix, re.IGNORECASE) or any(suffix.lstrip().startswith(mark) for mark in ("件", "套", "个", "台")):
        unit = "count"
    elif re.match(r"\s*days?\b", suffix, re.IGNORECASE) or any(suffix.lstrip().startswith(mark) for mark in ("天", "日")):
        unit = "days"
    if unit == "days" and any(hint.lower() in clause.lower() for hint in dict(_FIELD_LABELS)["max_lead_days"]):
        field = "max_lead_days"
    if not field and unit:
        field = {"yuan": "total_cents", "cents": "total_cents", "count": "quantity", "days": "lead_days"}[unit]
    fields = {field} if field else set()
    if unit in {"cents", "yuan"}:
        fields &= {"unit_price_cents", "total_cents", "line_total_cents"}
    elif unit == "count":
        fields &= {"quantity", "shortage", "available", "on_hand", "projected", "reserved", "inbound", "safety_stock", "target_stock", "min_order_qty"}
    elif unit == "days":
        fields &= {"lead_days", "max_lead_days"}
    ids = {value.upper() for value in re.findall(
        r"(?<![A-Za-z0-9])(P\d{3}|W\d{2}|S\d{2,3})(?![A-Za-z0-9])", clause, re.IGNORECASE
    )}
    return fields, unit, ",".join(sorted(ids))


def validate_business_claims(answer: str, evidence: list[dict[str, Any]]) -> ClaimCheck:
    violations: list[str] = []
    if _ORDER_CLAIM.search(answer):
        violations.append("P03 is read-only and cannot create or submit orders")
    checked = validate_answer(answer, build_fact_index(evidence))
    violations.extend(checked.violations)
    cited = list(checked.cited_facts)
    facts = [item for item in evidence if "value" in item and item.get("call_id")]
    shortages = [fact for fact in facts if fact.get("field") == "shortage" and isinstance(fact.get("value"), (int, float))]
    for clause in re.split(r"[；;。.!?\n]+", answer):
        clause_lower = clause.lower()
        clause_ids = {value.upper() for value in _IDS.findall(clause)}
        scoped_shortages = [fact for fact in shortages
                            if not clause_ids or str(fact.get("part_id", "")).upper() in clause_ids]
        if any(phrase in clause_lower for phrase in ("库存充足", "无需补货", "没有缺口", "no shortage", "sufficient stock")):
            if any(fact["value"] > 0 for fact in scoped_shortages):
                violations.append("final answer contradicts a successful positive shortage fact")
        if any(phrase in clause_lower for phrase in ("存在缺口", "需要补货", "shortage", "replenish")):
            if any(fact["value"] == 0 for fact in scoped_shortages):
                violations.append("final answer contradicts a successful zero shortage fact")
    return ClaimCheck(passed=not violations, violations=violations, cited_facts=cited)
