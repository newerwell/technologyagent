"""P01 金额规则：整数分，拒绝布尔/负数/非整数。"""

from __future__ import annotations

import pytest

from backend.app.domain.money import line_total


def test_line_total_uses_integer_cents():
    assert line_total(55, 1200) == 66000
    assert line_total(0, 1200) == 0


@pytest.mark.parametrize("quantity", [True, False, -1, 1.5, "1", None])
def test_line_total_rejects_invalid_quantity(quantity):
    with pytest.raises(ValueError):
        line_total(quantity, 1200)


@pytest.mark.parametrize("price", [True, False, -1, 1.5, "1200", None, 0])
def test_line_total_rejects_invalid_price(price):
    with pytest.raises(ValueError):
        line_total(1, price)
