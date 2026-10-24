"""P04 草稿准备和编辑；草稿中的价格、总额与来源全部来自业务仓储。"""

from __future__ import annotations

from uuid import uuid4

from backend.app.contracts.common import AppError, Clock, ErrorCodes, RequestContext
from backend.app.contracts.domain import OrderDraft, OrderItem, ReplenishmentRequest
from backend.app.contracts.order_workflow import DraftPatch, DraftPrepareRequest
from backend.app.domain.orders import build_order_item, quote_snapshot, serialize_draft, validate_supplier
from backend.app.repositories.drafts import DraftRepository
from backend.app.repositories.mongo import MongoResources
from backend.app.services.replenishment import ReplenishmentService
from backend.app.repositories.catalog import CatalogRepository


class DraftService:
    def __init__(self, mongo: MongoResources, catalog: CatalogRepository,
                 replenishment: ReplenishmentService, clock: Clock) -> None:
        self._mongo = mongo
        self._catalog = catalog
        self._replenishment = replenishment
        self._clock = clock
        self._drafts = DraftRepository(mongo)

    async def prepare(self, request: DraftPrepareRequest, ctx: RequestContext) -> dict:
        missing = ["warehouse_id"] if request.warehouse_id is None else []
        if missing:
            return {"drafts": [], "missing_fields": missing}
        preview = await self._replenishment.preview(
            ReplenishmentRequest(
                part_ids=request.part_ids,
                warehouse_id=request.warehouse_id,
                max_lead_days=request.max_lead_days,
            ), ctx,
        )
        quotes = {quote.id: quote for quote in await self._catalog.list_quotes(request.part_ids)}
        supplier_ids: set[str] = set()
        grouped: dict[str, list[OrderItem]] = {}
        missing_fields: set[str] = set()
        for line in preview.lines:
            candidates = [candidate for candidate in line.candidate_quotes
                          if request.supplier_id is None or candidate.supplier_id == request.supplier_id]
            if not line.actionable or not candidates:
                missing_fields.update(line.missing_fields or ["valid_quote"])
                continue
            selected_candidate = next(
                (candidate for candidate in candidates if candidate.quote_id == line.recommended_quote_id),
                candidates[0],
            )
            quote = quotes.get(selected_candidate.quote_id)
            if quote is None:
                missing_fields.add("valid_quote")
                continue
            quantity = request.quantities.get(
                line.part_id, max(line.shortage, quote.min_order_qty)
            )
            item = build_order_item(line.part_id, quantity, quote)
            supplier_ids.add(quote.supplier_id)
            grouped.setdefault(quote.supplier_id, []).append(item)
        suppliers = {item.id: item for item in await self._catalog.list_suppliers(sorted(supplier_ids))}
        drafts = []
        now = self._clock.now()
        for supplier_id, items in grouped.items():
            supplier = suppliers.get(supplier_id)
            if supplier is None:
                missing_fields.add("supplier")
                continue
            validate_supplier(supplier)
            draft = OrderDraft(
                id=f"drf_{uuid4().hex}", owner_id=ctx.owner_id,
                supplier_id=supplier_id, warehouse_id=request.warehouse_id,
                items=items, total_cents=sum(item.line_total_cents for item in items),
                version=1, state="draft", source_refs=preview.source_refs,
                snapshot_versions=preview.snapshot_versions,
                quote_snapshots={item.quote_id: quote_snapshot(quotes[item.quote_id]) for item in items},
                created_at=now, updated_at=now,
            )
            await self._drafts.insert(draft)
            drafts.append(serialize_draft(draft))
        return {"drafts": drafts, "missing_fields": sorted(missing_fields)}

    async def get(self, draft_id: str, ctx: RequestContext) -> dict:
        draft = await self._drafts.get(ctx.owner_id, draft_id)
        if draft is None:
            raise AppError(ErrorCodes.NOT_FOUND, "draft not found", http_status=404)
        return serialize_draft(draft)

    async def list(self, ctx: RequestContext) -> list[dict]:
        return [serialize_draft(draft) for draft in await self._drafts.list_owner(ctx.owner_id)]

    async def patch(self, draft_id: str, patch: DraftPatch, ctx: RequestContext) -> dict:
        draft = await self._drafts.get(ctx.owner_id, draft_id)
        if draft is None:
            raise AppError(ErrorCodes.NOT_FOUND, "draft not found", http_status=404)
        if draft.version != patch.expected_version:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "draft version is stale", http_status=409)
        supplier_id = patch.supplier_id or draft.supplier_id
        warehouse_id = patch.warehouse_id or draft.warehouse_id
        quote_records = await self._catalog.list_quotes([item.part_id for item in patch.items])
        quotes = {quote.id: quote for quote in quote_records}
        suppliers = {item.id: item for item in await self._catalog.list_suppliers([supplier_id])}
        supplier = suppliers.get(supplier_id)
        if supplier is None:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "supplier not found", http_status=422)
        validate_supplier(supplier)
        quantities: dict[tuple[str, str], int] = {}
        for requested in patch.items:
            key = (requested.part_id, requested.quote_id)
            quantities[key] = quantities.get(key, 0) + requested.quantity
        items = []
        for (part_id, quote_id), quantity in quantities.items():
            quote = quotes.get(quote_id)
            if (quote is None or quote.part_id != part_id
                    or quote.supplier_id != supplier_id or quote.valid_until <= self._clock.now()
                    or quantity < quote.min_order_qty):
                raise AppError(ErrorCodes.VALIDATION_ERROR, "quote does not match part and supplier", http_status=422)
            items.append(build_order_item(part_id, quantity, quote))
        preview = await self._replenishment.preview(
            ReplenishmentRequest(
                part_ids=list(dict.fromkeys(item.part_id for item in patch.items)),
                warehouse_id=warehouse_id,
            ), ctx
        )
        if any("inventory" in line.missing_fields for line in preview.lines):
            raise AppError(ErrorCodes.VALIDATION_ERROR, "warehouse has no inventory record for this part", http_status=422)
        updated = draft.model_copy(update={
            "supplier_id": supplier_id, "warehouse_id": warehouse_id,
            "items": items, "total_cents": sum(item.line_total_cents for item in items),
            "version": draft.version + 1, "state": "draft", "updated_at": self._clock.now(),
            "snapshot_versions": preview.snapshot_versions, "source_refs": preview.source_refs,
            "quote_snapshots": {item.quote_id: quote_snapshot(quotes[item.quote_id]) for item in items},
        })
        async with self._mongo.transaction() as session:
            if not await self._drafts.replace_version(updated, patch.expected_version, session=session):
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "draft version is stale", http_status=409)
            await self._mongo.db["approvals"].update_many(
                {"owner_id": ctx.owner_id, "draft_id": draft_id, "status": "pending"},
                {"$set": {"status": "superseded", "updated_at": self._clock.now()}},
                session=session,
            )
        return serialize_draft(updated)
