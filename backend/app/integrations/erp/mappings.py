"""ERP mapping helpers. Unknown remote fields stay unknown; money never uses float arithmetic."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


def yuan_to_cents(value: Any) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid ERP yuan amount") from exc
    if not amount.is_finite() or amount * 100 != (amount * 100).to_integral_value():
        raise ValueError("ERP amount has fractional cents")
    return int(amount * 100)


@dataclass(frozen=True)
class MappedPage:
    records: list[dict[str, Any]]
    total: int | None
    page: int
    page_size: int
    complete: bool
    warning: str | None = None


def normalize_page(payload: dict[str, Any], *, page: int, page_size: int) -> MappedPage:
    rows = payload.get("records", payload.get("data", []))
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("ERP page records must be an array of objects")
    total_raw = payload.get("total")
    total = total_raw if isinstance(total_raw, int) and not isinstance(total_raw, bool) and total_raw >= 0 else None
    warning = None
    if total is None:
        warning = "ERP did not provide a trusted total"
    elif total == 0 and rows:
        warning = "ERP total contradicts returned records"
    complete = warning is None and (page - 1) * page_size + len(rows) >= total
    if warning is None and not complete:
        warning = "page is not the complete result set"
    return MappedPage(rows, total, page, page_size, complete, warning)


def map_order(raw: dict[str, Any]) -> dict[str, Any]:
    status = raw.get("status")
    known = {"submitted", "shipped", "received", "completed", "cancelled"}
    result = {"id": str(raw.get("id", raw.get("order_id", ""))),
              "number": str(raw.get("number", "")), "raw_status": status,
              "status": status if status in known else "unknown",
              "total_cents": yuan_to_cents(raw["total_yuan"]) if "total_yuan" in raw else None,
              "items": [map_order_item(item) for item in raw.get("items", raw.get("details", []))
                        if isinstance(item, dict)], "missing_fields": []}
    for field in ("id", "number", "status", "total_yuan", "items"):
        if field not in raw and not (field == "id" and "order_id" in raw):
            result["missing_fields"].append(field)
    return result


def _first(raw: dict[str, Any], *keys: str) -> Any:
    return next((raw[key] for key in keys if key in raw), None)


def map_supplier(raw: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(_first(raw, "id", "supplier_id", "code") or ""),
            "code": str(_first(raw, "code", "supplier_code") or ""),
            "name": str(_first(raw, "name", "supplier_name") or ""),
            "status": _first(raw, "status", "state"), "raw_status": _first(raw, "status", "state"),
            "credit_rating": _first(raw, "credit_rating", "rating"),
            "missing_fields": [key for key, value in (("id", _first(raw, "id", "supplier_id", "code")),
                ("code", _first(raw, "code", "supplier_code")), ("name", _first(raw, "name", "supplier_name")),
                ("status", _first(raw, "status", "state"))) if value is None]}


def map_part(raw: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(_first(raw, "id", "part_id", "code") or ""),
            "code": str(_first(raw, "code", "part_code") or ""),
            "name": str(_first(raw, "name", "part_name") or ""),
            "specification": _first(raw, "specification", "spec") or "",
            "unit": _first(raw, "unit", "unit_name"), "active": _first(raw, "active", "enabled"),
            "missing_fields": [key for key, value in (("id", _first(raw, "id", "part_id", "code")),
                ("code", _first(raw, "code", "part_code")), ("name", _first(raw, "name", "part_name")),
                ("unit", _first(raw, "unit", "unit_name"))) if value is None]}


def map_inventory(raw: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(_first(raw, "id", "inventory_id") or ""),
            "part_id": str(_first(raw, "part_id", "material_id") or ""),
            "warehouse_id": str(_first(raw, "warehouse_id", "warehouse_code") or ""),
            "on_hand": _first(raw, "on_hand", "quantity", "stock_qty"),
            "reserved": _first(raw, "reserved", "reserved_qty"),
            "inbound": _first(raw, "inbound", "inbound_qty"),
            "missing_fields": [key for key in ("id", "part_id", "warehouse_id", "on_hand", "reserved", "inbound")
                if _first(raw, key, {"part_id": "material_id", "warehouse_id": "warehouse_code",
                    "reserved": "reserved_qty", "inbound": "inbound_qty"}.get(key, key)) is None]}


def map_order_item(raw: dict[str, Any]) -> dict[str, Any]:
    result = {"part_id": str(_first(raw, "part_id", "material_id") or ""),
              "quantity": _first(raw, "quantity", "qty"),
              "unit_price_cents": yuan_to_cents(_first(raw, "unit_price_yuan", "unit_price"))
                  if _first(raw, "unit_price_yuan", "unit_price") is not None else None,
              "line_total_cents": yuan_to_cents(_first(raw, "line_total_yuan", "amount"))
                  if _first(raw, "line_total_yuan", "amount") is not None else None,
              "received_qty": _first(raw, "received_qty", "received_quantity")}
    result["missing_fields"] = [key for key, value in result.items() if value is None and key != "missing_fields"]
    return result


def map_quote(raw: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field, aliases in (("min_order_qty", ("min_order_qty", "moq")),
        ("lead_days", ("lead_days", "delivery_days")), ("valid_until", ("valid_until", "expires_at")))
        if _first(raw, *aliases) is None]
    return {"id": str(_first(raw, "id", "quote_id") or ""), "raw": dict(raw),
            "unit_price_cents": yuan_to_cents(_first(raw, "unit_price_yuan", "unit_price"))
                if _first(raw, "unit_price_yuan", "unit_price") is not None else None,
            "min_order_qty": _first(raw, "min_order_qty", "moq"),
            "lead_days": _first(raw, "lead_days", "delivery_days"),
            "valid_until": _first(raw, "valid_until", "expires_at"), "missing_fields": missing}
