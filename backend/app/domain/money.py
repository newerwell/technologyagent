"""金额规则：整数分，禁止浮点与布尔混入。"""

from __future__ import annotations

from typing import Any


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def line_total(quantity: int, unit_price_cents: int) -> int:
    """行金额（分）= 数量 × 单价（分）。"""
    qty = _require_non_negative_int(quantity, "quantity")
    price = _require_non_negative_int(unit_price_cents, "unit_price_cents")
    if price == 0:
        raise ValueError("unit_price_cents must be > 0")
    return qty * price


def fen_to_yuan_text(cents: int) -> str:
    """仅用于后端测试/证据；前端使用自己的 formatMoney。"""
    value = _require_non_negative_int(cents, "cents")
    return f"{value // 100}.{value % 100:02d}"
