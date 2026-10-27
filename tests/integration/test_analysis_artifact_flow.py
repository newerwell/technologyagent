import csv
import io
import json
from datetime import datetime, timezone

import pytest

from backend.app.agent.budget import RunBudget
from backend.app.agent.tools.analysis import AnalysisToolRegistry
from backend.app.contracts.common import RequestContext, SystemClock
from backend.app.ports.tools import ToolResult, ToolSpec
from backend.app.services.artifacts import ArtifactService


class PreviewRegistry:
    def available(self, _ctx):
        return [ToolSpec(name="replenishment_preview", description="preview", input_schema={})]

    async def invoke(self, name, arguments, ctx, budget):
        if name != "replenishment_preview":
            return ToolResult(ok=False, error={"code": "UNKNOWN_TOOL", "message": name})
        return ToolResult(ok=True, call_id="call-preview-1", meta={
            "data_source": "local_seed", "scope": "warehouse:" + arguments["warehouse_id"],
            "as_of": "2026-10-24T10:00:00+00:00",
        }, data={
            "lines": [{
                "part_id": "P001", "part_name": "刹车片", "warehouse_id": "W01", "unit": "套",
                "shortage": 55, "quantity": 55, "actionable": True,
                "recommended_quote_id": "Q02", "total_cents": 60500,
                "candidate_quotes": [
                    {"quote_id": "Q01", "supplier_id": "S01", "supplier_name": "甲供应商",
                     "unit_price_cents": 1200, "suggested_quantity": 55,
                     "line_total_cents": 66000, "lead_days": 5,
                     "valid_until": "2026-11-01T00:00:00+00:00"},
                    {"quote_id": "Q02", "supplier_id": "S02", "supplier_name": "乙供应商",
                     "unit_price_cents": 1100, "suggested_quantity": 55,
                     "line_total_cents": 60500, "lead_days": 7,
                     "valid_until": "2026-11-01T00:00:00+00:00"},
                ],
            }],
            "source_refs": [
                {"call_id": "call-preview-1", "entity": "inventory", "id": "I001",
                 "data_source": "local_seed", "as_of": "2026-10-24T10:00:00+00:00"},
                {"call_id": "call-preview-1", "entity": "quote", "id": "Q01",
                 "data_source": "local_seed", "as_of": "2026-10-24T10:00:00+00:00"},
                {"call_id": "call-preview-1", "entity": "quote", "id": "Q02",
                 "data_source": "local_seed", "as_of": "2026-10-24T10:00:00+00:00"},
            ],
        })


class PagedInventoryRegistry:
    def available(self, _ctx):
        return [ToolSpec(name="inventory_page", description="inventory", input_schema={})]

    async def invoke(self, name, arguments, ctx, budget):
        assert name == "inventory_page"
        page = arguments["page"]
        row = {1: {"id": "I001", "part_id": "P001", "warehouse_id": "W01", "unit": "套",
                   "on_hand": 10, "available": 8, "inbound": 0, "shortage": 55, "warning": True},
               2: {"id": "I002", "part_id": "P002", "warehouse_id": "W01", "unit": "个",
                   "on_hand": 20, "available": 18, "inbound": 0, "shortage": 12, "warning": True}}[page]
        return ToolResult(ok=True, call_id=f"call-page-{page}", meta={
            "data_source": "local_seed", "scope": "warehouse:W01",
            "as_of": "2026-10-24T10:00:00+00:00",
        }, data={"records": [row], "total": 2, "page": page, "page_size": 1, "pages": 2,
                "source_refs": [{"call_id": f"call-page-{page}", "entity": "inventory", "id": row["id"],
                                 "data_source": "local_seed", "as_of": "2026-10-24T10:00:00+00:00"}]})


class MemoryArtifactRepository:
    def __init__(self):
        self.rows = {}

    async def insert(self, document):
        self.rows[document["_id"]] = document

    async def get(self, artifact_id, owner_id):
        row = self.rows.get(artifact_id)
        return row if row and row["owner_id"] == owner_id else None


class EventRecorder:
    def __init__(self):
        self.events = []

    async def append_event(self, run_id, kind, payload, ctx):
        self.events.append((run_id, kind, payload))


@pytest.mark.asyncio
async def test_report_tool_derives_money_scope_and_sources_from_authorized_preview(tmp_path):
    repository = MemoryArtifactRepository()
    artifacts = ArtifactService(repository, tmp_path, SystemClock())
    events = EventRecorder()
    registry = AnalysisToolRegistry(PreviewRegistry(), object(), artifacts, events, sandbox_enabled=False)
    ctx = RequestContext(owner_id="owner", request_id="req", run_id="run")
    budget = RunBudget(ctx.run_id)

    preview = await registry.invoke("replenishment_preview", {"part_ids": ["P001"], "warehouse_id": "W01"}, ctx, budget)
    report = await registry.invoke("artifact_report", {"dataset_id": preview.meta["dataset_id"], "format": "csv"}, ctx, budget)

    assert report.ok, report.error
    artifact_id = report.data["artifact_id"]
    artifact, content = await artifacts.open(artifact_id, ctx)
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    assert artifact.status == "ready"
    assert [row[-1] for row in rows if len(row) == 8 and row[0] == "P001"] == ["66000", "60500"]
    assert [row for row in rows if row and row[0] == "范围"] == [["范围", "仓库 W01；物料 P001"]]
    assert b"Q01" in content and b"Q02" in content and b"call-preview-1" in content
    assert len(events.events) == 1 and events.events[0][1] == "artifact_ready"


@pytest.mark.asyncio
async def test_report_tool_does_not_accept_model_supplied_rows_or_values(tmp_path):
    registry = AnalysisToolRegistry(PreviewRegistry(), object(), ArtifactService(MemoryArtifactRepository(), tmp_path, SystemClock()), EventRecorder(), sandbox_enabled=False)
    ctx = RequestContext(owner_id="owner", request_id="req", run_id="run")
    preview = await registry.invoke("replenishment_preview", {"part_ids": ["P001"], "warehouse_id": "W01"}, ctx, RunBudget(ctx.run_id))

    result = await registry.invoke("artifact_report", {
        "dataset_id": preview.meta["dataset_id"], "format": "csv",
        "rows": [["P001", "W01", "S01", 55, 9999]],
    }, ctx, RunBudget(ctx.run_id))

    assert not result.ok
    assert result.error["code"] == "INVALID_ARGUMENTS"


@pytest.mark.asyncio
async def test_formal_report_combines_complete_inventory_pages_and_reads_back_full_body(tmp_path):
    artifacts = ArtifactService(MemoryArtifactRepository(), tmp_path, SystemClock())
    registry = AnalysisToolRegistry(PagedInventoryRegistry(), object(), artifacts, EventRecorder(), sandbox_enabled=False)
    ctx = RequestContext(owner_id="owner", request_id="req", run_id="run")
    budget = RunBudget(ctx.run_id)
    args = {"warehouse_id": "W01", "page_size": 1}

    for page in (1, 2):
        result = await registry.invoke("inventory_page", {**args, "page": page}, ctx, budget)
        assert result.ok

    dataset_id = registry.latest_report_dataset_id(ctx, "分析W01全部库存并生成报告")
    assert dataset_id is not None
    report = await registry.invoke("artifact_report", {"dataset_id": dataset_id, "format": "md"}, ctx, budget)

    assert report.ok, report.error
    artifact, body = await artifacts.open(report.data["artifact_id"], ctx)
    text = body.decode("utf-8")
    assert artifact.kind == "md"
    assert "warehouse:W01" in text
    assert "P001" in text and "P002" in text
    assert "I001" in text and "I002" in text
    assert text.count("call-page-1") >= 1 and text.count("call-page-2") >= 1
    assert "查询范围内返回 2 条库存记录" in text
    verified = await registry.verify_report_artifact(report.data["artifact_id"], dataset_id, "md", ctx)
    assert verified is not None
    assert verified["source_refs"] == artifact.source_refs
    assert len(verified["content_sha256"]) == 64
    (tmp_path / artifact.storage_key).write_bytes(body.replace(b"P002", b"P999"))
    assert await registry.verify_report_artifact(report.data["artifact_id"], dataset_id, "md", ctx) is None


@pytest.mark.asyncio
async def test_formal_report_refuses_incomplete_inventory_page_set(tmp_path):
    artifacts = ArtifactService(MemoryArtifactRepository(), tmp_path, SystemClock())
    registry = AnalysisToolRegistry(PagedInventoryRegistry(), object(), artifacts, EventRecorder(), sandbox_enabled=False)
    ctx = RequestContext(owner_id="owner", request_id="req", run_id="run")
    result = await registry.invoke("inventory_page", {"warehouse_id": "W01", "page": 1, "page_size": 1}, ctx, RunBudget(ctx.run_id))

    assert result.ok
    assert registry.latest_report_dataset_id(ctx) is None


@pytest.mark.parametrize("exception_name", ["RunCancelled", "RunDeadlineExceeded", "RunLimitExceeded"])
@pytest.mark.asyncio
async def test_report_registry_propagates_run_control_exceptions(tmp_path, monkeypatch, exception_name):
    from backend.app.agent import budget as budget_module

    artifacts = ArtifactService(MemoryArtifactRepository(), tmp_path, SystemClock())
    registry = AnalysisToolRegistry(PreviewRegistry(), object(), artifacts, EventRecorder(), sandbox_enabled=False)
    ctx = RequestContext(owner_id="owner", request_id="req", run_id="run")
    budget = RunBudget(ctx.run_id)
    preview = await registry.invoke("replenishment_preview", {"part_ids": ["P001"], "warehouse_id": "W01"}, ctx, budget)
    exception_type = getattr(budget_module, exception_name)

    async def abort(*_args, **_kwargs):
        raise exception_type(exception_name)

    monkeypatch.setattr(registry._artifact_generator, "generate_report", abort)
    with pytest.raises(exception_type):
        await registry.invoke("artifact_report", {"dataset_id": preview.meta["dataset_id"], "format": "md"}, ctx, budget)
