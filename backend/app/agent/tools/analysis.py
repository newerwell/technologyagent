"""P06分析代码工具：只读授权产物作为输入，代码只进入Docker沙箱。"""
from __future__ import annotations

import json
from uuid import uuid4
from typing import Any

from backend.app.agent.budget import RunBudget
from backend.app.contracts.artifacts import CollectedOutput, SandboxJob
from backend.app.contracts.common import RequestContext
from backend.app.ports.tools import ToolResult, ToolSpec

ANALYSIS_SPEC = ToolSpec(
    name="analysis_execute",
    description="在隔离容器中分析当前run已授权的CSV/JSON数据并生成允许格式的文件。",
    effect="sandbox_execute", capability="sandbox.execute",
    input_schema={"type": "object", "properties": {
        "code": {"type": "string", "maxLength": 100000},
        "input_dataset_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "output_allowlist": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10},
    }, "required": ["code", "input_dataset_ids", "output_allowlist"], "additionalProperties": False},
)


class AnalysisToolRegistry:
    def __init__(self, base, sandbox, artifacts, runs, sandbox_enabled: bool = True):
        self._base, self._sandbox, self._artifacts, self._runs = base, sandbox, artifacts, runs
        self._sandbox_enabled = sandbox_enabled
        self._datasets: dict[str, bytes] = {}

    def available(self, ctx: RequestContext) -> list[ToolSpec]:
        tools = self._base.available(ctx)
        return [*tools, ANALYSIS_SPEC] if self._sandbox_enabled else tools

    async def close(self) -> None:
        close = getattr(self._base, "close", None)
        if close is not None:
            await close()

    async def invoke(self, name: str, arguments: dict[str, Any], ctx: RequestContext, budget: RunBudget) -> ToolResult:
        if name != "analysis_execute":
            result = await self._base.invoke(name, arguments, ctx, budget)
            if result.ok and result.data is not None:
                try:
                    payload = json.dumps(result.data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    if len(payload) <= 5 * 1024 * 1024 and sum(map(len, self._datasets.values())) + len(payload) <= 20 * 1024 * 1024:
                        dataset_id = "ds_" + uuid4().hex
                        self._datasets[dataset_id] = payload
                        meta = {**result.meta, "dataset_id": dataset_id}
                        return ToolResult(ok=True, data=result.data, error=result.error, meta=meta, call_id=result.call_id)
                except (TypeError, ValueError):
                    pass
            return result
        try:
            await budget.check_cancelled()
            await budget.check_active()
            if not ctx.run_id:
                raise ValueError("analysis requires a trusted active run")
            ids = arguments["input_dataset_ids"]
            if len(ids) > 10 or len(set(ids)) != len(ids):
                raise ValueError("dataset IDs must be unique and limited to 10")
            inputs = []
            refs = []
            for artifact_id in ids:
                content = self._datasets.get(artifact_id)
                if content is None:
                    artifact, content = await self._artifacts.open(artifact_id, ctx)
                    if artifact.run_id != ctx.run_id or artifact.mime not in {"text/csv", "application/json"}:
                        raise ValueError("dataset is outside this owner/run or unsupported")
                    refs.append({"entity": "artifact", "id": artifact.id})
                else:
                    refs.append({"entity": "tool_result", "id": artifact_id})
                inputs.append({"filename": f"dataset-{len(inputs) + 1}.json", "content": content})
            output_names = arguments["output_allowlist"]
            if not isinstance(output_names, list) or not output_names or len(output_names) > 10:
                raise ValueError("output allowlist must contain 1 to 10 filenames")
            available, reason = await self._sandbox.available()
            if not available:
                return ToolResult(ok=False, error={"code": "SANDBOX_UNAVAILABLE", "message": reason}, call_id=ctx.call_id or "")
            from backend.app.contracts.artifacts import SandboxInput
            job = SandboxJob(code=arguments["code"], input_files=[SandboxInput(**item) for item in inputs],
                             output_allowlist=output_names)
            result = await self._sandbox.execute(job, ctx)
            if result.timed_out:
                return ToolResult(ok=False, error={"code": "SANDBOX_TIMEOUT", "message": "分析代码超过30秒并已终止"}, call_id=ctx.call_id or "")
            if result.exit_code != 0 or not result.outputs:
                return ToolResult(ok=False, error={"code": "SANDBOX_EXECUTION_FAILED", "message": result.diagnostics or f"container exit {result.exit_code}"}, call_id=ctx.call_id or "")
            registered = []
            for output in result.outputs:
                item = CollectedOutput(**{**output.model_dump(), "source_refs": refs})
                artifact = await self._artifacts.register(item, ctx)
                registered.append(artifact)
                await self._runs.append_event(ctx.run_id, "artifact_ready", {
                    "artifact_id": artifact.id, "kind": artifact.kind, "filename": artifact.filename,
                    "mime": artifact.mime, "source_refs": artifact.source_refs,
                }, ctx)
            return ToolResult(ok=True, data={"artifacts": [item.model_dump(mode="json") for item in registered]},
                              meta={"source_refs": refs}, call_id=ctx.call_id or "")
        except Exception as exc:
            code = getattr(exc, "code", "ANALYSIS_FAILED")
            return ToolResult(ok=False, error={"code": code, "message": str(exc)[:300]}, call_id=ctx.call_id or "")


class AnalysisRegistryFactory:
    def __init__(self, base_factory, sandbox, artifacts, runs):
        self._base_factory, self._sandbox, self._artifacts, self._runs = base_factory, sandbox, artifacts, runs

    async def __call__(self, ctx: RequestContext):
        base = await self._base_factory(ctx)
        available, _ = await self._sandbox.available()
        return AnalysisToolRegistry(base, self._sandbox, self._artifacts, self._runs, sandbox_enabled=available)
