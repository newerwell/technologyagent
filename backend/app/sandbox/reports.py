"""从单一结构化分析事实生成可解析的固定格式报告。"""
from __future__ import annotations

import csv
import html
import io
import json
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


def build_report_spec(format: Literal["md", "html", "csv", "json"] | str, analysis: AnalysisResult) -> ReportSpec:
    if format not in {"md", "html", "csv", "json"}:
        raise ValueError(f"unsupported report format: {format}")
    data = analysis.model_dump(mode="json")
    if any(len(row) != len(analysis.columns) for row in analysis.rows):
        raise ValueError("report row length must match columns")
    if format == "json":
        content, mime = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"
    elif format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow([*analysis.columns, *([""] * max(0, 0))])
        for row in analysis.rows:
            safe = []
            for index, value in enumerate(row):
                if index not in analysis.numeric_columns and isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                safe.append(value)
            writer.writerow(safe)
        writer.writerow([])
        writer.writerow(["范围", analysis.scope])
        writer.writerow(["来源时间", analysis.as_of])
        writer.writerow(["结论", analysis.summary])
        writer.writerow(["建议", "；".join(analysis.recommendations)])
        writer.writerow(["缺失项", "；".join(analysis.missing_fields)])
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
        content, mime = "\n".join(lines).encode("utf-8"), "text/markdown"
    else:
        esc = lambda value: html.escape(str(value), quote=True)
        header = "".join(f"<th>{esc(c)}</th>" for c in analysis.columns)
        rows = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>" for row in analysis.rows)
        bullets = "".join(f"<li>{esc(x)}</li>" for x in analysis.recommendations) or "<li>无</li>"
        missing = "".join(f"<li>{esc(x)}</li>" for x in analysis.missing_fields) or "<li>无</li>"
        doc = ("<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><title>" + esc(analysis.title) +
               "</title><h1>" + esc(analysis.title) + "</h1><p>数据范围：" + esc(analysis.scope) +
               "</p><p>来源时间：" + esc(analysis.as_of) + "</p><table><thead><tr>" + header +
               "</tr></thead><tbody>" + rows + "</tbody></table><h2>结论</h2><p>" + esc(analysis.summary) +
               "</p><h2>建议</h2><ul>" + bullets + "</ul><h2>缺失项</h2><ul>" + missing + "</ul></html>")
        content, mime = doc.encode("utf-8"), "text/html"
    return ReportSpec(format=format, content=content, mime=mime)
