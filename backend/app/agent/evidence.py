"""P03 工具依据收集与硬性结论检查；不宣称覆盖所有自然语言幻觉。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.app.ports.tools import ToolResult

_ORDER_CLAIM = re.compile(r"(已(?:经)?(?:下单|创建订单|提交订单)|订单已(?:创建|提交|成立))")
_NUMBER = re.compile(r"(缺口|可用|预计可用|单价|总额|金额)\s*[=:：]?\s*(\d+(?:\.\d+)?)")


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    passed: bool
    violations: list[str] = field(default_factory=list)


def _add(refs: list[dict[str, Any]], *, call_id: str, entity: str, ident: str, meta: dict[str, Any]) -> None:
    refs.append(
        {
            "call_id": call_id,
            "entity": entity,
            "id": ident,
            "data_source": meta.get("data_source", "local_seed"),
            "as_of": meta.get("as_of") or datetime.now().isoformat(),
        }
    )


def collect_evidence(name: str, result: ToolResult, *, call_id: str) -> list[dict[str, Any]]:
    if not result.ok or not isinstance(result.data, dict):
        return []
    refs: list[dict[str, Any]] = []
    data = result.data
    if name == "replenishment_preview":
        for ref in data.get("source_refs") or []:
            refs.append(
                {
                    "call_id": call_id,
                    "entity": ref.get("entity", "unknown"),
                    "id": ref.get("id", ""),
                    "data_source": ref.get("data_source", "local_seed"),
                    "as_of": ref.get("as_of"),
                }
            )
    elif name in {"inventory_page", "inventory_warning"}:
        for record in data.get("records") or []:
            _add(refs, call_id=call_id, entity="inventory", ident=str(record.get("id", "")), meta=result.meta)
    elif name == "inventory_get":
        _add(refs, call_id=call_id, entity="inventory", ident=str(data.get("id", "")), meta=result.meta)
    elif name in {"part_search", "part_query"}:
        records = data.get("records") if name == "part_search" else [data]
        for record in records or []:
            _add(refs, call_id=call_id, entity="part", ident=str(record.get("id", "")), meta=result.meta)
    elif name in {"supplier_query", "supplier_get"}:
        records = data.get("records") if name == "supplier_query" else [data]
        for record in records or []:
            _add(refs, call_id=call_id, entity="supplier", ident=str(record.get("id", "")), meta=result.meta)
    elif name == "quote_list":
        for record in data.get("records") or []:
            _add(refs, call_id=call_id, entity="quote", ident=str(record.get("id", "")), meta=result.meta)
    return [ref for ref in refs if ref["id"]]


def validate_business_claims(answer: str, evidence: list[dict[str, Any]]) -> ClaimCheck:
    violations: list[str] = []
    if _ORDER_CLAIM.search(answer):
        violations.append("P03 is read-only and cannot create or submit orders")
    if _NUMBER.search(answer) and not evidence:
        violations.append("numeric business claim has no tool source")
    return ClaimCheck(passed=not violations, violations=violations)
