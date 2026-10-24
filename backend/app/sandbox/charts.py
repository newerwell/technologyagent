"""图表输入的确定性验证和 PNG 渲染。"""
from __future__ import annotations

from datetime import date
from io import BytesIO
import json
import math
from typing import Any

from backend.app.contracts.artifacts import ChartSeries, ChartSpec, CollectedOutput, SandboxInput, SandboxJob
from backend.app.contracts.common import RequestContext
from backend.app.ports.sandbox import SandboxPort


def build_chart_spec(kind: str, data: dict[str, Any], source_refs: list[dict[str, str]]) -> ChartSpec:
    if kind not in {"bar", "line", "pie"}:
        raise ValueError(f"unsupported chart kind: {kind}")
    labels = data.get("labels")
    series = data.get("series")
    if not isinstance(labels, list) or not labels or not isinstance(series, list) or not series:
        raise ValueError("chart data must contain labels and series")
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("chart labels must be non-empty strings")
    parsed: list[ChartSeries] = []
    for item in series:
        if not isinstance(item, dict):
            raise ValueError("chart series entries must be objects")
        values = item.get("values")
        cents = item.get("values_cents")
        if kind == "bar" and cents is not None:
            if (not isinstance(cents, list) or len(cents) != len(labels)
                    or any(type(value) is not int for value in cents)):
                raise ValueError("money values must be integer cents")
            values = [value / 100 for value in cents]
        if not isinstance(values, list) or len(values) != len(labels):
            raise ValueError("series values must match labels")
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in values):
            raise ValueError("chart values must be finite numbers")
        if kind == "bar" and any(value < 0 for value in values):
            raise ValueError("bar chart money values cannot be negative")
        parsed.append(ChartSeries(name=item.get("name", "数据"), values=values, values_cents=cents))
    if kind == "line":
        try:
            points = [date.fromisoformat(label[:10]) for label in labels]
        except ValueError as exc:
            raise ValueError("line chart requires actual ISO time labels") from exc
        if len(points) < 2:
            raise ValueError("line chart requires at least two time points")
        if points != sorted(points) or len(set(points)) != len(points):
            raise ValueError("line time points must be ordered and unique")
    if kind == "pie":
        if len(parsed) != 1 or any(value < 0 for value in parsed[0].values):
            raise ValueError("pie requires one non-negative series")
        if sum(parsed[0].values) <= 0:
            raise ValueError("pie chart cannot represent all-zero data")
    return ChartSpec(kind=kind, labels=labels, series=parsed,
                     title=str(data.get("title") or "采购分析"), source_refs=source_refs)


def render_chart(spec: ChartSpec) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.sans-serif": ["Noto Sans CJK JP", "DejaVu Sans"], "axes.unicode_minus": False,
                         "font.size": 11, "figure.dpi": 120})
    fig, ax = plt.subplots(figsize=(9, 5.2), constrained_layout=True)
    if spec.kind == "bar":
        width = 0.8 / len(spec.series)
        positions = list(range(len(spec.labels)))
        for index, series in enumerate(spec.series):
            offset = (index - (len(spec.series) - 1) / 2) * width
            bars = ax.bar([p + offset for p in positions], series.values, width, label=series.name)
            for bar, value in zip(bars, series.values, strict=True):
                ax.annotate(f"¥{value:,.2f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            xytext=(0, 4), textcoords="offset points", ha="center", fontsize=9)
        ax.set_xticks(positions, spec.labels)
        ax.set_ylabel("金额（元）")
        if len(spec.series) > 1:
            ax.legend()
    elif spec.kind == "line":
        for series in spec.series:
            ax.plot(spec.labels, series.values, marker="o", label=series.name)
        ax.set_xlabel("日期")
        ax.legend()
        ax.tick_params(axis="x", rotation=15)
    else:
        ax.pie(spec.series[0].values, labels=spec.labels, autopct="%1.1f%%", startangle=90)
        ax.axis("equal")
    ax.set_title(spec.title)
    if spec.kind != "pie":
        ax.grid(axis="y", alpha=0.22)
    image = BytesIO()
    fig.savefig(image, format="png", bbox_inches="tight")
    plt.close(fig)
    return image.getvalue()


def chart_sandbox_job(spec: ChartSpec) -> SandboxJob:
    """Build a fixed renderer job; only JSON data crosses the sandbox boundary."""
    code = r'''import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
data = json.load(open("/work/data/chart.json", encoding="utf-8"))
plt.rcParams.update({"font.sans-serif": ["Noto Sans CJK JP", "DejaVu Sans"], "axes.unicode_minus": False, "font.size": 11})
fig, ax = plt.subplots(figsize=(9, 5.2), constrained_layout=True)
kind, labels, series = data["kind"], data["labels"], data["series"]
if kind == "bar":
    width = .8 / len(series)
    x = list(range(len(labels)))
    for i, item in enumerate(series):
        values = item.get("values_cents") or item["values"]
        values = [v / 100 for v in values] if item.get("values_cents") else values
        bars = ax.bar([p + (i-(len(series)-1)/2)*width for p in x], values, width, label=item["name"])
        for bar, value in zip(bars, values): ax.annotate(f"¥{value:,.2f}", (bar.get_x()+bar.get_width()/2, bar.get_height()), xytext=(0,4), textcoords="offset points", ha="center", fontsize=9)
    ax.set_xticks(x, labels); ax.set_ylabel("金额（元）")
    if len(series) > 1: ax.legend()
elif kind == "line":
    for item in series: ax.plot(labels, item["values"], marker="o", label=item["name"])
    ax.set_xlabel("日期"); ax.legend(); ax.tick_params(axis="x", rotation=15)
else:
    ax.pie(series[0]["values"], labels=labels, autopct="%1.1f%%", startangle=90); ax.axis("equal")
ax.set_title(data["title"])
if kind != "pie": ax.grid(axis="y", alpha=.22)
fig.savefig("/out/chart.png", format="png", bbox_inches="tight"); plt.close(fig)
'''
    payload = json.dumps(spec.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
    return SandboxJob(code=code, input_files=[SandboxInput(filename="chart.json", content=payload)],
                      timeout_seconds=30, output_allowlist=["chart.png"])


async def render_chart_in_sandbox(spec: ChartSpec, sandbox: SandboxPort, ctx: RequestContext) -> bytes:
    result = await sandbox.execute(chart_sandbox_job(spec), ctx)
    if result.timed_out or result.exit_code != 0 or not result.outputs:
        raise RuntimeError(result.diagnostics or "chart sandbox execution failed")
    output = result.outputs[0]
    if output.mime != "image/png" or not output.content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("sandbox chart output is not a valid PNG")
    return output.content
