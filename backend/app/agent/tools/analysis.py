"""P06分析代码工具：只读授权产物作为输入，代码只进入Docker沙箱。"""
from __future__ import annotations

import json
import asyncio
import time
from uuid import uuid4
from typing import Any

from backend.app.agent.budget import RunBudget
from backend.app.contracts.artifacts import AuthorizedDataset, CollectedOutput, SandboxJob
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

REPORT_SPEC = ToolSpec(
    name="artifact_report",
    description="把当前run成功只读查询的数据生成结构化报告；金额、明细、范围和来源由服务端事实派生。",
    effect="artifact_generate", capability="artifacts.generate",
    input_schema={"type": "object", "properties": {
        "dataset_id": {"type": "string"},
        "format": {"type": "string", "enum": ["md", "html", "csv", "json"]},
    }, "required": ["dataset_id", "format"], "additionalProperties": False},
)

CHART_SPEC = ToolSpec(
    name="artifact_chart",
    description="根据当前run成功只读查询的真实事实生成bar、line或pie图；数值不能由模型直接指定。",
    effect="sandbox_execute", capability="sandbox.execute",
    input_schema={"type": "object", "properties": {
        "dataset_id": {"type": "string"},
        "kind": {"type": "string", "enum": ["bar", "line", "pie"]},
    }, "required": ["dataset_id", "kind"], "additionalProperties": False},
)

_DATASET_MAX_BYTES = 5 * 1024 * 1024
_DATASETS_MAX_BYTES = 20 * 1024 * 1024


class AnalysisToolRegistry:
    def __init__(self, base, sandbox, artifacts, runs, sandbox_enabled: bool = True):
        self._base, self._sandbox, self._artifacts, self._runs = base, sandbox, artifacts, runs
        self._sandbox_enabled = sandbox_enabled
        from backend.app.services.analysis_artifacts import AnalysisArtifactService
        self._artifact_generator = AnalysisArtifactService(sandbox, artifacts, runs)
        self._datasets: dict[str, AuthorizedDataset] = {}
        self._dataset_bytes = 0

    def available(self, ctx: RequestContext) -> list[ToolSpec]:
        tools = self._base.available(ctx)
        return [*tools, REPORT_SPEC, *([ANALYSIS_SPEC, CHART_SPEC] if self._sandbox_enabled else [])]

    async def close(self) -> None:
        close = getattr(self._base, "close", None)
        if close is not None:
            await close()

    async def invoke(self, name: str, arguments: dict[str, Any], ctx: RequestContext, budget: RunBudget) -> ToolResult:
        if name not in {"analysis_execute", "artifact_report", "artifact_chart"}:
            result = await self._base.invoke(name, arguments, ctx, budget)
            if result.ok and result.data is not None:
                try:
                    payload = json.dumps(result.data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    if len(payload) <= _DATASET_MAX_BYTES and self._dataset_bytes + len(payload) <= _DATASETS_MAX_BYTES and ctx.run_id:
                        dataset_id = "ds_" + uuid4().hex
                        call_id = result.call_id or result.meta.get("call_id") or ctx.call_id or ""
                        refs = self._source_refs(name, result.data, result.meta, str(call_id))
                        dataset = AuthorizedDataset(
                            dataset_id=dataset_id, owner_id=ctx.owner_id, run_id=ctx.run_id,
                            call_id=str(call_id), tool_name=name, arguments=arguments,
                            data_source=str(result.meta.get("data_source") or "unknown"),
                            scope=str(result.meta.get("scope") or ""), as_of=result.meta.get("as_of"),
                            source_refs=refs, data=json.loads(payload),
                        )
                        self._datasets[dataset_id] = dataset
                        self._dataset_bytes += len(payload)
                        meta = {**result.meta, "dataset_id": dataset_id}
                        return ToolResult(ok=True, data=result.data, error=result.error, meta=meta, call_id=result.call_id)
                except (TypeError, ValueError):
                    pass
            return result
        if name in {"artifact_report", "artifact_chart"}:
            required = {"dataset_id", "format"} if name == "artifact_report" else {"dataset_id", "kind"}
            allowed = required
            if set(arguments) != allowed:
                return ToolResult(ok=False, error={"code": "INVALID_ARGUMENTS", "message": "artifact request fields do not match the schema"}, call_id=ctx.call_id or "")
            dataset = self._datasets.get(str(arguments.get("dataset_id")))
            if dataset is None or dataset.owner_id != ctx.owner_id or dataset.run_id != ctx.run_id:
                return ToolResult(ok=False, error={"code": "DATASET_NOT_AUTHORIZED", "message": "dataset is not available to this owner/run"}, call_id=ctx.call_id or "")
            try:
                await budget.check_cancelled()
                await budget.check_active()
                if name == "artifact_report":
                    artifact = await self._artifact_generator.generate_report(dataset, str(arguments["format"]), ctx)
                else:
                    artifact = await self._artifact_generator.generate_chart(dataset, str(arguments["kind"]), ctx, budget)
                await budget.check_cancelled()
                await budget.check_active()
                return ToolResult(ok=True, data={"artifact_id": artifact.id, "filename": artifact.filename,
                    "kind": artifact.kind, "mime": artifact.mime, "source_refs": artifact.source_refs},
                    meta={"source_refs": artifact.source_refs, "dataset_call_id": dataset.call_id}, call_id=ctx.call_id or "")
            except Exception as exc:
                code = getattr(exc, "code", "ARTIFACT_GENERATION_FAILED")
                return ToolResult(ok=False, error={"code": code, "message": str(exc)[:300]}, call_id=ctx.call_id or "")
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
                dataset = self._datasets.get(artifact_id)
                if dataset is None:
                    artifact, content = await self._artifacts.open(artifact_id, ctx)
                    if artifact.run_id != ctx.run_id or artifact.mime not in {"text/csv", "application/json"}:
                        raise ValueError("dataset is outside this owner/run or unsupported")
                    refs.extend(artifact.source_refs or [{"entity": "artifact", "id": artifact.id}])
                else:
                    if dataset.owner_id != ctx.owner_id or dataset.run_id != ctx.run_id:
                        raise ValueError("dataset is outside this owner/run")
                    refs.extend(dataset.source_refs)
                    content = json.dumps(dataset.data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                inputs.append({"filename": f"dataset-{len(inputs) + 1}.json", "content": content})
            if not refs:
                raise ValueError("analysis outputs require traceable business source references")
            output_names = arguments["output_allowlist"]
            if not isinstance(output_names, list) or not output_names or len(output_names) > 10:
                raise ValueError("output allowlist must contain 1 to 10 filenames")
            if not self._sandbox_enabled:
                return ToolResult(ok=False, error={"code": "SANDBOX_UNAVAILABLE", "message": "sandbox capability is unavailable"}, call_id=ctx.call_id or "")
            from backend.app.contracts.artifacts import SandboxInput
            job = SandboxJob(code=arguments["code"], input_files=[SandboxInput(**item) for item in inputs],
                             output_allowlist=output_names)
            result = await self._sandbox.execute(job, ctx, budget)
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

    @staticmethod
    def _source_refs(name: str, data: Any, meta: dict[str, Any], call_id: str) -> list[dict[str, str]]:
        refs = data.get("source_refs") if isinstance(data, dict) else None
        normalized = []
        for ref in refs or []:
            if not isinstance(ref, dict) or not ref.get("entity") or not ref.get("id"):
                continue
            normalized.append({str(key): str(value) for key, value in ref.items() if value is not None})
        if normalized:
            return normalized
        entity = {"quote_list": "quote", "inventory_page": "inventory", "inventory_warning": "inventory",
                  "inventory_get": "inventory", "supplier_query": "supplier", "supplier_get": "supplier",
                  "part_search": "part", "part_query": "part", "order_page": "purchase_order",
                  "order_get": "purchase_order"}.get(name)
        records = data.get("records", []) if isinstance(data, dict) else []
        if isinstance(data, dict) and data.get("id"):
            records = [data]
        for record in records:
            if not isinstance(record, dict) or not record.get("id") or not entity:
                continue
            normalized.append({"call_id": call_id, "entity": entity, "id": str(record["id"]),
                               "data_source": str(meta.get("data_source") or "unknown"),
                               "as_of": str(meta.get("as_of") or "")})
        return normalized


class AnalysisRegistryFactory:
    def __init__(self, base_factory, sandbox, artifacts, runs):
        self._base_factory, self._sandbox, self._artifacts, self._runs = base_factory, sandbox, artifacts, runs
        self._cached_status = None

    async def __call__(self, ctx: RequestContext):
        base = await self._base_factory(ctx)
        # Docker is optional. Do not make the core read-only tool registry wait for it;
        # capability discovery is cached and runs under a short independent deadline.
        available, _ = await self._sandbox_status()
        return AnalysisToolRegistry(base, self._sandbox, self._artifacts, self._runs, sandbox_enabled=available)

    async def _sandbox_status(self) -> tuple[bool, str]:
        cached = getattr(self, "_cached_status", None)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1], cached[2]
        try:
            available, reason = await asyncio.wait_for(self._sandbox.available(), timeout=0.25)
        except Exception as exc:
            available, reason = False, f"{type(exc).__name__}: sandbox probe timed out or failed"
        self._cached_status = (time.monotonic() + 2.0, available, reason)
        return available, reason
