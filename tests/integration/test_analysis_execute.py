import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.agent.budget import RunBudget
from backend.app.agent.tools.analysis import AnalysisToolRegistry
from backend.app.contracts.common import RequestContext, SystemClock
from backend.app.ports.tools import ToolResult, ToolSpec
from backend.app.sandbox.runner import DockerSandbox
from backend.app.services.artifacts import ArtifactService


class ReadOnlyRegistry:
    def available(self, ctx):
        return [ToolSpec(name="inventory_page", description="read", input_schema={})]

    async def invoke(self, name, arguments, ctx, budget):
        return ToolResult(ok=True, data={"records": [{"id": "I001", "part_id": "P001", "on_hand": 20}],
                                        "source_refs": [{"entity": "inventory", "id": "I001"}]},
                          meta={"data_source": "local_seed"}, call_id="call_inventory")


class MemoryArtifactsRepository:
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
async def test_analysis_execute_runs_in_docker_and_registers_authorized_output():
    sandbox = DockerSandbox()
    available, reason = await sandbox.available()
    if not available:
        if os.getenv("P06_REQUIRED") == "1":
            pytest.fail(f"P06 requires real Docker analysis execution: {reason}")
        pytest.skip(f"sandbox image unavailable: {reason}")

    root = Path(".runtime") / ("test-analysis-artifacts-" + uuid4().hex)
    root.mkdir(parents=True, exist_ok=False)
    repository, events = MemoryArtifactsRepository(), EventRecorder()
    artifacts = ArtifactService(repository, root, SystemClock())
    registry = AnalysisToolRegistry(ReadOnlyRegistry(), sandbox, artifacts, events)
    ctx = RequestContext(owner_id="owner-p06", request_id="req-p06", run_id="run-p06")
    try:
        read = await registry.invoke("inventory_page", {}, ctx, RunBudget(ctx.run_id))
        result = await registry.invoke("analysis_execute", {
            "input_dataset_ids": [read.meta["dataset_id"]],
            "output_allowlist": ["inventory.csv"],
            "code": """import csv, json
row = json.load(open('/work/data/dataset-1.json', encoding='utf-8'))['records'][0]
with open('/out/inventory.csv', 'w', encoding='utf-8', newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['物料', '在手（件）'])
    writer.writerow([row['part_id'], row['on_hand']])
""",
        }, ctx, RunBudget(ctx.run_id))

        assert result.ok, result.error
        artifact_doc = next(iter(repository.rows.values()))
        artifact, content = await artifacts.open(artifact_doc["_id"], ctx)
        assert artifact.run_id == ctx.run_id and artifact.owner_id == ctx.owner_id
        assert content.decode("utf-8").splitlines() == ["物料,在手（件）", "P001,20"]
        assert events.events == [(ctx.run_id, "artifact_ready", {
            "artifact_id": artifact.id, "kind": "csv", "filename": "inventory.csv",
            "mime": "text/csv", "source_refs": [{"entity": "inventory", "id": "I001"}],
        })]
    finally:
        shutil.rmtree(root, ignore_errors=True)
