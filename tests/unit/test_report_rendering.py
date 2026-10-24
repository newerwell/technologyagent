import csv
import io
import json

from backend.app.sandbox.reports import AnalysisResult, build_report_spec


def sample():
    return AnalysisResult.model_validate({
        "title": "供应商比较 <script>", "scope": "零件 P001 / 仓库 W01 / 数量 55 件",
        "as_of": "2026-10-24T00:00:00Z", "source_refs": [{"entity": "quote", "id": "Q01"}],
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
