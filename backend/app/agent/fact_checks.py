"""按明确字段、单位和实体范围核对结构化业务主张。"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
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
    quote_id: str | None = None


@dataclass(frozen=True, slots=True)
class BusinessFact:
    key: FactKey
    value: bool | int | float | str
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
_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9])(?:PO-[A-Z0-9]+|[A-Z][A-Z0-9]*-\d+|[A-Z]\d{2,3})(?![A-Za-z0-9])", re.IGNORECASE)
_SCOPE_TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:PO-[A-Z0-9]+|[PQ]\d{2,3}|W\d{2}|S\d{2,3})(?![A-Za-z0-9])", re.IGNORECASE)

_FIELD_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("order_total_cents", ("订单总额", "订单合计", "订单金额", "order total")),
    ("line_total_cents", ("行金额", "行总额", "line total", "line amount", "line_total_cents")),
    ("unit_price_cents", ("单价", "unit price", "价格")),
    ("shortage", ("缺口", "短缺", "缺货", "不足", "shortage")),
    ("max_lead_days", ("交期上限", "最晚交期", "交期要求", "最多", "不超过", "以内", "天内", "上限", "deadline", "max_lead_days")),
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
        if not field or not unit or (isinstance(value, bool) and unit != "boolean"):
            continue
        if not isinstance(value, bool) and isinstance(value, (int, float, Decimal)) and _decimal(value) is None:
            continue
        quote_fact = bool(raw.get("quote_id")) and field in {
            "is_valid", "lead_days", "unit_price_cents", "min_order_qty", "valid_until",
        }
        key = FactKey(
            entity_type="quote" if quote_fact else str(raw.get("entity_type") or raw.get("entity") or "unknown"),
            entity_id=(str(raw["quote_id"]) if quote_fact else
                       str(raw.get("entity_id") or raw.get("record_id") or raw.get("id") or "") or None),
            field=field,
            part_id=_upper(raw.get("part_id")),
            warehouse_id=_upper(raw.get("warehouse_id")),
            supplier_id=_upper(raw.get("supplier_id")),
            order_id=_upper(raw.get("order_id")),
            metric=str(raw.get("metric") or "") or None,
            quote_id=_upper(raw.get("quote_id")),
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
    if not separators:
        return []
    separator = separators[-1]
    if separator == 0:
        return []
    header = prior[separator - 1]
    table_rows = [*prior[separator + 1:], line]
    if "|" not in header or any(not row.strip() or "|" not in row for row in table_rows):
        return []
    return [cell.strip().lower() for cell in header.strip().strip("|").split("|")]


def _nearest_field(matches: list[tuple[int, int, str]], position: int | None) -> str:
    """Bind the label closest to the number; a trailing label may still describe it."""
    if position is None:
        return max(matches)[2]
    before = [match for match in matches if match[0] <= position]
    if before:
        return max(before)[2]
    after = [match for match in matches if match[0] - match[1] >= position]
    if after:
        return min(after, key=lambda match: match[0] - match[1])[2]
    return max(matches)[2]


def _field_from_text(context: str, header_field: str = "", *, position: int | None = None) -> str | None:
    header = header_field.lower().strip()
    text = context.lower()
    if re.search(
        r"(?:(?:物料|采购|补货|订购)数量|(?<![A-Za-z0-9_])quantity(?![A-Za-z0-9_]))"
        r"\s*(?:为|[:=：])?\s*[-+]?\d", text,
    ):
        return "quantity"
    if re.search(r"(?:共|合计|总计)\s*\d[\d,]*(?:\s*(?:条|个|项))?\s*(?:库存记录|inventory records?)", text):
        return "inventory_count"
    if re.search(r"(?:预警|警告|warning).{0,8}(?:共|数量|条数|个数|count|[:：]?\s*\d+\s*(?:条|个))|\d+\s*(?:条|个)\s*(?:库存)?(?:预警|警告|warning)", text):
        return "warning_count"
    # A request ceiling requires an explicit temporal upper-bound expression.
    if (any(hint in text for hint in ("不超过", "最多", "以内", "天内", "日内", "交期上限", "max_lead_days"))
            and any(unit in text for unit in ("天", "日", "day"))):
        return "max_lead_days"
    local_matches = [
        (text.rfind(hint.lower()) + len(hint), len(hint), field)
        for field, hints in _FIELD_HINTS
        for hint in hints
        if hint.lower() in text
    ]
    if local_matches:
        return _nearest_field(local_matches, position)
    if header:
        if re.search(r"(?:预警|警告)(?:数量|条数|个数|数|count)", header):
            return "warning_count"
        header_matches = [
            (header.rfind(hint.lower()) + len(hint), len(hint), field)
            for field, hints in _FIELD_HINTS
            for hint in hints
            if hint.lower() in header
        ]
        if header_matches:
            return max(header_matches)[2]
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
    # Markdown emphasis around a unit is presentation only (for example **55套**).
    value = re.sub(r"^[\s*_\x60]+", "", suffix).lower()
    explicit_unit = re.match(r"[（(]?\s*单位\s*(?:[:：]\s*)?", value)
    if explicit_unit:
        value = re.sub(r"^[\s*_\x60]+", "", value[explicit_unit.end():])
    if value.startswith(("人民币", "yuan", "元")):
        return "yuan"
    if value.startswith("分") or re.match(r"cents?\b", value):
        return "cents"
    for unit in ("件", "套", "个", "台", "条", "项", "家", "对", "片"):
        if value.startswith(unit):
            return unit
    if value.startswith(("unit", "units")):
        return "count"
    if value.startswith(("天", "日", "day", "days")):
        return "days"
    return None


_UNIT_CLAUSE = re.compile(
    r"^[，,、；;]\s*(?:单位|business unit|unit)\s*[:：]?\s*"
    r"([件套个台条项家对片]|units?|count)",
    re.IGNORECASE,
)


def _unit_after_clause(answer: str, end: int) -> str | None:
    """A separate unit label binds only the adjacent quantity in the same sentence."""
    match = _UNIT_CLAUSE.match(answer[end:])
    if not match:
        return None
    return _claim_unit(match.group(1))


def _boolean_field_from_text(context: str) -> str | None:
    text = context.lower()
    if any(term in text for term in ("is_valid", "valid quote", "有效报价", "报价有效", "有效性")):
        return "is_valid"
    if any(term in text for term in ("warning", "预警")):
        return "warning"
    if any(term in text for term in ("active", "启用状态", "是否启用")):
        return "active"
    return None


_ENTITY_HEADER_HINTS = (
    "实体", "零件", "物料", "部件", "仓库", "供应商", "报价",
    "entity", "part", "item", "sku", "warehouse", "supplier", "quote",
)
_FIELD_HEADER_HINTS = ("字段", "指标", "属性", "field", "metric", "attribute")
_UNIT_HEADER_HINTS = ("单位", "unit")
_VALUE_HEADER_HINTS = ("值", "数值", "内容", "value", "content")
_CLAUSE_BOUNDARIES = "，,、；;。.!?？\n|（）()"
_ROW_PUNCTUATION = "，,、；;。.!?？\n|()（）"


@dataclass(frozen=True, slots=True)
class _NumberContext:
    context: str
    field_hint: str
    scope: frozenset[str]
    suffix: str
    position: int | None = None
    unit_hint: str | None = None


def _table_roles(headers: list[str]) -> dict[str, object]:
    """Assign column roles so a vertical table keeps its field/value/unit cells."""
    roles: dict[str, object] = {
        "entity_cols": [], "field_col": None, "unit_col": None, "value_cols": [],
    }
    for index, header in enumerate(headers):
        text = header.lower()
        if any(hint in text for hint in _FIELD_HEADER_HINTS):
            if roles["field_col"] is None:
                roles["field_col"] = index
        elif any(hint in text for hint in _UNIT_HEADER_HINTS):
            if roles["unit_col"] is None:
                roles["unit_col"] = index
        elif any(hint in text for hint in _VALUE_HEADER_HINTS):
            roles["value_cols"].append(index)  # type: ignore[union-attr]
        elif any(hint in text for hint in _ENTITY_HEADER_HINTS):
            roles["entity_cols"].append(index)  # type: ignore[union-attr]
    return roles


def _id_only_tokens(cell: str) -> list[str]:
    """Return entity IDs only when the cell is just IDs, not prose that mentions them."""
    text = re.sub(r"[*_\x60]+", "", cell)
    tokens = _SCOPE_TOKEN.findall(text)
    if not tokens:
        return []
    residual = _SCOPE_TOKEN.sub("", text)
    if re.sub(r"[\s/:：,、\-|]+", "", residual):
        return []
    return tokens


def _inherited_scope_ids(answer: str, left: int) -> list[str]:
    """Reuse the nearest entity of the same sentence, never across a sentence or a new number."""
    sentence_start = max(answer.rfind(mark, 0, left) for mark in "。！？!?\n") + 1
    prefix = answer[sentence_start:left]
    prefix = re.split(r"但是|然而|不过|但|却", prefix)[-1]
    for segment in reversed(re.split(r"[，,、；;：:]", prefix)):
        if _NUMBER.search(segment):
            return []
        ids = _SCOPE_TOKEN.findall(segment)
        if ids:
            return ids
    return []


def _heading_scope_ids(answer: str, line_start: int) -> list[str]:
    if line_start <= 0:
        return []
    preceding_lines = answer[:line_start].splitlines()
    heading = preceding_lines[-1] if preceding_lines else ""
    heading_tokens = _SCOPE_TOKEN.findall(heading)
    residual = _SCOPE_TOKEN.sub("", heading)
    if heading_tokens and not re.sub(r"[\s/:：,|()（）*\x60-]", "", residual):
        return heading_tokens
    return []


def _table_heading_scope_ids(answer: str, line_start: int) -> list[str]:
    """A heading above the table scopes rows that carry no entity column of their own."""
    prior = answer[:line_start].splitlines()
    separators = [i for i, row in enumerate(prior)
                  if "|" in row and re.fullmatch(r"[\s|:-]+", row)]
    if not separators or separators[-1] < 1:
        return []
    index = separators[-1] - 2
    while index >= 0 and "|" in prior[index]:
        index -= 1
    while index >= 0 and not prior[index].strip():
        index -= 1
    if index < 0:
        return []
    heading = prior[index]
    heading_tokens = _SCOPE_TOKEN.findall(heading)
    residual = _SCOPE_TOKEN.sub("", heading)
    if heading_tokens and not re.sub(r"[\s/:：,|()（）*\x60-]", "", residual):
        return heading_tokens
    return []


def _text_context(answer: str, start: int, end: int) -> _NumberContext:
    left = max(answer.rfind(mark, 0, start) for mark in _CLAUSE_BOUNDARIES) + 1
    right = min(
        (position for position in (answer.find(mark, end) for mark in _CLAUSE_BOUNDARIES) if position >= 0),
        default=len(answer),
    )
    context = answer[left:right]
    scope_ids = _SCOPE_TOKEN.findall(context)
    if not scope_ids:
        scope_ids = _inherited_scope_ids(answer, left)
    if not scope_ids:
        scope_ids = _heading_scope_ids(answer, answer.rfind("\n", 0, start) + 1)
    return _NumberContext(
        context=context,
        field_hint="",
        scope=frozenset(value.upper() for value in scope_ids),
        suffix=answer[end:end + 32],
        position=start - left,
    )


def _table_context(answer: str, line_start: int, row: str, start: int, end: int) -> _NumberContext:
    headers = _table_header(answer, line_start, row)
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    index = max(0, row[:start - line_start].count("|") - (1 if row.lstrip().startswith("|") else 0))
    roles = _table_roles(headers)
    context = row
    local_ids: list[str] = []
    position: int | None = None
    if index < len(cells):
        cell = cells[index]
        cell_left = row.find("|") + 1 if row.lstrip().startswith("|") else 0
        for _ in range(index):
            separator = row.find("|", cell_left)
            if separator < 0:
                break
            cell_left = separator + 1
        cell_right = row.find("|", cell_left)
        if cell_right < 0:
            cell_right = len(row)
        cell_value_left = cell_left + len(row[cell_left:cell_right]) - len(row[cell_left:cell_right].lstrip())
        local_start = start - (line_start + cell_value_left)
        local_end = end - (line_start + cell_value_left)
        left = max((cell.rfind(mark, 0, local_start) for mark in _ROW_PUNCTUATION), default=-1) + 1
        right = min(
            (pos for pos in (cell.find(mark, local_end) for mark in _ROW_PUNCTUATION) if pos >= 0),
            default=len(cell),
        )
        context = cell[left:right].strip()
        position = local_start - left
        local_ids = _SCOPE_TOKEN.findall(cell[left:right])
        supplier_matches = list(re.finditer(r"(?<![A-Za-z0-9])S\d{2,3}(?![A-Za-z0-9])", cell, re.IGNORECASE))
        if supplier_matches:
            nearest_supplier = min(supplier_matches, key=lambda item: abs(item.start() - local_start))
            local_ids.append(nearest_supplier.group(0))
    field_hint = ""
    field_col = roles["field_col"]
    if isinstance(field_col, int) and field_col < len(cells) and field_col != index:
        field_hint = cells[field_col]
    elif index < len(headers):
        field_hint = headers[index]
    entity_ids: list[str] = []
    for column in roles["entity_cols"]:  # type: ignore[union-attr]
        if column < len(cells):
            entity_ids.extend(_id_only_tokens(cells[column]))
    row_scope = entity_ids or [
        token for token in _SCOPE_TOKEN.findall(row) if token.upper().startswith(("P", "W"))
    ]
    scope_ids = [*row_scope, *local_ids]
    if not scope_ids:
        scope_ids = _table_heading_scope_ids(answer, line_start)
    unit_hint = None
    unit_col = roles["unit_col"]
    if isinstance(unit_col, int) and unit_col < len(cells):
        unit_hint = _claim_unit(cells[unit_col])
    return _NumberContext(
        context=context,
        field_hint=field_hint,
        scope=frozenset(value.upper() for value in scope_ids),
        suffix=answer[end:end + 32],
        position=position,
        unit_hint=unit_hint,
    )


def _context_for_number(answer: str, start: int, end: int) -> _NumberContext:
    line_start = answer.rfind("\n", 0, start) + 1
    line_end = answer.find("\n", end)
    if line_end < 0:
        line_end = len(answer)
    row = answer[line_start:line_end]
    if "|" in row:
        return _table_context(answer, line_start, row, start, end)
    return _text_context(answer, start, end)


def _explicit_query_count_field(answer: str, start: int, end: int, unit: str | None) -> str | None:
    """Bind a returned row count to a named query across explanatory parentheses."""
    if unit in {"yuan", "cents", "days"}:
        return None
    left = max((answer.rfind(mark, 0, start) for mark in "。!?！？；;\n"), default=-1) + 1
    prefix = answer[max(left, start - 240):start]
    suffix = answer[end:end + 24]
    total_label = re.search(
        r"(?<![A-Za-z0-9_])total`?\s*(?:字段)?\s*(?:[=:：]|为)\s*$", prefix, re.I,
    )
    if not total_label and re.search(
        r"(?:单价|总额|总价|金额|价格|unit_price|total_cents)[^，,；;。\n]*$", prefix, re.I,
    ):
        return None
    row_count = re.match(r"\s*(?:条|个|项)\s*(?:(?:库存|预警|报价|供应商)\s*)?(?:记录|结果)", suffix)
    returned_count = (re.search(r"(?:返回|共|合计|总计)\s*$", prefix)
                      and re.match(r"\s*(?:条|个|项)(?!元|分)", suffix))
    count_label = re.search(r"(?:记录条数|记录数|结果条数|返回条数|结果集计数)\s*(?:为|[=:：])\s*$", prefix)
    if not (total_label or row_count or returned_count or count_label):
        return None
    hints = (
        (r"(?<![A-Za-z0-9_])inventory_warning(?![A-Za-z0-9_])|(?:库存)?预警(?:查询|记录|列表)?", "warning_count"),
        (r"(?<![A-Za-z0-9_])inventory_page(?![A-Za-z0-9_])|库存(?:快照|分页|记录|查询)", "inventory_count"),
        (r"(?<![A-Za-z0-9_])quote_list(?![A-Za-z0-9_])|报价(?:查询|记录|列表)", "quote_count"),
        (r"(?<![A-Za-z0-9_])supplier_query(?![A-Za-z0-9_])|供应商(?:查询|列表)", "supplier_count"),
        (r"(?<![A-Za-z0-9_])part_search(?![A-Za-z0-9_])|物料(?:查询|列表)", "part_count"),
    )
    matches = [(match.end(), field) for pattern, field in hints for match in re.finditer(pattern, prefix, re.I)]
    return max(matches)[1] if matches else None


def extract_business_claims(answer: str) -> tuple[list[BusinessClaim], list[str]]:
    claims: list[BusinessClaim] = []
    violations: list[str] = []
    identifiers = list(_IDENTIFIER.finditer(answer))
    timestamps = list(_TIMESTAMP.finditer(answer))
    for match in _NUMBER.finditer(answer):
        start, end = match.span("number")
        if any(item.start() <= start and end <= item.end() for item in identifiers + timestamps):
            continue
        if re.search(r"(?:版本|version)\s*$", answer[max(0, start - 16):start], re.IGNORECASE):
            continue
        raw_number = match.group("number")
        extracted = _context_for_number(answer, start, end)
        context = extracted.context
        scope = extracted.scope
        unit = _claim_unit(extracted.suffix) or extracted.unit_hint
        if unit is None:
            unit = _unit_after_clause(answer, end)
        field = _field_from_text(context, extracted.field_hint, position=extracted.position)
        query_count = _explicit_query_count_field(answer, start, end, unit)
        if query_count is not None:
            field = query_count
        if raw_number.lower() in {"true", "false"}:
            boolean_field = _boolean_field_from_text(context)
            if boolean_field:
                claims.append(BusinessClaim(raw_number, frozenset({boolean_field}), "boolean", scope, context))
            elif unit is not None or field is not None:
                violations.append(f"numeric claim {raw_number} is invalid: boolean is not a numeric business value")
            continue
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
        key.quote_id,
    ) if value)


def _scope_matches_fact(scope: frozenset[str], fact: BusinessFact) -> bool:
    required = set(scope)
    # Quotes are part/supplier scoped, not warehouse scoped, unless the source
    # explicitly includes a warehouse attribute. Retain the warehouse context
    # only when it is present on the fact itself.
    if fact.key.entity_type == "quote" and fact.key.warehouse_id is None and fact.key.part_id:
        required = {value for value in required if not value.startswith("W")}
    return required.issubset(_fact_scope(fact))


def _unit_matches_claim(fact: BusinessFact, claim: BusinessClaim, index: FactIndex) -> bool:
    expected_unit = "cents" if claim.unit == "yuan" else claim.unit
    if fact.unit == expected_unit:
        return True
    if (claim.unit in {"件", "套", "个", "台", "条", "项", "家", "片", "对"}
            and fact.unit == "count" and fact.key.field == "min_order_qty"
            and fact.key.entity_type == "quote"):
        return any(
            candidate.key.entity_type == "quote"
            and candidate.key.entity_id == fact.key.entity_id
            and candidate.key.part_id == fact.key.part_id
            and candidate.key.supplier_id == fact.key.supplier_id
            and candidate.key.field == "part_unit"
            and candidate.unit == "label"
            and candidate.value == claim.unit
            for candidate in index.facts
        )
    return False


def _part_unit_labels(fact: BusinessFact, index: FactIndex) -> set[str]:
    """Collect verified business-unit labels for the exact quote/part/supplier."""
    quote_id = fact.key.quote_id or fact.key.entity_id
    return {
        str(candidate.value)
        for candidate in index.facts
        if candidate.key.entity_type == "quote"
        and candidate.key.field == "part_unit"
        and (candidate.key.quote_id or candidate.key.entity_id) == quote_id
        and candidate.key.part_id == fact.key.part_id
        and candidate.key.supplier_id == fact.key.supplier_id
        and candidate.unit == "label"
        and isinstance(candidate.value, str)
    }


def _canonical_fact_for_comparison(fact: BusinessFact, index: FactIndex) -> BusinessFact | None:
    """Normalize a quote MOQ to its verified business unit before snapshot selection.

    Only the same quote/part/supplier with a trusted part_unit can be normalized;
    conflicting labels return None so no source is silently preferred.
    """
    if fact.key.entity_type != "quote" or fact.key.field != "min_order_qty":
        return fact
    labels = _part_unit_labels(fact, index)
    if not labels:
        return fact
    if len(labels) > 1:
        return None
    unit = next(iter(labels))
    return fact if fact.unit == unit else replace(fact, unit=unit)


def _normalized_stamp(value: str | None) -> tuple[int, str]:
    if not value:
        return (0, "")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (1, parsed.astimezone(timezone.utc).isoformat())
    except ValueError:
        return (0, value)


def _fact_identity(fact: BusinessFact) -> tuple[Any, ...]:
    """Use business scope for inventory observations; keep source identity separate."""
    key = fact.key
    if key.entity_type == "quote":
        # The same quote can be returned once from quote_list and once embedded
        # in a warehouse-scoped preview. Warehouse context does not create a
        # second quote fact; keep it on the selected fact for claim matching.
        return ("quote_business_fact", key.quote_id or key.entity_id, key.field,
                key.part_id, key.supplier_id, key.metric, fact.unit)
    if key.entity_type in {"inventory", "replenishment", "preview"} and key.part_id and key.warehouse_id:
        return ("inventory_business_fact", key.field, key.part_id, key.warehouse_id,
                key.supplier_id, key.order_id, key.quote_id, key.metric, fact.unit)
    return (key.entity_type, key.entity_id, key.field, key.part_id, key.warehouse_id,
            key.supplier_id, key.order_id, key.quote_id, key.metric, fact.unit)


def _latest_facts(facts: list[BusinessFact]) -> tuple[list[BusinessFact], list[str]]:
    """Select current snapshots by scoped business identity before value matching."""
    identities: dict[tuple[Any, ...], list[BusinessFact]] = {}
    for fact in facts:
        identities.setdefault(_fact_identity(fact), []).append(fact)
    selected: list[BusinessFact] = []
    conflicts: list[str] = []
    for identity, group in identities.items():
        latest_stamp = max(_normalized_stamp(item.as_of) for item in group)
        latest = [item for item in group if _normalized_stamp(item.as_of) == latest_stamp]
        values = {repr(item.value) for item in latest}
        if len(values) > 1:
            conflicts.append(f"CLAIM_AMBIGUOUS: conflicting facts at the latest snapshot for {identity[2]}")
            continue
        # Identical facts can be duplicated through an envelope and source ref.
        selected.append(sorted(latest, key=lambda item: item.call_id)[0])
    return selected, conflicts


def validate_claims(claims: list[BusinessClaim], index: FactIndex) -> ClaimValidation:
    violations: list[str] = []
    cited: list[dict[str, Any]] = []
    for claim in claims:
        if claim.unit == "boolean":
            expected_bool = claim.number.lower() == "true"
            candidates = [fact for fact in index.facts if fact.key.field in claim.fields
                          and fact.unit == "boolean"]
            if claim.scope:
                candidates = [fact for fact in candidates if _scope_matches_fact(claim.scope, fact)]
            candidates, snapshot_issues = _latest_facts(candidates)
            violations.extend(snapshot_issues)
            if not candidates:
                violations.append(f"boolean claim {claim.number} does not match its field and entity scope")
                continue
            if candidates[0].value is not expected_bool:
                violations.append(f"boolean claim {claim.number} does not match the latest fact")
                continue
            identities = {
                (fact.key.field, fact.key.part_id, fact.key.warehouse_id, fact.key.supplier_id, fact.key.order_id)
                for fact in candidates
            }
            if len(identities) > 1:
                violations.append(f"CLAIM_AMBIGUOUS: boolean claim {claim.number} matches multiple entities")
                continue
            cited.append(dict(candidates[0].raw or {}))
            continue
        expected = _canonical_value(claim)
        if expected is None:
            violations.append(f"numeric claim {claim.number} is invalid")
            continue
        candidates: list[BusinessFact] = []
        for fact in index.facts:
            if fact.key.field not in claim.fields:
                continue
            # Normalize the same quote's MOQ representation before selecting the
            # latest snapshot; the compared fact keeps its original source and as_of.
            normalized = _canonical_fact_for_comparison(fact, index)
            if normalized is None:
                continue
            if not (_unit_matches_claim(normalized, claim, index)
                    or (normalized.unit == "count"
                        and claim.unit in {"件", "套", "个", "台", "条", "项", "家", "片"}
                        and normalized.key.field in {"part_count", "quote_count", "supplier_count",
                                                     "warning_count", "inventory_count", "result_count"})):
                continue
            candidates.append(normalized)
        if claim.scope:
            candidates = [
                fact for fact in candidates
                if (
                    (claim.scope - {value for value in claim.scope if value.startswith(("S", "W"))}).issubset(_fact_scope(fact))
                    if fact.key.entity_type == "request_constraint" and "max_lead_days" in claim.fields
                    else _scope_matches_fact(claim.scope, fact)
                )
            ]
        candidates, snapshot_issues = _latest_facts(candidates)
        violations.extend(snapshot_issues)
        if not candidates:
            claimed_scope = ",".join(sorted(claim.scope)) or "none"
            violations.append(
                f"numeric claim {claim.number} does not match its field, unit, and entity scope "
                f"(claimed scope: {claimed_scope}; unit: {claim.unit or 'unknown'}); "
                "state the exact entity and its business unit"
            )
            continue
        candidates = [fact for fact in candidates if _fact_decimal(fact) == expected]
        if not candidates:
            violations.append(f"numeric claim {claim.number} does not match the latest fact")
            continue
        # The same preview row can be exposed through both its result envelope
        # and a source reference. Collapse those duplicate observations by
        # business scope, while keeping equal values for distinct entities
        # ambiguous when the answer omits their scope.
        identities = {_fact_identity(fact) for fact in candidates}
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
