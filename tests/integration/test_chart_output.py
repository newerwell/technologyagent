import io
import hashlib
import os

import pytest
from PIL import Image

from backend.app.contracts.common import RequestContext
from backend.app.sandbox.charts import build_chart_spec, render_chart_in_sandbox
from backend.app.sandbox.runner import DockerSandbox


@pytest.mark.asyncio
async def test_bar_line_and_pie_are_distinct_real_sandbox_pngs():
    sandbox = DockerSandbox()
    available, reason = await sandbox.available()
    if not available:
        if os.getenv("P06_REQUIRED") == "1":
            pytest.fail(f"P06 requires the real Docker sandbox: {reason}")
        pytest.skip(f"sandbox image unavailable: {reason}")
    ctx = RequestContext(owner_id="test", request_id="charts", run_id="run_charts")
    specs = [
        build_chart_spec("bar", {"title": "P001 刹车片 55件有效报价", "labels": ["S01 660元", "S02 605元"],
                                 "series": [{"name": "总额（分）", "values_cents": [66000, 60500]}]},
                         [{"entity": "quote", "id": "Q01"}, {"entity": "quote", "id": "Q02"}]),
        build_chart_spec("line", {"title": "合成三日订单数量", "labels": ["2026-10-22", "2026-10-23", "2026-10-24"],
                                   "series": [{"name": "订单数", "values": [2, 5, 3]}]}, []),
        build_chart_spec("pie", {"title": "库存按品类分布", "labels": ["制动", "滤清", "传动"],
                                  "series": [{"name": "在手件数", "values": [20, 15, 8]}]},
                         [{"entity": "inventory", "id": "seed-v1"}]),
    ]
    images = [await render_chart_in_sandbox(spec, sandbox, ctx) for spec in specs]
    assert len({hashlib.sha256(image).digest() for image in images}) == 3
    for image in images:
        decoded = Image.open(io.BytesIO(image))
        assert decoded.format == "PNG" and decoded.width >= 600 and decoded.height >= 350
