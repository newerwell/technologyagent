"""Render constrained answer facts from complete, scoped server evidence."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from backend.app.agent.harness import query_matches_constraints, query_scope_complete
from backend.app.contracts.workflow import QueryEvidence


def _queries(state: dict[str, Any]) -> list[QueryEvidence]:
    result: list[QueryEvidence] = []
    for item in state.get("plan") or []:
        raw = item if isinstance(item, dict) else item.model_dump(mode="json")
        for query in raw.get("query_evidence") or []:
            try:
                result.append(query if isinstance(query, QueryEvidence) else QueryEvidence.model_validate(query))
            except Exception:  # malformed or legacy evidence cannot authorize rendered claims
                continue
    return result


def _complete_groups(queries: list[QueryEvidence], constraints: dict[str, Any], names: set[str]) -> list[list[QueryEvidence]]:
    groups: dict[tuple[str, str, str], list[QueryEvidence]] = defaultdict(list)
    for query in queries:
        if query.tool_name not in names or not query_matches_constraints(query, constraints):
            continue
        args = {key: value for key, value in query.arguments.items() if key not in {"page", "page_size"}}
        groups[(query.tool_name, str(sorted(args.items())), str(query.as_of or ""))].append(query)
    return [group for group in groups.values() if query_scope_complete(group)]


def _scoped(fact: dict[str, Any], *, part: str | None = None, warehouse: str | None = None) -> bool:
    if part and str(fact.get("part_id") or "").upper() != part:
        return False
    if warehouse and str(fact.get("warehouse_id") or "").upper() != warehouse:
        return False
    return True


def _render_target_gaps(state: dict[str, Any], constraints: dict[str, Any], queries: list[QueryEvidence]) -> str | None:
    groups = _complete_groups(queries, constraints, {"inventory_page"})
    if not groups:
        return None
    group = max(groups, key=lambda values: max((item.as_of or "") for item in values))
    facts = list(state.get("evidence") or [])
    requested_parts = {str(value).upper() for value in constraints.get("part_ids") or []}
    requested_warehouses = {str(value).upper() for value in constraints.get("warehouse_ids") or []}
    rendered: dict[tuple[str, str], set[int]] = defaultdict(set)
    call_ids = {query.call_id for query in group}
    for fact in facts:
        if fact.get("field") != "shortage" or str(fact.get("call_id")) not in call_ids:
            continue
        part = str(fact.get("part_id") or "").upper()
        warehouse = str(fact.get("warehouse_id") or "").upper()
        value = fact.get("value")
        if (not part or not warehouse or (requested_parts and part not in requested_parts)
                or (requested_warehouses and warehouse not in requested_warehouses)
                or isinstance(value, bool) or not isinstance(value, int) or value < 0):
            continue
        rendered[(warehouse, part)].add(value)
    if not rendered:
        return None
    if any(len(values) != 1 for values in rendered.values()):
        return None
    positives = sorted((warehouse, part, next(iter(values))) for (warehouse, part), values in rendered.items()
                       if next(iter(values)) > 0)
    if not positives:
        scope = "、".join(sorted(requested_warehouses)) or "已完整查询范围"
        answer = f"{scope}未发现正的目标库存缺口。"
    else:
        answer = "；".join(
        f"{warehouse}的{part}目标库存缺口为{shortage}件"
        for warehouse, part, shortage in positives
        ) + "。"
    answer += "补货判定采用目标库存缺口口径，与安全库存预警口径不同。"
    sources = {query.data_source for query in group}
    observations = {query.as_of for query in group if query.as_of}
    if len(sources) != 1 or len(observations) != 1:
        return None
    return f"{answer}\n数据源：{next(iter(sources))}；观察时间：{next(iter(observations))}。"


def _render_supplier_recommendation(
    state: dict[str, Any], constraints: dict[str, Any], queries: list[QueryEvidence]
) -> str | None:
    matching = [query for query in queries if query.tool_name == "replenishment_preview"
                and query_matches_constraints(query, constraints)]
    if not matching:
        return None
    facts = list(state.get("evidence") or [])
    answers: set[str] = set()
    for query in matching:
        call_ids = {query.call_id}
        query_parts = {str(value).upper() for value in query.arguments.get("part_ids", [])}
        query_warehouse = str(query.arguments.get("warehouse_id") or "").upper()
        if not query_warehouse:
            continue
        quote_facts = [fact for fact in facts if str(fact.get("call_id")) in call_ids
                       and fact.get("field") == "recommended_quote_id"
                       and _scoped(fact, warehouse=query_warehouse)]
        for recommendation in quote_facts:
            part = str(recommendation.get("part_id") or "").upper()
            quote_id = str(recommendation.get("value") or "")
            if not part or not quote_id or (query_parts and part not in query_parts):
                continue
            quote_fact = next((fact for fact in facts if str(fact.get("call_id")) in call_ids
                               and fact.get("field") == "quote_id" and fact.get("value") == quote_id
                               and _scoped(fact, part=part, warehouse=query_warehouse)
                               and fact.get("supplier_id")), None)
            if not quote_fact:
                continue
            supplier = str(quote_fact["supplier_id"]).upper()
            scoped = [fact for fact in facts if str(fact.get("call_id")) in call_ids
                      and _scoped(fact, part=part, warehouse=query_warehouse)
                      and (not fact.get("supplier_id") or str(fact.get("supplier_id")).upper() == supplier)]
            values: dict[str, Any] = {}
            for field in ("lead_days", "quantity", "unit_price_cents", "total_cents"):
                candidates = {fact.get("value") for fact in scoped if fact.get("field") == field}
                if len(candidates) != 1:
                    values = {}
                    break
                values[field] = next(iter(candidates))
            if not values:
                continue
            if (values["lead_days"] > int(constraints["max_lead_days"])
                    or values["quantity"] <= 0 or values["unit_price_cents"] < 0 or values["total_cents"] < 0):
                continue
            answers.add(
                f"服务推荐报价{quote_id}：{part}/{query_warehouse}/{supplier}交期{values['lead_days']}天；"
                f"{part}/{query_warehouse}数量{values['quantity']}件；"
                f"{part}/{query_warehouse}/{supplier}单价{Decimal(values['unit_price_cents']) / 100:.2f}元；"
                f"{part}/{query_warehouse}总额{Decimal(values['total_cents']) / 100:.2f}元；"
                f"{part}/{query_warehouse}符合用户提出的{constraints['max_lead_days']}天内到货条件。\n"
                f"数据源：{query.data_source}；观察时间：{query.as_of or '未提供'}。"
            )
    if not answers:
        return None
    return "\n".join(sorted(answers))


def _render_no_valid_quotes(
    state: dict[str, Any], constraints: dict[str, Any], queries: list[QueryEvidence]
) -> str | None:
    groups = _complete_groups(queries, constraints, {"quote_list"})
    if not groups:
        return None
    facts = list(state.get("evidence") or [])
    parts: set[str] = set()
    selected_sources: set[str] = set()
    selected_observations: set[str] = set()
    requested_parts = {str(value).upper() for value in constraints.get("part_ids") or []}
    for group in groups:
        call_ids = {query.call_id for query in group}
        total = group[0].total
        records = [fact for fact in facts if str(fact.get("call_id")) in call_ids
                   and fact.get("field") == "is_valid" and isinstance(fact.get("value"), bool)
                   and (not requested_parts or str(fact.get("part_id") or "").upper() in requested_parts)]
        record_ids = {str(fact.get("id") or fact.get("record_id") or "") for fact in records}
        record_ids.discard("")
        if total is None or (total > 0 and (len(record_ids) < total or any(fact["value"] for fact in records))):
            continue
        group_parts = {
            str(query.arguments.get("part_id") or "").upper() for query in group
            if query.arguments.get("part_id")
        }
        group_parts |= {str(value).upper() for query in group for value in query.arguments.get("part_ids", [])}
        if requested_parts and not requested_parts.issubset(group_parts):
            continue
        parts.update(group_parts or requested_parts)
        selected_sources.update(query.data_source for query in group)
        selected_observations.update(query.as_of for query in group if query.as_of)
    if not parts or len(selected_sources) != 1 or len(selected_observations) != 1:
        return None
    answer = "；".join(f"{part}没有有效报价，无法判断最便宜的供应商" for part in sorted(parts)) + "。"
    return f"{answer}\n数据源：{next(iter(selected_sources))}；观察时间：{next(iter(selected_observations))}。"


def render_verified_core_facts(state: dict[str, Any]) -> str | None:
    """Provide a server-rendered factual core for fully constrained P03 answers.

    Returning ``None`` means the normal reviewer must decide whether evidence is
    sufficient; this function never fills a missing source, scope, or field.
    """
    constraints = state.get("request_constraints") or {}
    queries = _queries(state)
    if constraints.get("intent") == "target_replenishment":
        return _render_target_gaps(state, constraints, queries)
    if constraints.get("intent") == "supplier_recommendation":
        if constraints.get("max_lead_days") is not None:
            return _render_supplier_recommendation(state, constraints, queries)
        return _render_no_valid_quotes(state, constraints, queries)
    return None
