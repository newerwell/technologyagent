"""Shared, fail-closed query path for remote provider reads."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from backend.app.contracts.common import AppError, Page, PageQuery
from backend.app.contracts.domain import InventoryView, Part, PurchaseOrder, Supplier
from backend.app.integrations.erp.mappings import (
    map_inventory,
    map_order,
    map_part,
    map_supplier,
)

_MAPPERS = {
    "supplier": (map_supplier, Supplier),
    "part": (map_part, Part),
    "inventory": (map_inventory, InventoryView),
    "order": (map_order, PurchaseOrder),
}
_MAX_PAGES = 100
_MAX_RECORDS = 10_000


class ProviderQueries:
    """Validate remote records and prove a complete page set before returning any page."""

    def __init__(self, *, max_query_seconds: float = 60.0) -> None:
        self._max_query_seconds = max_query_seconds

    async def page(self, provider: Any, operation: str, params: dict[str, Any], entity: str,
                   *, remaining_budget: float | None = None) -> Page[Any]:
        try:
            return await self._page(provider, operation, params, entity, remaining_budget=remaining_budget)
        except AppError:
            raise
        except TimeoutError as exc:
            raise AppError("DEPENDENCY_UNAVAILABLE", "remote provider read exceeded its budget", 503,
                           retryable=True) from exc
        except (ValueError, TypeError, ValidationError) as exc:
            raise AppError("REMOTE_DATA_INVALID", str(exc)[:300], 502) from exc
        except Exception as exc:
            raise AppError("DEPENDENCY_UNAVAILABLE", "remote provider read failed", 503,
                           retryable=True) from exc

    async def _page(self, provider: Any, operation: str, params: dict[str, Any], entity: str,
                    *, remaining_budget: float | None = None, return_all: bool = False) -> Page[Any] | list[Any]:
        query = PageQuery(page=params.get("page", 1), page_size=params.get("page_size", 20))
        mapper, model = self._mapper(entity)
        deadline = time.monotonic() + min(self._max_query_seconds,
                                          remaining_budget if remaining_budget is not None else self._max_query_seconds)
        filters = {key: value for key, value in params.items() if key not in {"page", "page_size"}}
        all_rows: list[Any] = []
        seen: set[str] = set()
        expected_total: int | None = None
        expected_pages: int | None = None
        for page_number in range(1, _MAX_PAGES + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("remote provider query budget exhausted during pagination")
            raw = await provider.query(operation, **filters, page=page_number,
                                      page_size=query.page_size, remaining_budget=remaining)
            rows, total, declared_page, declared_size, pages = self._page_envelope(raw)
            if (declared_page != page_number or declared_size != query.page_size
                    or total < 0 or pages < 0):
                raise ValueError("remote provider page metadata contradicts the request")
            calculated_pages = (total + query.page_size - 1) // query.page_size if total else 0
            if pages != calculated_pages:
                raise ValueError("remote provider pages contradict total and page_size")
            if pages >= _MAX_PAGES or total >= _MAX_RECORDS:
                raise ValueError("remote provider result reaches the completeness safety limit")
            if expected_total is None:
                expected_total, expected_pages = total, pages
            elif total != expected_total or pages != expected_pages:
                raise ValueError("remote provider pagination changed total/pages between pages")
            if page_number > pages:
                if pages != 0 or rows:
                    raise ValueError("remote provider returned an out-of-range page")
                break
            expected_count = min(query.page_size, total - (page_number - 1) * query.page_size)
            if len(rows) != expected_count:
                raise ValueError("remote provider page is incomplete or has an unexpected record count")
            for raw_row in rows:
                try:
                    self._check_raw_types(raw_row, entity)
                    mapped = mapper(raw_row)
                    missing = mapped.get("missing_fields", [])
                    if missing:
                        raise ValueError("missing required fields: " + ", ".join(missing))
                    record = model.model_validate(self._dto_input(mapped))
                except ValidationError as exc:
                    raise ValueError(f"remote {entity} DTO validation failed: {self._safe_validation(exc)}") from exc
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"remote {entity} record failed DTO validation: {exc}") from exc
                identity = getattr(record, "id", None)
                if not isinstance(identity, str) or not identity:
                    raise ValueError(f"remote {entity} record has no valid entity id")
                if identity in seen:
                    raise ValueError("remote provider returned duplicate entity identifiers")
                seen.add(identity)
                all_rows.append(record)
            if page_number == pages:
                break
        else:
            raise ValueError("remote provider pagination exceeds the page safety limit")

        if expected_total is None or len(all_rows) != expected_total:
            raise ValueError("remote provider pagination is incomplete")
        if query.page > max(expected_pages or 0, 1):
            raise ValueError("requested remote page is out of range")
        if return_all:
            return all_rows
        start = (query.page - 1) * query.page_size
        return Page(records=all_rows[start:start + query.page_size], total=expected_total,
                    page=query.page, page_size=query.page_size, pages=expected_pages or 0)

    async def all_records(self, provider: Any, operation: str, params: dict[str, Any], entity: str,
                          *, remaining_budget: float | None = None) -> list[Any]:
        try:
            return await self._page(provider, operation, {**params, "page": 1, "page_size": 100}, entity,
                                    remaining_budget=remaining_budget, return_all=True)
        except AppError:
            raise
        except TimeoutError as exc:
            raise AppError("DEPENDENCY_UNAVAILABLE", "remote provider read exceeded its budget", 503,
                           retryable=True) from exc
        except (ValueError, TypeError, ValidationError) as exc:
            raise AppError("REMOTE_DATA_INVALID", str(exc)[:300], 502) from exc
        except Exception as exc:
            raise AppError("DEPENDENCY_UNAVAILABLE", "remote provider read failed", 503,
                           retryable=True) from exc

    async def get(self, provider: Any, operation: str, params: dict[str, Any], entity: str,
                  *, remaining_budget: float | None = None) -> Any:
        try:
            return await self._get(provider, operation, params, entity, remaining_budget=remaining_budget)
        except AppError:
            raise
        except TimeoutError as exc:
            raise AppError("DEPENDENCY_UNAVAILABLE", "remote provider read exceeded its budget", 503,
                           retryable=True) from exc
        except (ValueError, TypeError, ValidationError) as exc:
            raise AppError("REMOTE_DATA_INVALID", str(exc)[:300], 502) from exc
        except Exception as exc:
            raise AppError("DEPENDENCY_UNAVAILABLE", "remote provider read failed", 503,
                           retryable=True) from exc

    async def _get(self, provider: Any, operation: str, params: dict[str, Any], entity: str,
                   *, remaining_budget: float | None = None) -> Any:
        mapper, model = self._mapper(entity)
        if remaining_budget is not None and remaining_budget <= 0:
            raise TimeoutError("remote provider query budget exhausted before request")
        raw = await provider.query(operation, **params, remaining_budget=remaining_budget)
        if not isinstance(raw, dict):
            raise TypeError("remote provider entity response must be an object")
        try:
            self._check_raw_types(raw, entity)
            mapped = mapper(raw)
            missing = mapped.get("missing_fields", [])
            if missing:
                raise ValueError("missing required fields: " + ", ".join(missing))
            return model.model_validate(self._dto_input(mapped))
        except ValidationError as exc:
            raise ValueError(f"remote {entity} DTO validation failed: {self._safe_validation(exc)}") from exc
        except (ValueError, TypeError) as exc:
            raise ValueError(f"remote {entity} record failed DTO validation: {exc}") from exc

    @staticmethod
    def _check_raw_types(raw: dict[str, Any], entity: str) -> None:
        def exact_integer(field: str, *aliases: str) -> None:
            value = next((raw[key] for key in (field, *aliases) if key in raw), None)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{field} must be an integer")

        if entity == "part":
            active = raw.get("active", raw.get("enabled"))
            if not isinstance(active, bool):
                raise ValueError("active must be a boolean")
        elif entity == "inventory":
            for field, aliases in (("on_hand", ("quantity", "stock_qty")), ("reserved", ("reserved_qty",)),
                                   ("inbound", ("inbound_qty",)), ("safety_stock", ()),
                                   ("target_stock", ()), ("version", ())):
                exact_integer(field, *aliases)
        elif entity == "order":
            exact_integer("version")
            if "total_cents" in raw:
                exact_integer("total_cents")
            for item in raw.get("items", raw.get("details", [])):
                if not isinstance(item, dict):
                    continue
                value = item.get("quantity", item.get("qty"))
                if not isinstance(value, int) or isinstance(value, bool):
                    raise TypeError("order item quantity must be an integer")
                if "received_qty" in item or "received_quantity" in item:
                    received = item.get("received_qty", item.get("received_quantity"))
                    if not isinstance(received, int) or isinstance(received, bool):
                        raise TypeError("received_qty must be an integer")

    @staticmethod
    def _safe_validation(exc: ValidationError) -> str:
        return "; ".join(f"{'.'.join(map(str, item.get('loc', ())))}: {item.get('msg', 'invalid value')}"
                          for item in exc.errors()[:5])

    @staticmethod
    def _dto_input(mapped: dict[str, Any]) -> dict[str, Any]:
        values = {key: value for key, value in mapped.items() if key not in {"missing_fields", "raw_status"}}
        items = values.get("items")
        if isinstance(items, list):
            clean_items = []
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    raise TypeError("order item must be an object")
                missing = item.get("missing_fields", [])
                if missing:
                    raise ValueError(f"order item {index} missing required fields: {', '.join(missing)}")
                clean_items.append({key: value for key, value in item.items() if key != "missing_fields"})
            values["items"] = clean_items
        return values

    @staticmethod
    def _mapper(entity: str):
        try:
            return _MAPPERS[entity]
        except KeyError as exc:
            raise ValueError(f"unsupported remote entity type: {entity}") from exc

    @staticmethod
    def _page_envelope(raw: Any) -> tuple[list[dict[str, Any]], int, int, int, int]:
        if not isinstance(raw, dict):
            raise TypeError("remote provider page response must be an object")
        rows = raw.get("records", raw.get("data"))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise TypeError("remote provider page records must be an array of objects")
        fields = ("total", "page", "page_size", "pages")
        if any(key not in raw for key in fields):
            missing = ", ".join(key for key in fields if key not in raw)
            raise ValueError(f"remote provider page is missing pagination metadata: {missing}")
        values = [raw[key] for key in fields]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("remote provider pagination metadata must be integers")
        return rows, raw["total"], raw["page"], raw["page_size"], raw["pages"]
