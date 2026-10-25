"""按明确字段、单位和实体范围核对结构化业务主张。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True, slots=True)
class FactKey:
    entity_type: str
    entity_id: str | None
    field: str
    part_id: str | None = None
    warehouse_id: str | None = None
    supplier_id: str | None = None
    order_id: str | None = None
    metric: str | None = None


@dataclass(frozen=True, slots=True)
class BusinessFact:
    key: FactKey
    value: int | float | str
    unit: str
    call_id: str
    as_of: str | None = None
    source_refs: tuple[dict[str, Any], ...] = ()
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class FactIndex:
    facts: tuple[BusinessFact, ...]


@dataclass(frozen=True, slots=True)
class BusinessClaim:
    number: str
    fields: frozenset[str]
    unit: str | None
    scope: frozenset[str]
    raw: str
    invalid_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimValidation:
    passed: bool
    violations: tuple[str, ...] = ()
    cited_facts: tuple[dict[str, Any], ...] = ()


_NUMBER = re.compile(
    r"(?<![A-Za-z0-9])(?P<number>-?(?:[\d,]+(?:\.\d+)?|NaN|Infinity|∞|True|False))(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_TIMESTAMP = re.compile(
    r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?",
    re.IGNORECASE,
)
_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9])(?:PO-\d+|[A-Z]\d{2,3})(?![A-Za-z0-9])", re.IGNORECASE)
_SCOPE_TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:PO-\d+|P\d{3}|W\d{2}|S\d{2,3})(?![A-Za-z0-9])", re.IGNORECASE)

_FIELD_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("order_total_cents", ("订单总额", "订单合计", "订单金额", "order total")),
    ("line_total_cents", ("行金额", "行总额", "line total", "line amount")),
    ("unit_price_cents", ("单价", "unit price", "价格")),
    ("shortage", ("缺口", "短缺", "缺货", "不足", "shortage")),
    ("max_lead_days", ("交期上限", "最多", "不超过", "以内", "天内", "max_lead_days")),
    ("lead_days", ("交期", "到货", "lead time")),
    ("min_order_qty", ("起订量", "最低订购量", "最小订购量", "MOQ")),
    ("on_hand", ("在手库存", "在手", "现有库存", "库存", "on_hand")),
    ("available", ("可用库存", "可用", "available")),
    ("projected", ("预计可用", "预测可用", "预计库存", "预测库存", "projected")),
    ("reserved", ("预留", "reserved")),
    ("inbound", ("在途", "inbound")),
    ("safety_stock", ("安全库存", "safety stock")),
    ("target_stock", ("目标库存", "target stock")),
    ("quantity", ("数量", "采购量", "订购量", "quantity")),
    ("total_cents", ("总额", "总价", "金额", "合计", "total")),
)

_FIELD_UNITS = {
    "unit_price_cents": "cents", "line_total_cents": "cents",
    "order_total_cents": "cents", "total_cents": "cents",
    "lead_days": "days", "max_lead_days": "days",
    "quantity": "count", "min_order_qty": "count", "shortage": "count",
    "available": "count", "on_hand": "count", "projected": "count",
    "reserved": "count", "inbound": "count", "safety_stock": "count",
    "target_stock": "count", "part_count": "count", "quote_count": "count",
    "supplier_count": "count", "warning_count": "count", "inventory_count": "count",
    "result_count": "count",
}
_MONEY_FIELDS = frozenset({"unit_price_cents", "line_total_cents", "order_total_cents", "total_cents"})
_COUNT_FIELDS = frozenset({
    "quantity", "min_order_qty", "shortage", "available", "on_hand", "projected",
    "reserved", "inbound", "safety_stock", "target_stock", "part_count", "quote_count",
    "supplier_count", "warning_count", "inventory_count", "result_count",
})


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def build_fact_index(evidence: list[dict[str, Any]]) -> FactIndex:
    """Build named, scoped facts without flattening field identity or snapshots."""
    facts: list[BusinessFact] = []
    for raw in evidence:
        if not isinstance(raw, dict) or "value" not in raw or not raw.get("call_id"):
            continue
        field = str(raw.get("field") or "")
        unit = str(raw.get("unit") or _FIELD_UNITS.get(field, ""))
        value = raw["value"]
        if not field or not unit or isinstance(value, bool):
            continue
        if isinstance(value, (int, float, Decimal)) and _decimal(value) is None:
            continue
        key = FactKey(
            entity_type=str(raw.get("entity_type") or raw.get("entity") or "unknown"),
            entity_id=str(raw.get("entity_id") or raw.get("record_id") or raw.get("id") or "") or None,
            field=field,
            part_id=_upper(raw.get("part_id")),
            warehouse_id=_upper(raw.get("warehouse_id")),
            supplier_id=_upper(raw.get("supplier_id")),
            order_id=_upper(raw.get("order_id")),
            metric=str(raw.get("metric") or "") or None,
        )
        refs = tuple(ref for ref in raw.get("source_refs", []) if isinstance(ref, dict))
        facts.append(BusinessFact(
            key=key, value=value, unit=unit, call_id=str(raw["call_id"]),
            as_of=str(raw.get("as_of")) if raw.get("as_of") else None,
            source_refs=refs, raw=raw,
        ))
    return FactIndex(tuple(facts))


def _upper(value: Any) -> str | None:
    return str(value).upper() if value is not None and str(value) else None


def _table_header(answer: str, line_start: int, line: str) -> list[str]:
    prior = answer[:line_start].splitlines()
    separators = [i for i, row in enumerate(prior) if "|" in row and re.fullmatch(r"[\s|:-]+", row)]
    if not separators or separators[-1] == 0:
        return []
    return [cell.strip().lower() for cell in prior[separators[-1] - 1].strip().strip("|").split("|")]


def _field_from_text(context: str, header_field: str = "") -> str | None:
    text = (header_field + " " + context).lower()
    if "预警" in text:
        return "warning_count"
    # A request ceiling is distinct from an observed lead time. User intent
    # phrases take precedence over a nearby mention of arrival/delivery.
    if any(hint in text for hint in ("要求", "不超过", "以内", "天内", "交期上限", "max_lead_days")):
        return "max_lead_days"
    matched: list[tuple[int, int, str]] = []
    for field, hints in _FIELD_HINTS:
        for hint in hints:
            pos = text.rfind(hint.lower())
            if pos >= 0:
                matched.append((pos + len(hint), len(hint), field))
    if matched:
        return max(matched)[2]
    if re.search(r"预警", text):
        return "warning_count"
    if re.search(r"(?:报价|quote).{0,12}(?:条|个|家|项)|(?:条|个|家|项).{0,12}(?:报价|quote)", text):
        return "quote_count"
    if re.search(r"(?:供应商|supplier).{0,12}(?:家|个|项)|(?:家|个|项).{0,12}(?:供应商|supplier)", text):
        return "supplier_count"
    if re.search(r"(?:零件|物料|sku).{0,12}(?:件|个|项)|(?:个|项).{0,12}(?:零件|物料|sku)", text):
        return "part_count"
    if re.search(r"(?:库存|inventory).{0,12}(?:条|个|项)|(?:条|个|项).{0,12}(?:库存|inventory)", text):
        return "inventory_count"
    if re.search(r"(?:共|合计|总计)\s*$", context.lower()) or re.search(r"^\s*(?:共|合计|总计)", context.lower()):
        return "result_count"
    return None


def _claim_unit(suffix: str) -> str | None:
    value = suffix.lstrip().lower()
    if value.startswith(("人民币", "yuan")) or value.startswith("元"):
        return "yuan"
    if value.startswith("分") or re.match(r"cents?\b", value):
        return "cents"
    if value.startswith(("件", "套", "个", "台", "条", "项", "家", "unit", "units")):
        return "count"
    if value.startswith(("天", "日", "day", "days")):
        return "days"
    return None


def _context_for_number(answer: str, start: int, end: int) -> tuple[str, str, frozenset[str], str]:
    line_start = answer.rfind("\n", 0, start) + 1
    line_end = answer.find("\n", end)
    if line_end < 0:
        line_end = len(answer)
    row = answer[line_start:line_end]
    header_field = ""
    if "|" in row:
        cells_before = row[:start - line_start].count("|")
        headers = _table_header(answer, line_start, row)
        index = max(0, cells_before - 1)
        if index < len(headers):
            header_field = headers[index]
    boundaries = "，,、；;。.!?\n|：:"
    left = max((answer.rfind(mark, 0, start) for mark in boundaries), default=-1) + 1
    right_candidates = [answer.find(mark, end) for mark in boundaries]
    right = min((pos for pos in right_candidates if pos >= 0), default=len(answer))
    context = answer[left:right]
    if "|" in row:
        context = row
    all_context = f"{context} {header_field}"
    scope = frozenset(value.upper() for value in _SCOPE_TOKEN.findall(all_context))
    suffix = answer[end:end + 24]
    return context, header_field, scope, suffix


def extract_business_claims(answer: str) -> tuple[list[BusinessClaim], list[str]]:
    claims: list[BusinessClaim] = []
    violations: list[str] = []
    identifiers = list(_IDENTIFIER.finditer(answer))
    timestamps = list(_TIMESTAMP.finditer(answer))
    for match in _NUMBER.finditer(answer):
        start, end = match.span("number")
        if any(item.start() <= start and end <= item.end() for item in identifiers + timestamps):
            continue
        raw_number = match.group("number")
        context, header_field, scope, suffix = _context_for_number(answer, start, end)
        unit = _claim_unit(suffix)
        field = _field_from_text(context, header_field)
        if unit is None and field is None:
            if re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?\s*", answer):
                violations.append(f"numeric claim {raw_number} has no bound fact field and unit")
            continue
        if unit is None and field:
            unit = _FIELD_UNITS.get(field)
        if field:
            fields = frozenset({field})
        elif unit == "yuan" or unit == "cents":
            fields = _MONEY_FIELDS
        elif unit == "count":
            fields = _COUNT_FIELDS
        elif unit == "days":
            fields = frozenset({"lead_days", "max_lead_days"})
        else:
            fields = frozenset()
        invalid_reason = None
        lowered = raw_number.lower()
        if lowered in {"true", "false"}:
            invalid_reason = "boolean is not a numeric business value"
        else:
            try:
                numeric = Decimal(raw_number.replace(",", ""))
            except InvalidOperation:
                numeric = Decimal("NaN")
            if not numeric.is_finite():
                invalid_reason = "non-finite numeric claim"
            elif unit in {"yuan", "cents", "count", "days"}:
                canonical = numeric * 100 if unit == "yuan" else numeric
                if unit == "yuan" and canonical != canonical.to_integral_value():
                    invalid_reason = "money precision exceeds one fen"
                elif unit in {"cents", "count", "days"} and numeric != numeric.to_integral_value():
                    invalid_reason = f"{unit} value must be an integer"
                elif canonical < 0:
                    invalid_reason = "negative business values are not accepted"
        if invalid_reason:
            violations.append(f"numeric claim {raw_number} is invalid: {invalid_reason}")
            continue
        claims.append(BusinessClaim(raw_number, fields, unit, scope, context, invalid_reason))
    return claims, violations


def _canonical_value(claim: BusinessClaim) -> Decimal | None:
    try:
        value = Decimal(claim.number.replace(",", ""))
    except InvalidOperation:
        return None
    if claim.unit == "yuan":
        value *= 100
    return value if value.is_finite() else None


def _fact_decimal(fact: BusinessFact) -> Decimal | None:
    if isinstance(fact.value, bool):
        return None
    try:
        value = Decimal(str(fact.value))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _fact_scope(fact: BusinessFact) -> frozenset[str]:
    key = fact.key
    return frozenset(value for value in (
        key.entity_id.upper() if key.entity_id else None,
        key.part_id, key.warehouse_id, key.supplier_id, key.order_id,
    ) if value)


def _dedupe_latest(facts: list[BusinessFact]) -> list[BusinessFact]:
    by_snapshot: dict[tuple[FactKey, str], BusinessFact] = {}
    for fact in facts:
        stamp = fact.as_of or ""
        key = (fact.key, stamp)
        prior = by_snapshot.get(key)
        if prior is None or fact.call_id < prior.call_id:
            by_snapshot[key] = fact
    by_identity: dict[FactKey, list[BusinessFact]] = {}
    for fact in by_snapshot.values():
        by_identity.setdefault(fact.key, []).append(fact)
    selected: list[BusinessFact] = []
    for group in by_identity.values():
        latest = max((fact.as_of or "" for fact in group), default="")
        selected.extend(fact for fact in group if (fact.as_of or "") == latest)
    return selected


def validate_claims(claims: list[BusinessClaim], index: FactIndex) -> ClaimValidation:
    violations: list[str] = []
    cited: list[dict[str, Any]] = []
    for claim in claims:
        expected = _canonical_value(claim)
        if expected is None:
            violations.append(f"numeric claim {claim.number} is invalid")
            continue
        candidates = [
            fact for fact in index.facts
            if fact.key.field in claim.fields
            and fact.unit == ("cents" if claim.unit == "yuan" else claim.unit or fact.unit)
            and _fact_decimal(fact) == expected
        ]
        if claim.scope:
            candidates = [fact for fact in candidates if claim.scope.issubset(_fact_scope(fact))]
        candidates = _dedupe_latest(candidates)
        if not candidates:
            violations.append(f"numeric claim {claim.number} does not match its field, unit, and entity scope")
            continue
        # The same preview row can be exposed through both its result envelope
        # and a source reference. Collapse those duplicate observations by
        # business scope, while keeping equal values for distinct entities
        # ambiguous when the answer omits their scope.
        identities = {
            (
                fact.key.field, fact.unit, _fact_decimal(fact), fact.key.part_id,
                fact.key.warehouse_id, fact.key.supplier_id, fact.key.order_id,
            )
            for fact in candidates
        }
        if len(identities) > 1:
            violations.append(f"CLAIM_AMBIGUOUS: numeric claim {claim.number} matches multiple facts; state the entity and field")
            continue
        selected = candidates[0]
        raw = dict(selected.raw or {})
        if not raw.get("call_id") or not selected.key.entity_type:
            violations.append(f"numeric claim {claim.number} has no traceable source")
            continue
        cited.append(raw)
    return ClaimValidation(not violations, tuple(violations), tuple(cited))


def validate_answer(answer: str, index: FactIndex) -> ClaimValidation:
    claims, extraction_violations = extract_business_claims(answer)
    checked = validate_claims(claims, index)
    violations = tuple([*extraction_violations, *checked.violations])
    return ClaimValidation(not violations, violations, checked.cited_facts)
