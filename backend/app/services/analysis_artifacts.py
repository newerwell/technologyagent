"""从授权只读结果派生并发布可核验的图表与报告。"""
from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from uuid import uuid4

from backend.app.contracts.artifacts import AuthorizedDataset, ChartSpec, CollectedOutput
from backend.app.contracts.common import RequestContext
from backend.app.agent.budget import RunBudget
from backend.app.ports.sandbox import SandboxPort
from backend.app.sandbox.charts import build_chart_spec, render_chart_in_sandbox
from backend.app.sandbox.reports import AnalysisResult, build_report_spec
from backend.app.services.artifacts import ArtifactService


def _text(value: Any, fallback: str = "") -> str:
    return str(value) if value is not None else fallback


def _sources(dataset: AuthorizedDataset) -> list[dict[str, str]]:
    refs = []
    for ref in dataset.source_refs:
        cleaned = {str(key): str(value) for key, value in ref.items() if value is not None}
        if cleaned.get("entity") and cleaned.get("id"):
            refs.append(cleaned)
    if not refs:
        raise ValueError("authoritative source references are required for a formal artifact")
    return refs


def _scope(dataset: AuthorizedDataset) -> str:
    args = dataset.arguments
    if dataset.tool_name == "replenishment_preview":
        fields = []
        if args.get("warehouse_id"):
            fields.append("仓库 " + _text(args["warehouse_id"]))
        if args.get("part_ids"):
            fields.append("物料 " + "、".join(map(str, args["part_ids"])))
        if args.get("max_lead_days") is not None:
            fields.append("交期不超过 " + _text(args["max_lead_days"]) + " 天")
        return "；".join(fields) or dataset.scope
    if dataset.scope:
        return dataset.scope
    safe = {key: value for key, value in args.items() if key in {"warehouse_id", "part_id", "part_ids", "supplier_id", "page", "page_size"}}
    return json.dumps(safe, ensure_ascii=False, sort_keys=True) if safe else dataset.tool_name


def build_analysis_result(dataset: AuthorizedDataset) -> AnalysisResult:
    """Build rows only from a trusted tool result; callers cannot submit report values."""
    sources = _sources(dataset)
    scope = _scope(dataset)
    as_of = dataset.as_of or "未知（来源未提供时间）"
    data = dataset.data

    if dataset.tool_name == "replenishment_preview" and isinstance(data, dict):
        lines = data.get("lines")
        if not isinstance(lines, list):
            raise ValueError("replenishment result has no structured lines")
        requested_parts = {str(value) for value in dataset.arguments.get("part_ids", [])}
        requested_warehouse = dataset.arguments.get("warehouse_id")
        requested_supplier = dataset.arguments.get("supplier_id")
        max_lead_days = dataset.arguments.get("max_lead_days")
        source_quote_ids = {ref["id"] for ref in sources if ref.get("entity") == "quote"}
        rows: list[list[Any]] = []
        chosen_ids = set()
        for line in lines:
            if not isinstance(line, dict):
                raise ValueError("replenishment line is malformed")
            part_id, warehouse_id = _text(line.get("part_id")), _text(line.get("warehouse_id"))
            if ((requested_parts and part_id not in requested_parts)
                    or (requested_warehouse and warehouse_id != requested_warehouse)):
                raise ValueError("replenishment line is outside the requested part/warehouse scope")
            line_quantity = line.get("quantity")
            if type(line_quantity) is not int or line_quantity < 0:
                raise ValueError("replenishment line quantity must be a non-negative integer")
            unit = line.get("unit")
            if not isinstance(unit, str) or not unit.strip():
                raise ValueError("replenishment line is missing its concrete business unit")
            candidates = line.get("candidate_quotes") or []
            for quote in candidates:
                if not isinstance(quote, dict):
                    raise ValueError("candidate quote is malformed")
                quote_id = _text(quote.get("quote_id"))
                if not quote_id or quote_id not in source_quote_ids:
                    raise ValueError("candidate quote is not bound to a query source reference")
                cents = quote.get("unit_price_cents")
                quantity = quote.get("suggested_quantity")
                total = quote.get("line_total_cents")
                if any(type(value) is not int for value in (cents, quantity, total)):
                    raise ValueError("candidate money and quantity must be integer values")
                if quantity != line_quantity:
                    raise ValueError("candidate quote quantity differs from replenishment line quantity")
                if requested_supplier and quote.get("supplier_id") != requested_supplier:
                    raise ValueError("candidate quote is outside the requested supplier scope")
                if max_lead_days is not None and (
                    type(max_lead_days) is not int or type(quote.get("lead_days")) is not int
                    or quote["lead_days"] > max_lead_days
                ):
                    raise ValueError("candidate quote is outside the requested lead-time filter")
                if cents <= 0 or quantity < 0 or total != cents * quantity:
                    raise ValueError("candidate quote total does not match quantity and unit price")
                if dataset.as_of:
                    try:
                        valid_until = datetime.fromisoformat(_text(quote.get("valid_until")).replace("Z", "+00:00"))
                        observed_at = datetime.fromisoformat(dataset.as_of.replace("Z", "+00:00"))
                    except ValueError as exc:
                        raise ValueError("candidate quote validity or source time is invalid") from exc
                    if valid_until <= observed_at:
                        continue
                rows.append([
                    _text(line.get("part_id")), _text(line.get("warehouse_id")),
                    unit, _text(quote.get("supplier_name"), _text(quote.get("supplier_id"))),
                    quote.get("lead_days"), cents, quantity, total,
                ])
                chosen_ids.add(quote_id)
        if not rows:
            raise ValueError("the authorized result contains no valid quote rows")
        if chosen_ids != source_quote_ids:
            # Source refs may include inventory and expired/filtered quote records; only
            # require each emitted quote to resolve, never fabricate a quote reference.
            if not chosen_ids.issubset(source_quote_ids):
                raise ValueError("candidate quote source references do not match the query")
        recommendations = []
        for line in lines:
            recommended = _text(line.get("recommended_quote_id")) if isinstance(line, dict) else ""
            if recommended and recommended in chosen_ids:
                recommendations.append(f"{_text(line.get('part_id'))}推荐报价 {recommended}。")
        missing = sorted({str(field) for line in lines if isinstance(line, dict) for field in (line.get("missing_fields") or [])})
        return AnalysisResult(
            title="补货报价分析", scope=scope, as_of=as_of, source_refs=sources,
            columns=["物料", "仓库", "单位", "供应商", "交期（天）", "单价（分/单位）", "数量", "总额（分）"],
            rows=rows, summary=f"根据 {len(rows)} 条来源报价生成；所有金额保留整数分。",
            recommendations=recommendations, missing_fields=missing,
            numeric_columns=[4, 5, 6, 7],
        )

    if dataset.tool_name in {"inventory_page", "inventory_warning"} and isinstance(data, dict):
        records = data.get("records")
        if not isinstance(records, list):
            raise ValueError("inventory query has no structured records")
        rows = []
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("inventory record is malformed")
            unit = record.get("unit")
            if not isinstance(unit, str) or not unit.strip():
                raise ValueError("inventory record is missing its concrete business unit")
            rows.append([_text(record.get("part_id")), _text(record.get("warehouse_id")), unit,
                         record.get("on_hand"), record.get("available"), record.get("inbound"),
                         record.get("shortage"), bool(record.get("warning"))])
        return AnalysisResult(
            title="库存分析", scope=scope, as_of=as_of, source_refs=sources,
            columns=["物料", "仓库", "单位", "在手", "可用", "在途", "缺口", "预警"],
            rows=rows, summary=f"查询范围内返回 {len(rows)} 条库存记录。",
            numeric_columns=[3, 4, 5, 6],
        )

    if dataset.tool_name == "quote_list" and isinstance(data, dict):
        records = data.get("records")
        if not isinstance(records, list):
            raise ValueError("quote query has no structured records")
        rows = []
        valid_ids = set()
        for quote in records:
            if not isinstance(quote, dict) or quote.get("is_valid") is not True:
                continue
            if type(quote.get("unit_price_cents")) is not int or type(quote.get("lead_days")) is not int:
                raise ValueError("quote price and lead time must be numeric")
            part_unit = quote.get("part_unit")
            if not isinstance(part_unit, str) or not part_unit.strip():
                raise ValueError("quote record is missing its concrete business unit")
            rows.append([_text(quote.get("part_id")), _text(quote.get("part_name")), part_unit,
                         _text(quote.get("supplier_id")), _text(quote.get("supplier_name")),
                         quote["unit_price_cents"], quote["lead_days"]])
            if quote.get("id"):
                valid_ids.add(str(quote["id"]))
        if not rows:
            raise ValueError("the authorized query contains no valid quotes")
        if not valid_ids.issubset({ref["id"] for ref in sources if ref.get("entity") == "quote"}):
            raise ValueError("quote rows are not bound to their source references")
        return AnalysisResult(
            title="有效报价分析", scope=scope, as_of=as_of, source_refs=sources,
            columns=["物料编号", "物料名称", "单位", "供应商编号", "供应商", "单价（分/单位）", "交期（天）"],
            rows=rows, summary=f"按来源查询时间筛选后共 {len(rows)} 条有效报价。",
            numeric_columns=[5, 6],
        )

    raise ValueError(f"formal artifacts are unsupported for source tool {dataset.tool_name}")


def build_dataset_chart(dataset: AuthorizedDataset, kind: str) -> ChartSpec:
    sources = _sources(dataset)
    data = dataset.data
    if kind == "bar" and dataset.tool_name == "replenishment_preview" and isinstance(data, dict):
        labels, cents = [], []
        source_quote_ids = {ref["id"] for ref in sources if ref.get("entity") == "quote"}
        for line in data.get("lines", []):
            if not isinstance(line, dict):
                continue
            for quote in line.get("candidate_quotes", []):
                if not isinstance(quote, dict) or quote.get("quote_id") not in source_quote_ids:
                    continue
                unit_price, quantity, total = quote.get("unit_price_cents"), quote.get("suggested_quantity"), quote.get("line_total_cents")
                if any(type(value) is not int for value in (unit_price, quantity, total)) or total != unit_price * quantity:
                    raise ValueError("candidate quote total does not match authorized facts")
                labels.append(f"{line.get('part_id')}/{quote.get('supplier_id')}")
                cents.append(total)
        if not cents:
            raise ValueError("no source-bound quote amounts are available for a bar chart")
        return build_chart_spec("bar", {"title": "有效报价总额比较", "labels": labels,
                                          "series": [{"name": "总额", "values_cents": cents}]}, sources)
    if kind == "pie" and dataset.tool_name in {"inventory_page", "inventory_warning"} and isinstance(data, dict):
        records = data.get("records")
        if not isinstance(records, list) or not records:
            raise ValueError("inventory chart needs at least one record")
        warning = sum(1 for record in records if isinstance(record, dict) and record.get("warning") is True)
        normal = sum(1 for record in records if isinstance(record, dict) and record.get("warning") is False)
        return build_chart_spec("pie", {"title": "库存预警占比", "labels": ["预警", "未预警"],
                                          "series": [{"name": "库存记录", "values": [warning, normal]}]}, sources)
    if kind == "line" and dataset.tool_name == "order_page" and isinstance(data, dict):
        records = data.get("records")
        if not isinstance(records, list):
            raise ValueError("order history has no records")
        by_day: dict[str, int] = {}
        for order in records:
            if not isinstance(order, dict) or not order.get("created_at"):
                raise ValueError("order history is missing a creation timestamp")
            timestamp = datetime.fromisoformat(str(order["created_at"]).replace("Z", "+00:00"))
            day = timestamp.date().isoformat()
            by_day[day] = by_day.get(day, 0) + sum(int(item.get("quantity", 0)) for item in order.get("items", []))
        labels = sorted(by_day)
        if len(labels) < 2:
            raise ValueError("line chart requires at least two source dates")
        return build_chart_spec("line", {"title": "按日采购数量", "labels": labels,
                                          "series": [{"name": "采购件数", "values": [by_day[day] for day in labels]}]}, sources)
    raise ValueError(f"{kind} chart is unsupported for source tool {dataset.tool_name}")


class AnalysisArtifactService:
    def __init__(self, sandbox: SandboxPort, artifacts: ArtifactService, runs: Any) -> None:
        self._sandbox, self._artifacts, self._runs = sandbox, artifacts, runs

    async def generate_report(self, dataset: AuthorizedDataset, format: str, ctx: RequestContext):
        result = build_analysis_result(dataset)
        spec = build_report_spec(format, result)
        filename = f"analysis-{uuid4().hex[:12]}.{format}"
        output = CollectedOutput(filename=filename, content=spec.content, mime=spec.mime,
                                 kind=format, source_refs=_sources(dataset))
        return await self._register(output, ctx)

    async def generate_chart(self, dataset: AuthorizedDataset, kind: str, ctx: RequestContext,
                             budget: RunBudget | None = None):
        spec = build_dataset_chart(dataset, kind)
        content = await render_chart_in_sandbox(spec, self._sandbox, ctx, budget)
        output = CollectedOutput(filename=f"analysis-{uuid4().hex[:12]}.png", content=content,
                                 mime="image/png", kind="png", source_refs=_sources(dataset))
        return await self._register(output, ctx)

    async def _register(self, output: CollectedOutput, ctx: RequestContext):
        artifact = await self._artifacts.register(output, ctx)
        await self._runs.append_event(ctx.run_id, "artifact_ready", {
            "artifact_id": artifact.id, "kind": artifact.kind, "filename": artifact.filename,
            "mime": artifact.mime, "source_refs": artifact.source_refs,
        }, ctx)
        return artifact
