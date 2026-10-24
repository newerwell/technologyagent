"""Generate small nonsensitive P06 artifacts from the committed synthetic fixture."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
from pathlib import Path
from html.parser import HTMLParser

from PIL import Image

from backend.app.contracts.common import RequestContext
from backend.app.sandbox.charts import build_chart_spec, render_chart_in_sandbox
from backend.app.sandbox.reports import AnalysisResult, build_report_spec
from backend.app.sandbox.runner import DockerSandbox
from backend.app.services.seeding import load_bundle

OUTPUT = Path(__file__).resolve().parents[1] / "evidence" / "p06-artifacts"


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


async def main() -> None:
    bundle = load_bundle()
    parts = {part.id: part for part in bundle.parts}
    suppliers = {supplier.id: supplier for supplier in bundle.suppliers}
    quotes = {quote.id: quote for quote in bundle.quotes}
    chosen = [quotes[quote_id] for quote_id in ("Q01", "Q02")]
    if any(quote.part_id != "P001" or quote.valid_until.isoformat() < "2026-10-23T02:00:00+00:00" for quote in chosen):
        raise RuntimeError("fixed valid quote inputs changed")
    labels = [suppliers[item.supplier_id].name for item in chosen]
    amounts = [item.unit_price_cents * 55 for item in chosen]
    if amounts != [66000, 60500] or "Q03" in {item.id for item in chosen}:
        raise RuntimeError("fixed 55-unit quote check failed")
    refs = [{"entity": "quote", "id": item.id, "data_source": "local_seed"} for item in chosen]

    bar = build_chart_spec("bar", {"title": "P001 刹车片 · 55件有效报价", "labels": labels,
                                    "series": [{"name": "总额（元）", "values_cents": amounts}]}, refs)
    line = build_chart_spec("line", {"title": "合成三日历史订单趋势", "labels": ["2026-10-22", "2026-10-23", "2026-10-24"],
                                      "series": [{"name": "订单数量（单）", "values": [2, 5, 3]}]},
                            [{"entity": "historical_orders", "id": "synthetic-three-days", "data_source": "local_seed"}])
    category_totals: dict[str, int] = {}
    for inventory in bundle.inventories:
        part = parts[inventory.part_id]
        category_totals[part.category] = category_totals.get(part.category, 0) + inventory.on_hand
    pie = build_chart_spec("pie", {"title": "合成库存按品类分布", "labels": list(category_totals),
                                    "series": [{"name": "在手数量（件）", "values": list(category_totals.values())}]},
                           [{"entity": "inventory", "id": item.id, "data_source": "local_seed"} for item in bundle.inventories])
    ctx = RequestContext(owner_id="evidence", request_id="p06-examples", run_id="run_p06_examples")
    sandbox = DockerSandbox()
    available, reason = await sandbox.available()
    if not available:
        raise RuntimeError(f"required Docker sandbox is unavailable: {reason}")
    charts = {
        "bar-valid-quotes.png": await render_chart_in_sandbox(bar, sandbox, ctx),
        "line-three-days.png": await render_chart_in_sandbox(line, sandbox, ctx),
        "pie-inventory-categories.png": await render_chart_in_sandbox(pie, sandbox, ctx),
    }
    analysis = AnalysisResult(
        title="P001 刹车片供应商报价比较", scope="local_seed / P001 / W01 / 55件有效报价",
        as_of="2026-10-23T02:00:00Z", source_refs=refs,
        columns=["供应商", "数量（件）", "总额（分）"],
        rows=[[labels[0], 55, amounts[0]], [labels[1], 55, amounts[1]]],
        summary="S02 总额60500分（605.00元）；S01总额66000分（660.00元）。仅包含有效报价Q01/Q02。",
        recommendations=["按价格优先选择S02；若要求7天内到货则选择S01。"],
        missing_fields=[], numeric_columns=[1, 2],
    )
    reports = {
        "quote-comparison.md": build_report_spec("md", analysis).content,
        "quote-comparison.html": build_report_spec("html", analysis).content,
        "quote-comparison.csv": build_report_spec("csv", analysis).content,
        "quote-comparison.json": build_report_spec("json", analysis).content,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for filename, content in {**charts, **reports}.items():
        (OUTPUT / filename).write_bytes(content)
    _validate_generated_files()
    print(f"wrote {len(charts)} Docker-rendered charts and {len(reports)} same-analysis reports under {OUTPUT}")


def _validate_generated_files() -> None:
    scope = "local_seed / P001 / W01 / 55件有效报价"
    money = {66000, 60500}
    pngs = [Image.open(io.BytesIO((OUTPUT / name).read_bytes())) for name in (
        "bar-valid-quotes.png", "line-three-days.png", "pie-inventory-categories.png")]
    assert all(image.format == "PNG" and image.width >= 600 and image.height >= 350 for image in pngs)
    assert len({hashlib.sha256((OUTPUT / name).read_bytes()).digest() for name in (
        "bar-valid-quotes.png", "line-three-days.png", "pie-inventory-categories.png")}) == 3

    markdown = (OUTPUT / "quote-comparison.md").read_text(encoding="utf-8")
    assert scope in markdown and "66000" in markdown and "60500" in markdown and "Q01/Q02" in markdown
    html_text = (OUTPUT / "quote-comparison.html").read_text(encoding="utf-8")
    parser = _TextOnly()
    parser.feed(html_text)
    visible_html = "".join(parser.parts)
    assert scope in visible_html and "66000" in visible_html and "60500" in visible_html
    assert "<script>" not in html_text

    rows = list(csv.reader(io.StringIO((OUTPUT / "quote-comparison.csv").read_text(encoding="utf-8-sig"))))
    assert rows[0] == ["供应商", "数量（件）", "总额（分）"]
    assert {int(row[2]) for row in rows[1:3]} == money
    assert ["范围", scope] in rows

    data = json.loads((OUTPUT / "quote-comparison.json").read_text(encoding="utf-8"))
    assert data["scope"] == scope and {row[2] for row in data["rows"]} == money
    assert {source["id"] for source in data["source_refs"]} == {"Q01", "Q02"}


if __name__ == "__main__":
    asyncio.run(main())
