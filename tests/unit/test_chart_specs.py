from datetime import datetime, timezone

import pytest

from backend.app.sandbox.charts import build_chart_spec


def test_bar_spec_keeps_integer_cents_and_filters_only_by_explicit_rows():
    spec = build_chart_spec("bar", {
        "title": "供应商报价比较",
        "labels": ["供应商 S01", "供应商 S02"],
        "series": [{"name": "55 件总额", "values_cents": [66000, 60500]}],
    }, [{"entity": "quote", "id": "Q01"}, {"entity": "quote", "id": "Q02"}])
    assert spec.labels == ["供应商 S01", "供应商 S02"]
    assert spec.series[0].values_cents == [66000, 60500]
    assert "Q03" not in str(spec.model_dump())


def test_line_rejects_unordered_or_single_time_point():
    with pytest.raises(ValueError, match="time"):
        build_chart_spec("line", {"title": "三日趋势", "labels": ["2026-10-02"], "series": [{"name": "订单", "values": [2]}]}, [])
    with pytest.raises(ValueError, match="ordered"):
        build_chart_spec("line", {"title": "三日趋势", "labels": ["2026-10-03", "2026-10-01"], "series": [{"name": "订单", "values": [3, 1]}]}, [])


def test_pie_rejects_negative_and_zero_and_unknown_kind():
    with pytest.raises(ValueError):
        build_chart_spec("pie", {"title": "库存分类", "labels": ["A", "B"], "series": [{"name": "库存", "values": [1, -1]}]}, [])
    with pytest.raises(ValueError):
        build_chart_spec("pie", {"title": "库存分类", "labels": ["A", "B"], "series": [{"name": "库存", "values": [0, 0]}]}, [])
    with pytest.raises(ValueError, match="unsupported"):
        build_chart_spec("scatter", {}, [])


@pytest.mark.parametrize("values", [[True, 1], [float("nan"), 1], [float("inf"), 1], [-1, 2]])
def test_bar_rejects_non_numeric_non_finite_or_negative_money(values):
    with pytest.raises(ValueError):
        build_chart_spec("bar", {"labels": ["S01", "S02"],
                                  "series": [{"name": "总额", "values": values}]}, [])


def test_bar_rejects_boolean_or_mismatched_integer_cents():
    for values in ([True, 60500], [66000]):
        with pytest.raises(ValueError, match="integer cents"):
            build_chart_spec("bar", {"labels": ["S01", "S02"],
                                      "series": [{"name": "总额", "values_cents": values}]}, [])
