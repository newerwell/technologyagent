import csv
import io
import json

from backend.app.sandbox.reports import AnalysisResult, build_report_spec


def sample():
    return AnalysisResult.model_validate({
        "title": "供应商比较 <script>", "scope": "零件 P001 / 仓库 W01 / 数量 55 件",
        "as_of": "2026-10-24T00:00:00Z", "source_refs": [{"entity": "quote", "id": "Q01", "call_id": "call-preview-1"}],
        "columns": ["供应商", "数量(件)", "总额(分)"],
        "rows": [["S01, 一号", 55, 66000], ["=HYPERLINK(\"x\")", 55, 60500]],
        "summary": "共 1215 元", "recommendations": ["选价格优先"], "missing_fields": [],
        "numeric_columns": [2],
    })


def test_all_formats_preserve_scope_rows_and_integer_cents():
    result = sample()
    rendered = {fmt: build_report_spec(fmt, result).content for fmt in ("md", "html", "csv", "json")}
    data = json.loads(rendered["json"])
    assert data["rows"][0][2] == 66000
    assert data["scope"] in rendered["md"].decode("utf-8") and data["scope"] in rendered["html"].decode("utf-8")
    csv_rows = list(csv.reader(io.StringIO(rendered["csv"].decode("utf-8-sig"))))
    assert csv_rows[2][0].startswith("'") and csv_rows[0][2] == "总额(分)"
    assert "<script>" not in rendered["html"].decode("utf-8")
    assert "&lt;script&gt;" in rendered["html"].decode("utf-8")


def test_all_formats_preserve_source_reference_identity():
    result = sample()
    rendered = {fmt: build_report_spec(fmt, result).content.decode("utf-8-sig")
                for fmt in ("md", "html", "csv", "json")}

    for text in rendered.values():
        assert "Q01" in text
        assert "quote" in text
    assert "call-preview-1" in rendered["csv"]


def test_csv_formula_protection_covers_header_and_every_metadata_cell():
    result = AnalysisResult.model_validate({
        "title": "=title", "scope": " +scope", "as_of": "\t@date",
        "source_refs": [{"entity": "=entity", "id": "-source", "call_id": "@call"}],
        "columns": ["=header", "金额(分)"], "rows": [["\t+name", 66000]],
        "summary": " =summary", "recommendations": ["-recommendation"],
        "missing_fields": ["@missing"], "numeric_columns": [1],
    })

    csv_rows = list(csv.reader(io.StringIO(build_report_spec("csv", result).content.decode("utf-8-sig"))))

    assert csv_rows[0][0] == "'=header"
    assert csv_rows[1][0] == "'\t+name"
    assert [row[1] for row in csv_rows if row and row[0] == "范围"] == ["' +scope"]
    assert [row[1] for row in csv_rows if row and row[0] == "来源时间"] == ["'\t@date"]
    assert [row[1] for row in csv_rows if row and row[0] == "结论"] == ["' =summary"]
    assert [row[1] for row in csv_rows if row and row[0] == "建议"] == ["'-recommendation"]
    assert [row[1] for row in csv_rows if row and row[0] == "缺失项"] == ["'@missing"]
    assert any(row and row[0] == "来源" and row[1] == "'=entity" for row in csv_rows)
    assert csv_rows[1][1] == "66000"


def test_numeric_columns_reject_strings_and_bool_values():
    result = AnalysisResult.model_validate({
        "title": "t", "scope": "s", "as_of": "now", "columns": ["amount"],
        "rows": [["9999"]], "summary": "s", "numeric_columns": [0],
    })

    import pytest
    with pytest.raises(ValueError, match="numeric"):
        build_report_spec("csv", result)
