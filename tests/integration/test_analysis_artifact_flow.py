import csv
import io
from datetime import UTC, datetime

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
            "as_of": f"2026-10-24T10:00:0{page}+00:00", "snapshot_id": "stable-inventory-snapshot",
        }, data={"records": [row], "total": 2, "page": page, "page_size": 1, "pages": 2,
                "source_refs": [{"call_id": f"call-page-{page}", "entity": "inventory", "id": row["id"],
                                 "data_source": "local_seed", "as_of": "2026-10-24T10:00:00+00:00"}]})


class FilteredInventoryRegistry:
    def available(self, _ctx):
        return [ToolSpec(name="inventory_page", description="inventory", input_schema={})]

    async def invoke(self, name, arguments, ctx, budget):
        assert name == "inventory_page"
        record = {"id": "I001", "part_id": "P001", "warehouse_id": "W01", "unit": "套",
                  "on_hand": 20, "available": 15, "inbound": 10, "shortage": 55, "warning": True}
        return ToolResult(ok=True, call_id="call-filtered", meta={
            "data_source": "local_seed", "scope": "warehouse:W01", "as_of": "2026-10-24T10:00:00+00:00",
            "snapshot_id": "filtered-subset-snapshot",
        }, data={"records": [record], "total": 1, "page": 1, "page_size": 1, "pages": 1,
                "source_refs": [{"call_id": "call-filtered", "entity": "inventory", "id": "I001",
                                 "data_source": "local_seed", "as_of": "2026-10-24T10:00:00+00:00"}]})


class GenericPagedRegistry:
    def __init__(self, tool_name, rows, *, pages=2, snapshot_ids=None, as_of=None):
        self.tool_name = tool_name
        self.rows = rows
        self.pages = pages
        self.snapshot_ids = snapshot_ids or ["snap-1"] * pages
        self.as_of = as_of or [f"2026-10-24T10:00:0{index}+00:00" for index in range(1, pages + 1)]

    def available(self, _ctx):
        return [ToolSpec(name=self.tool_name, description=self.tool_name, input_schema={})]

    async def invoke(self, name, arguments, ctx, budget):
        assert name == self.tool_name
        page = arguments["page"]
        row = self.rows[page - 1]
        entity = "quote" if self.tool_name == "quote_list" else "inventory"
        return ToolResult(ok=True, call_id=f"call-{page}", meta={
            "data_source": "local_seed", "scope": "warehouse:W01", "as_of": self.as_of[page - 1],
            "snapshot_id": self.snapshot_ids[page - 1],
        }, data={"records": [row], "total": self.pages, "page": page, "page_size": 1, "pages": self.pages,
                "source_refs": [{"call_id": f"call-{page}", "entity": entity, "id": row["id"],
                                 "data_source": "local_seed", "as_of": self.as_of[page - 1]}]})


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


@pytest.mark.asyncio
async def test_part_specific_report_rejects_additional_part_rows(tmp_path):
    registry = AnalysisToolRegistry(PagedInventoryRegistry(), object(),
        ArtifactService(MemoryArtifactRepository(), tmp_path, SystemClock()), EventRecorder(), sandbox_enabled=False)
    ctx = RequestContext(owner_id="owner", request_id="req", run_id="run")
    budget = RunBudget(ctx.run_id)
    for page in (1, 2):
        result = await registry.invoke("inventory_page", {
            "warehouse_id": "W01", "page": page, "page_size": 1,
        }, ctx, budget)
        assert result.ok

    assert registry.latest_report_dataset_id(ctx, "只分析W01的P001并生成报告") is None


@pytest.mark.asyncio
async def test_all_inventory_request_rejects_unrequested_part_name_subset_and_never_verifies_report(tmp_path):
    from backend.app.agent.graph import GraphExecutor
    from backend.app.contracts.agent import ExecutorInput

    artifacts = ArtifactService(MemoryArtifactRepository(), tmp_path, SystemClock())
    events = EventRecorder()
    registry = AnalysisToolRegistry(FilteredInventoryRegistry(), object(), artifacts, events, sandbox_enabled=False)
    ctx = RequestContext(owner_id="owner", request_id="req", run_id="run")
    budget = RunBudget(ctx.run_id)
    filtered = await registry.invoke("inventory_page", {
        "warehouse_id": "W01", "part_name": "刹车片", "page": 1, "page_size": 1,
    }, ctx, budget)
    dataset_id = filtered.meta["dataset_id"]
    request = ExecutorInput(run_id="run", thread_id="thread", message="分析W01全部库存并生成报告",
        ctx=ctx, graph_version="v2")

    assert not registry.report_dataset_matches_request(dataset_id, ctx, request.message)
    report = await registry.invoke("artifact_report", {"dataset_id": dataset_id, "format": "md"}, ctx, budget)
    assert report.ok, report.error
    artifact, body = await artifacts.open(report.data["artifact_id"], ctx)
    text = body.decode("utf-8")
    assert artifact.kind == "md"
    assert "P001" in text and "查询范围内返回 1 条库存记录" in text
    assert "P002" not in text

    class Runs:
        def __init__(self):
            self.rows = [{"type": kind, "payload": payload} for _run_id, kind, payload in events.events]

        async def events(self, *_args):
            return self.rows

        async def append_event(self, _run_id, kind, payload, _ctx):
            self.rows.append({"type": kind, "payload": payload})

    executor = GraphExecutor(None, lambda _ctx: None, runs=Runs())
    verified = await executor._verify_report_artifact(
        registry, request, report.data["artifact_id"], dataset_id, "md", report.data,
    )
    assert not verified
    assert not any(row.get("type") == "report_verified" for row in executor._runs.rows)


@pytest.mark.parametrize("tool_name,request_text", [
    ("inventory_warning", "分析W01库存预警并生成报告"),
    ("quote_list", "分析P001供应商报价并生成报告"),
])
@pytest.mark.asyncio
async def test_formal_report_rejects_missing_pages_for_all_paged_tool_sources(tmp_path, tool_name, request_text):
    rows = ([{"id": "I001", "part_id": "P001", "warehouse_id": "W01", "unit": "套",
              "on_hand": 20, "available": 15, "inbound": 10, "shortage": 55, "warning": True}]
            if tool_name == "inventory_warning" else
            [{"id": "Q01", "part_id": "P001", "part_name": "刹车片", "part_unit": "套", "supplier_id": "S01",
              "supplier_name": "S01", "unit_price_cents": 1200, "lead_days": 5, "is_valid": True}])
    artifacts = ArtifactService(MemoryArtifactRepository(), tmp_path, SystemClock())
    registry = AnalysisToolRegistry(GenericPagedRegistry(tool_name, rows, pages=2), object(), artifacts,
                                    EventRecorder(), sandbox_enabled=False)
    ctx = RequestContext(owner_id="owner", request_id="req", run_id="run")
    result = await registry.invoke(tool_name, {"warehouse_id": "W01", "part_id": "P001", "page": 1, "page_size": 1},
                                   ctx, RunBudget(ctx.run_id))

    assert result.ok
    assert registry.latest_report_dataset_id(ctx, request_text) is None
    report = await registry.invoke("artifact_report", {"dataset_id": result.meta["dataset_id"], "format": "md"},
                                   ctx, RunBudget(ctx.run_id))
    assert not report.ok
    assert report.error["code"] == "INCOMPLETE_DATASET"


@pytest.mark.parametrize("tool_name,rows,args", [
    ("inventory_warning", [
        {"id": "I001", "part_id": "P001", "warehouse_id": "W01", "unit": "套", "on_hand": 20,
         "available": 15, "inbound": 10, "shortage": 55, "warning": True},
        {"id": "I002", "part_id": "P002", "warehouse_id": "W01", "unit": "个", "on_hand": 20,
         "available": 18, "inbound": 0, "shortage": 12, "warning": True}], {"warehouse_id": "W01"}),
    ("quote_list", [
        {"id": "Q01", "part_id": "P001", "part_name": "刹车片", "part_unit": "套", "supplier_id": "S01",
         "supplier_name": "S01", "unit_price_cents": 1200, "lead_days": 5, "is_valid": True},
        {"id": "Q02", "part_id": "P001", "part_name": "刹车片", "part_unit": "套", "supplier_id": "S02",
         "supplier_name": "S02", "unit_price_cents": 1100, "lead_days": 12, "is_valid": True}], {"part_id": "P001"}),
])
@pytest.mark.asyncio
async def test_page_aggregation_accepts_realistic_per_call_times_only_with_matching_snapshot(tmp_path, tool_name, rows, args):
    artifacts = ArtifactService(MemoryArtifactRepository(), tmp_path, SystemClock())
    registry = AnalysisToolRegistry(GenericPagedRegistry(tool_name, rows, pages=2), object(), artifacts,
                                    EventRecorder(), sandbox_enabled=False)
    ctx = RequestContext(owner_id="owner", request_id="req", run_id="run")
    budget = RunBudget(ctx.run_id)
    for page in (1, 2):
        result = await registry.invoke(tool_name, {**args, "page": page, "page_size": 1}, ctx, budget)
        assert result.ok

    dataset_id = registry.latest_report_dataset_id(ctx, "生成完整报告")
    assert dataset_id is not None
    assert registry.report_dataset_matches_request(dataset_id, ctx, "生成完整报告")

    drift = AnalysisToolRegistry(GenericPagedRegistry(tool_name, rows, pages=2, snapshot_ids=["snap-1", "snap-2"]),
                                 object(), artifacts, EventRecorder(), sandbox_enabled=False)
    for page in (1, 2):
        await drift.invoke(tool_name, {**args, "page": page, "page_size": 1}, ctx, budget)
    assert drift.latest_report_dataset_id(ctx, "生成完整报告") is None


@pytest.mark.asyncio
async def test_real_local_source_adapters_emit_stable_paged_snapshot_and_detect_inventory_drift(
    tmp_path, db_name, mongo_admin,
):
    from datetime import timedelta

    from backend.app.agent.local_tools import LocalToolRegistry
    from backend.app.repositories.catalog import CatalogRepository
    from backend.app.repositories.indexes import ensure_indexes
    from backend.app.repositories.inventory import InventoryRepository
    from backend.app.repositories.mongo import MongoResources
    from backend.app.services.seeding import seed
    from tests.integration.conftest import make_settings

    class TickClock:
        def __init__(self):
            self.value = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)

        def now(self):
            result = self.value
            self.value += timedelta(microseconds=1)
            return result

    resources = await MongoResources.open(make_settings(db_name, storage_root=tmp_path))
    try:
        await ensure_indexes(resources.db)
        await seed(resources.db, reset=True)
        source = LocalToolRegistry(CatalogRepository(resources), InventoryRepository(resources), TickClock())
        ctx = RequestContext(owner_id="owner", request_id="req", run_id="run")
        budget = RunBudget(ctx.run_id)
        registry = AnalysisToolRegistry(source, object(), ArtifactService(MemoryArtifactRepository(), tmp_path, SystemClock()),
                                        EventRecorder(), sandbox_enabled=False)

        for tool_name, base_args in (
            ("inventory_page", {"warehouse_id": "W01"}),
            ("inventory_warning", {"warehouse_id": "W01"}),
            ("quote_list", {"part_id": "P001"}),
        ):
            first = await registry.invoke(tool_name, {**base_args, "page": 1, "page_size": 1}, ctx, budget)
            assert first.ok
            first_snapshot = registry._datasets[first.meta["dataset_id"]].snapshot_id
            first_as_of = registry._datasets[first.meta["dataset_id"]].as_of
            for page in range(2, first.data["pages"] + 1):
                result = await registry.invoke(tool_name, {**base_args, "page": page, "page_size": 1}, ctx, budget)
                assert result.ok
                current = registry._datasets[result.meta["dataset_id"]]
                assert current.snapshot_id == first_snapshot
                assert current.as_of != first_as_of
            assert registry.latest_report_dataset_id(ctx) is not None

        # A source mutation between pages changes the full-result fingerprint. Pages
        # from both observations must not be presented as a single complete report.
        drifting = AnalysisToolRegistry(source, object(), ArtifactService(MemoryArtifactRepository(), tmp_path, SystemClock()),
                                        EventRecorder(), sandbox_enabled=False)
        first = await drifting.invoke("inventory_page", {"warehouse_id": "W01", "page": 1, "page_size": 1}, ctx, budget)
        assert first.ok and first.data["pages"] > 1
        inventory_id = first.data["records"][0]["id"]
        await resources.db["inventories"].update_one({"_id": inventory_id}, {"$inc": {"on_hand": 1, "version": 1}})
        for page in range(2, first.data["pages"] + 1):
            assert (await drifting.invoke("inventory_page", {
                "warehouse_id": "W01", "page": page, "page_size": 1,
            }, ctx, budget)).ok
        assert drifting.latest_report_dataset_id(ctx) is None
    finally:
        await resources.close()


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
