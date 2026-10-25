"""P08 business tool dispatcher. It delegates to the shared services and mutations."""

from __future__ import annotations

from typing import Any

from backend.app.contracts.common import AppError, PageQuery, RequestContext


async def dispatch(runtime: Any, name: str, payload: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    module = ("suppliers" if name.startswith("supplier_") else "parts" if name.startswith("part_")
             else "inventory" if name.startswith("inventory_") else "orders" if name.startswith("order_") else None)
    provider = runtime.business_providers.get(module) if module else None
    if provider is not None:
        source = provider.capabilities.data_source
        if source == "remote_erp":
            if name in {"supplier_create", "supplier_update_status", "part_create", "order_update", "order_update_status",
                        "inventory_inbound", "inventory_outbound"}:
                if name not in provider.write_actions:
                    raise AppError("UNSUPPORTED_OPERATION", "remote ERP write capability has not been verified", 405)
                approval_id = payload.get("approval_id")
                if not approval_id:
                    raise AppError("APPROVAL_REQUIRED", "prepare and approve this remote operation first", 403)
                return await provider.mutate(name, payload, approved=True,
                                             correlation_id=payload.get("idempotency_key"))
            raw = await provider.query(name, **payload)
            return _map_remote(name, raw, payload)
        if source == "local_snapshot" and name in {"supplier_create", "supplier_update_status", "part_create",
            "order_update", "order_update_status", "inventory_inbound", "inventory_outbound"}:
            raise AppError("UNSUPPORTED_OPERATION", "local snapshot provider is read-only", 405)
    catalog, inventory = runtime.catalog.catalog, runtime.inventory.inventory
    page = PageQuery(page=int(payload.get("page", 1)), page_size=int(payload.get("page_size", 20)))
    if name in {"supplier_page", "supplier_query"}:
        result = await catalog.search_suppliers(payload.get("name"), page)
        return result.model_dump(mode="json")
    if name == "supplier_get":
        return (await catalog.get_supplier(payload["supplier_id"])).model_dump(mode="json")
    if name in {"part_page", "part_search"}:
        result = await catalog.search_parts(payload.get("name"), page)
        return result.model_dump(mode="json")
    if name in {"part_query", "part_get"}:
        return (await catalog.get_part(payload["part_id"])).model_dump(mode="json")
    if name == "part_by_supplier":
        quotes = await catalog.page_quotes(None, None, payload["supplier_id"], page)
        parts = {part.id: part for part in await catalog._repository.list_parts([q.part_id for q in quotes.records])}
        return {**quotes.model_dump(mode="json"), "records": [parts[q.part_id].model_dump(mode="json") for q in quotes.records if q.part_id in parts]}
    if name in {"order_page", "order_search_details", "order_statistics"}:
        if name == "order_statistics":
            stages = [{"$match": {"owner_id": ctx.owner_id}}, {"$group": {
                "_id": None, "total": {"$sum": 1}, "total_cents": {"$sum": "$total_cents"},
                "submitted": {"$sum": {"$cond": [{"$eq": ["$status", "submitted"]}, 1, 0]}},
                "shipped": {"$sum": {"$cond": [{"$eq": ["$status", "shipped"]}, 1, 0]}},
                "received": {"$sum": {"$cond": [{"$eq": ["$status", "received"]}, 1, 0]}},
                "completed": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
                "cancelled": {"$sum": {"$cond": [{"$eq": ["$status", "cancelled"]}, 1, 0]}},
            }}]
            cursor = await runtime.mongo.db["orders"].aggregate(stages)
            rows = [item async for item in cursor]
            summary = rows[0] if rows else {"total": 0, "total_cents": 0, "submitted": 0, "shipped": 0, "received": 0, "completed": 0, "cancelled": 0}
            return {"total": summary["total"], "total_cents": summary["total_cents"],
                    "by_status": {status: summary[status]
                                  for status in ("submitted", "shipped", "received", "completed", "cancelled")},
                    "scope_complete": True}
        result = await (runtime.orders.search_details(ctx.owner_id, status=payload.get("status"),
            supplier_id=payload.get("supplier_id"), part_id=payload.get("part_id"), query=page)
            if name == "order_search_details" else runtime.orders.page(ctx.owner_id, page))
        return result.model_dump(mode="json")
    if name == "order_get":
        order = await runtime.orders.get(ctx.owner_id, payload["order_id"])
        if order is None:
            raise AppError("NOT_FOUND", "order not found", 404)
        return order.model_dump(mode="json")
    if name in {"inventory_page", "inventory_warning"}:
        from backend.app.contracts.domain import InventoryQuery
        query = InventoryQuery(warehouse_id=payload.get("warehouse_id"), part_name=payload.get("part_name"),
                               page=page.page, page_size=page.page_size)
        result = await (inventory.page(query) if name == "inventory_page" else inventory.warnings(query))
        return result.model_dump(mode="json")
    if name in {"inventory_get", "inventory_check"}:
        return (await inventory.get(payload["inventory_id"])).model_dump(mode="json")
    if name == "mutation_prepare":
        action = payload.get("action")
        if action not in runtime.business_mutations.ALLOWED | {"inventory_receive"}:
            raise AppError("UNSUPPORTED_OPERATION", "mutation action is not supported", 405)
        proposal = await runtime.approvals.request_mutation(action, payload.get("payload", {}), ctx)
        return proposal
    if name == "inventory_inbound":
        if payload.get("order_id") and payload.get("receipt_id"):
            if not payload.get("approval_id") or not payload.get("idempotency_key"):
                raise AppError("APPROVAL_REQUIRED", "purchase receipt requires an approved proposal", 403)
            return await runtime.inventory_mutations.receive(order_id=payload["order_id"],
                receipt_id=payload["receipt_id"], warehouse_id=payload["warehouse_id"],
                items=payload["items"], approval_id=payload["approval_id"],
                idempotency_key=payload["idempotency_key"], ctx=ctx)
        return await _execute(runtime, name, payload, ctx)
    if name == "inventory_outbound":
        return await _execute(runtime, name, payload, ctx)
    if name in {"supplier_create", "supplier_update_status", "part_create", "order_update_status", "order_update"}:
        return await _execute(runtime, name, payload, ctx)
    raise AppError("UNSUPPORTED_OPERATION", f"unsupported P08 tool: {name}", 405)


async def _execute(runtime: Any, name: str, payload: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    approval_id, key = payload.get("approval_id"), payload.get("idempotency_key")
    if not approval_id or not key:
        raise AppError("APPROVAL_REQUIRED", "prepare and approve this operation before execution", 403)
    return await runtime.business_mutations.execute(approval_id, key, ctx, expected_action=name)


def _map_remote(name: str, raw: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    from backend.app.integrations.erp.mappings import map_inventory, map_order, map_part, map_supplier, normalize_page
    mapper = (map_supplier if name.startswith("supplier_") else map_part if name.startswith("part_")
              else map_inventory if name.startswith("inventory_") else map_order if name.startswith("order_") else None)
    if mapper is None:
        return raw
    if "records" in raw or "data" in raw:
        page = normalize_page(raw, page=int(payload.get("page", 1)), page_size=int(payload.get("page_size", 20)))
        return {"records": [mapper(row) for row in page.records], "total": page.total,
                "page": page.page, "page_size": page.page_size, "scope_complete": page.complete,
                "integrity_warning": page.warning}
    return mapper(raw)
