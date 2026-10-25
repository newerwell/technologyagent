"""从单一结构化分析事实生成可解析的固定格式报告。"""
from __future__ import annotations

import csv
import html
import io
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.contracts.artifacts import ReportSpec


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    scope: str
    as_of: str
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str]
    rows: list[list[Any]]
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    numeric_columns: list[int] = Field(default_factory=list)


def _csv_safe(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _validate(analysis: AnalysisResult) -> None:
    if len(analysis.numeric_columns) != len(set(analysis.numeric_columns)):
        raise ValueError("numeric columns must be unique")
    if any(type(index) is not int or index < 0 or index >= len(analysis.columns)
           for index in analysis.numeric_columns):
        raise ValueError("numeric column index is invalid")
    for row in analysis.rows:
        if len(row) != len(analysis.columns):
            raise ValueError("report row length must match columns")
        for index in analysis.numeric_columns:
            value = row[index]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("numeric column values must be finite numbers")


def build_report_spec(format: Literal["md", "html", "csv", "json"] | str, analysis: AnalysisResult) -> ReportSpec:
    if format not in {"md", "html", "csv", "json"}:
        raise ValueError(f"unsupported report format: {format}")
    _validate(analysis)
    data = analysis.model_dump(mode="json")
    source_refs = [dict(ref) for ref in analysis.source_refs]
    if format == "json":
        content, mime = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"
    elif format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow([_csv_safe(column) for column in analysis.columns])
        for row in analysis.rows:
            writer.writerow([value if index in analysis.numeric_columns else _csv_safe(value)
                             for index, value in enumerate(row)])
        writer.writerow([])
        writer.writerow(["范围", _csv_safe(analysis.scope)])
        writer.writerow(["来源时间", _csv_safe(analysis.as_of)])
        writer.writerow(["结论", _csv_safe(analysis.summary)])
        writer.writerow(["建议", _csv_safe("；".join(analysis.recommendations))])
        writer.writerow(["缺失项", _csv_safe("；".join(analysis.missing_fields))])
        writer.writerow([])
        writer.writerow(["来源引用", "实体", "记录ID", "工具调用", "数据源", "来源时间"])
        for ref in source_refs:
            writer.writerow(["来源", *[_csv_safe(ref.get(key, "")) for key in
                                         ("entity", "id", "call_id", "data_source", "as_of")]])
        content, mime = ("\ufeff" + stream.getvalue()).encode("utf-8"), "text/csv"
    elif format == "md":
        lines = [f"# {analysis.title}", "", f"- 数据范围：{analysis.scope}", f"- 来源时间：{analysis.as_of}",
                 "", "## 明细", "", "| " + " | ".join(analysis.columns) + " |",
                 "| " + " | ".join("---" for _ in analysis.columns) + " |"]
        lines += ["| " + " | ".join(str(value).replace("|", "\\|").replace("\n", " ") for value in row) + " |" for row in analysis.rows]
        lines += ["", "## 结论", "", analysis.summary, "", "## 建议", ""]
        lines += [f"- {item}" for item in analysis.recommendations] or ["- 无"]
        lines += ["", "## 缺失项", ""]
        lines += [f"- {item}" for item in analysis.missing_fields] or ["- 无"]
        lines += ["", "## 来源引用", ""]
        lines += [f"- {ref.get('call_id', '未知调用')} · {ref.get('entity', '未知实体')}:{ref.get('id', '未知记录')} · {ref.get('data_source', '未知来源')} · {ref.get('as_of', '未知时间')}"
                  for ref in source_refs] or ["- 无来源引用"]
        content, mime = "\n".join(lines).encode("utf-8"), "text/markdown"
    else:
        esc = lambda value: html.escape(str(value), quote=True)
        header = "".join(f"<th>{esc(c)}</th>" for c in analysis.columns)
        rows = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>" for row in analysis.rows)
        bullets = "".join(f"<li>{esc(x)}</li>" for x in analysis.recommendations) or "<li>无</li>"
        missing = "".join(f"<li>{esc(x)}</li>" for x in analysis.missing_fields) or "<li>无</li>"
        refs = "".join(f"<li>{esc(ref.get('call_id', '未知调用'))} · {esc(ref.get('entity', '未知实体'))}:{esc(ref.get('id', '未知记录'))} · {esc(ref.get('data_source', '未知来源'))} · {esc(ref.get('as_of', '未知时间'))}</li>"
                       for ref in source_refs) or "<li>无来源引用</li>"
        doc = ("<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><title>" + esc(analysis.title) +
               "</title><h1>" + esc(analysis.title) + "</h1><p>数据范围：" + esc(analysis.scope) +
               "</p><p>来源时间：" + esc(analysis.as_of) + "</p><table><thead><tr>" + header +
               "</tr></thead><tbody>" + rows + "</tbody></table><h2>结论</h2><p>" + esc(analysis.summary) +
               "</p><h2>建议</h2><ul>" + bullets + "</ul><h2>缺失项</h2><ul>" + missing +
               "</ul><h2>来源引用</h2><ul>" + refs + "</ul></html>")
        content, mime = doc.encode("utf-8"), "text/html"
    return ReportSpec(format=format, content=content, mime=mime)
