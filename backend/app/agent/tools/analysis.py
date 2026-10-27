"""P06分析代码工具：只读授权产物作为输入，代码只进入Docker沙箱。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any
from uuid import uuid4

from backend.app.agent.budget import (
    RunBudget,
    RunCancelled,
    RunDeadlineExceeded,
    RunLimitExceeded,
)
from backend.app.contracts.artifacts import (
    AuthorizedDataset,
    CollectedOutput,
    SandboxJob,
)
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
        self._report_datasets: dict[str, AuthorizedDataset] = {}
        self._dataset_bytes = 0

    def latest_report_dataset_id(self, ctx: RequestContext, request_message: str = "") -> str | None:
        """Return the newest in-scope dataset, requiring a complete source snapshot for paged tools."""
        requested_warehouses = {value.upper() for value in re.findall(r"(?<![A-Za-z0-9])W\d{2}(?![A-Za-z0-9])", request_message, re.IGNORECASE)}
        requested_parts = {value.upper() for value in re.findall(r"(?<![A-Za-z0-9])P\d{3}(?![A-Za-z0-9])", request_message, re.IGNORECASE)}
        all_inventory_requested = bool(re.search(r"(?:全部|所有|完整).{0,6}库存|库存.{0,6}(?:全部|所有|完整)", request_message))
        for dataset_id, dataset in reversed(list(self._datasets.items())):
            if (dataset.owner_id == ctx.owner_id and dataset.run_id == ctx.run_id
                    and dataset.tool_name in {"replenishment_preview", "inventory_page", "inventory_warning", "quote_list"}):
                args = dataset.arguments
                if all_inventory_requested and (dataset.tool_name != "inventory_page"
                        or args.get("part_name") or args.get("part_id") or args.get("part_ids")):
                    continue
                warehouses = {str(args.get("warehouse_id")).upper()} if args.get("warehouse_id") else set()
                if requested_warehouses and not requested_warehouses.issubset(warehouses):
                    continue
                if dataset.tool_name in {"inventory_page", "inventory_warning", "quote_list"}:
                    report_dataset = self._complete_paged_dataset(dataset, ctx)
                    if report_dataset is None:
                        continue
                    observed_parts = {str(row.get("part_id", "")).upper() for row in report_dataset.data["records"]
                                      if isinstance(row, dict)}
                    if requested_parts and observed_parts != requested_parts:
                        continue
                    report_id = "ds_report_" + uuid4().hex
                    self._report_datasets[report_id] = report_dataset.model_copy(update={"dataset_id": report_id})
                    if not self.report_dataset_matches_request(report_id, ctx, request_message):
                        self._report_datasets.pop(report_id, None)
                        continue
                    return report_id
                if not self.report_dataset_matches_request(dataset_id, ctx, request_message):
                    continue
                return dataset_id
        return None

    def _authorized_report_dataset(self, dataset_id: str, ctx: RequestContext) -> AuthorizedDataset | None:
        report_dataset = self._report_datasets.get(dataset_id)
        if report_dataset is not None:
            return report_dataset if report_dataset.owner_id == ctx.owner_id and report_dataset.run_id == ctx.run_id else None
        dataset = self._datasets.get(dataset_id) or self._report_datasets.get(dataset_id)
        if dataset is None or dataset.owner_id != ctx.owner_id or dataset.run_id != ctx.run_id:
            return None
        if dataset.tool_name in {"inventory_page", "inventory_warning", "quote_list"}:
            return self._complete_paged_dataset(dataset, ctx)
        return dataset

    def report_dataset_matches_request(self, dataset_id: str, ctx: RequestContext, request_message: str) -> bool:
        dataset = self._authorized_report_dataset(dataset_id, ctx)
        if dataset is None:
            return False
        requested_warehouses = {value.upper() for value in re.findall(r"(?<![A-Za-z0-9])W\d{2}(?![A-Za-z0-9])", request_message, re.IGNORECASE)}
        requested_parts = {value.upper() for value in re.findall(r"(?<![A-Za-z0-9])P\d{3}(?![A-Za-z0-9])", request_message, re.IGNORECASE)}
        all_inventory_requested = bool(re.search(r"(?:全部|所有|完整).{0,6}库存|库存.{0,6}(?:全部|所有|完整)", request_message))
        args = dataset.arguments
        if all_inventory_requested and (dataset.tool_name != "inventory_page"
                or args.get("part_name") or args.get("part_id") or args.get("part_ids")):
            return False
        warehouses = {str(args.get("warehouse_id")).upper()} if args.get("warehouse_id") else set()
        parts = {str(value).upper() for value in args.get("part_ids", [])}
        if args.get("part_id"):
            parts.add(str(args["part_id"]).upper())
        if requested_parts:
            data = dataset.data if isinstance(dataset.data, dict) else {}
            observed_parts = {str(row.get("part_id", "")).upper() for row in
                              (data.get("records") or data.get("lines") or []) if isinstance(row, dict)}
            if observed_parts != requested_parts:
                return False
        if requested_warehouses:
            data = dataset.data if isinstance(dataset.data, dict) else {}
            observed_warehouses = {str(row.get("warehouse_id", "")).upper() for row in
                                   (data.get("records") or data.get("lines") or []) if isinstance(row, dict)}
            if observed_warehouses != requested_warehouses or not requested_warehouses.issubset(warehouses):
                return False
        return True

    async def verify_report_artifact(self, artifact_id: str, dataset_id: str, format: str,
                                     ctx: RequestContext) -> dict[str, Any] | None:
        """Reopen and compare the registered report body with server-derived facts."""
        dataset = self._authorized_report_dataset(dataset_id, ctx)
        if dataset is None:
            return None
        try:
            from backend.app.sandbox.reports import build_report_spec
            from backend.app.services.analysis_artifacts import build_analysis_result

            expected = build_report_spec(format, build_analysis_result(dataset))
            artifact, content = await self._artifacts.open(artifact_id, ctx)
        except Exception:
            return None
        expected_refs = [{str(key): str(value) for key, value in ref.items() if value is not None}
                         for ref in dataset.source_refs]
        if (artifact.run_id != ctx.run_id or artifact.owner_id != ctx.owner_id
                or artifact.kind != format or artifact.mime != expected.mime
                or artifact.source_refs != expected_refs or content != expected.content):
            return None
        return {"artifact_id": artifact.id, "dataset_id": dataset_id, "format": format,
                "scope": build_analysis_result(dataset).scope, "source_refs": artifact.source_refs,
                "content_sha256": hashlib.sha256(content).hexdigest()}

    def _complete_paged_dataset(self, target: AuthorizedDataset, ctx: RequestContext) -> AuthorizedDataset | None:
        data = target.data
        if not isinstance(data, dict):
            return None
        page = data.get("page")
        page_size = data.get("page_size")
        total = data.get("total")
        pages = data.get("pages")
        if (target.tool_name not in {"inventory_page", "inventory_warning", "quote_list"}
                or any(type(value) is not int for value in (page, page_size, total, pages))
                or page_size < 1 or total < 1 or pages < 1 or not target.snapshot_id
                or pages != (total + page_size - 1) // page_size):
            return None
        query = {key: value for key, value in target.arguments.items() if key != "page"}
        candidates = []
        for dataset in self._datasets.values():
            candidate_data = dataset.data
            if (dataset.tool_name != target.tool_name or dataset.owner_id != ctx.owner_id or dataset.run_id != ctx.run_id
                    or dataset.arguments.get("page_size") != page_size
                    or {key: value for key, value in dataset.arguments.items() if key != "page"} != query
                    or dataset.data_source != target.data_source or dataset.snapshot_id != target.snapshot_id
                    or dataset.scope != target.scope or not isinstance(candidate_data, dict)
                    or candidate_data.get("total") != total or candidate_data.get("pages") != pages
                    or candidate_data.get("page_size") != page_size):
                continue
            candidate_page = candidate_data.get("page")
            records = candidate_data.get("records")
            if type(candidate_page) is not int or candidate_page < 1 or candidate_page > pages or not isinstance(records, list):
                return None
            candidates.append(dataset)
        by_page: dict[int, AuthorizedDataset] = {}
        for candidate in candidates:
            candidate_page = int(candidate.data["page"])
            if candidate_page in by_page:
                return None
            by_page[candidate_page] = candidate
        if set(by_page) != set(range(1, pages + 1)):
            return None
        records: list[dict[str, Any]] = []
        source_refs: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for page_number in range(1, pages + 1):
            dataset = by_page[page_number]
            page_records = dataset.data["records"]
            expected_size = page_size if page_number < pages else total - page_size * (pages - 1)
            if len(page_records) != expected_size:
                return None
            for record in page_records:
                if not isinstance(record, dict) or not record.get("id") or str(record["id"]) in seen_ids:
                    return None
                seen_ids.add(str(record["id"]))
                records.append(record)
            source_refs.extend(dataset.source_refs)
        if len(records) != total:
            return None
        combined = dict(data)
        combined["records"] = records
        combined["page"] = 1
        combined["page_size"] = max(page_size, total)
        combined["pages"] = 1
        combined["total"] = total
        unique_refs = {(ref.get("entity"), ref.get("id"), ref.get("call_id")): ref for ref in source_refs}
        return target.model_copy(update={"data": combined, "source_refs": list(unique_refs.values()),
                                         "as_of": max((item.as_of for item in by_page.values() if item.as_of), default=target.as_of)})

    # Backwards-compatible internal name used by older focused tests.
    def _complete_inventory_pages(self, target: AuthorizedDataset, ctx: RequestContext) -> AuthorizedDataset | None:
        return self._complete_paged_dataset(target, ctx)

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
                            snapshot_id=result.meta.get("snapshot_id"),
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
            requested_dataset_id = str(arguments.get("dataset_id"))
            dataset = self._datasets.get(requested_dataset_id) or self._report_datasets.get(requested_dataset_id)
            if dataset is None or dataset.owner_id != ctx.owner_id or dataset.run_id != ctx.run_id:
                return ToolResult(ok=False, error={"code": "DATASET_NOT_AUTHORIZED", "message": "dataset is not available to this owner/run"}, call_id=ctx.call_id or "")
            if (name == "artifact_report" and dataset.tool_name in {"inventory_page", "inventory_warning", "quote_list"}
                    and requested_dataset_id not in self._report_datasets):
                dataset = self._complete_paged_dataset(dataset, ctx)
                if dataset is None:
                    return ToolResult(ok=False, error={"code": "INCOMPLETE_DATASET", "message": "all pages from one consistent inventory snapshot are required"}, call_id=ctx.call_id or "")
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
            except (RunCancelled, RunDeadlineExceeded, RunLimitExceeded):
                raise
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
        except (RunCancelled, RunDeadlineExceeded, RunLimitExceeded):
            raise
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
