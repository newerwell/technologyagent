"""Render constrained answer facts from complete, scoped server evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
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


def _unique_value(facts: list[dict[str, Any]], field: str) -> Any:
    candidates = {fact.get("value") for fact in facts if fact.get("field") == field}
    return next(iter(candidates)) if len(candidates) == 1 else None


def _snapshot_key(value: str | None) -> tuple[int, str]:
    if not value:
        return (0, "")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (1, parsed.astimezone(timezone.utc).isoformat())
    except ValueError:
        return (0, value)


def _render_target_gaps(state: dict[str, Any], constraints: dict[str, Any], queries: list[QueryEvidence]) -> str | None:
    groups = _complete_groups(queries, constraints, {"inventory_page"})
    if not groups:
        return None
    # Keep one newest complete snapshot per requested warehouse/filter scope;
    # selecting one global newest group silently drops other warehouses.
    newest: dict[str, list[QueryEvidence]] = {}
    for group in groups:
        first = group[0]
        args = {key: value for key, value in first.arguments.items() if key not in {"page", "page_size"}}
        scope_key = str(sorted(args.items()))
        prior = newest.get(scope_key)
        stamp = max((_snapshot_key(item.as_of) for item in group), default=(0, ""))
        prior_stamp = max((_snapshot_key(item.as_of) for item in prior or []), default=(0, ""))
        if prior is None or stamp > prior_stamp:
            newest[scope_key] = group
    selected_groups = list(newest.values())
    facts = list(state.get("evidence") or [])
    requested_parts = {str(value).upper() for value in constraints.get("part_ids") or []}
    requested_warehouses = {str(value).upper() for value in constraints.get("warehouse_ids") or []}
    rendered: dict[tuple[str, str], set[int]] = defaultdict(set)
    call_ids = {query.call_id for group in selected_groups for query in group}
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
    query_warehouses = {
        str(query.arguments.get("warehouse_id") or "").upper()
        for group in selected_groups for query in group if query.arguments.get("warehouse_id")
    }
    empty_warehouses = {
        str(group[0].arguments.get("warehouse_id") or "").upper()
        for group in selected_groups if group and group[0].total == 0 and group[0].arguments.get("warehouse_id")
    }
    if not rendered and not empty_warehouses:
        return None
    if any(len(values) != 1 for values in rendered.values()):
        return None
    if requested_warehouses and not requested_warehouses.issubset(query_warehouses):
        return None
    if requested_warehouses and requested_parts:
        missing_pairs = {(warehouse, part) for warehouse in requested_warehouses - empty_warehouses
                         for part in requested_parts} - rendered.keys()
        if missing_pairs:
            return None
    elif requested_parts and not requested_parts.issubset({part for _warehouse, part in rendered}):
        return None
    positives = sorted((warehouse, part, next(iter(values))) for (warehouse, part), values in rendered.items()
                       if next(iter(values)) > 0)
    if not positives:
        scope = "、".join(sorted(requested_warehouses or query_warehouses)) or "已完整查询范围"
        answer = f"{scope}未发现正的目标库存缺口。"
    else:
        unit_by_scope: dict[tuple[str, str], set[str]] = defaultdict(set)
        for fact in facts:
            if fact.get("field") == "shortage" and str(fact.get("call_id")) in call_ids:
                unit_by_scope[(str(fact.get("warehouse_id") or "").upper(),
                               str(fact.get("part_id") or "").upper())].add(str(fact.get("unit") or "count"))
        pieces = []
        for warehouse, part, shortage in positives:
            units = unit_by_scope.get((warehouse, part), {"count"})
            if len(units) != 1:
                return None
            unit = next(iter(units))
            if unit == "count":
                unit = "件"
            pieces.append(f"{warehouse}的{part}目标库存缺口为{shortage}{unit}")
        answer = "；".join(pieces) + "。"
    if empty_warehouses:
        answer += "空仓范围：" + "、".join(sorted(empty_warehouses)) + "未返回库存记录，无法核对该仓目标缺口。"
    answer += "补货判定采用目标库存缺口口径，与安全库存预警口径不同。"
    sources = {query.data_source for group in selected_groups for query in group}
    observations = {query.as_of for group in selected_groups for query in group if query.as_of}
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
            scoped_facts = [fact for fact in facts if _scoped(fact, part=part, warehouse=query_warehouse)]
            unit_values = {fact.get("value") for fact in scoped_facts if fact.get("field") == "unit"}
            if len(unit_values) > 1 or any(not isinstance(value, str) or not value.strip() for value in unit_values):
                continue
            if not unit_values:
                answers.add(
                    f"服务端补货预览推荐报价{quote_id}/{supplier}：交期{values['lead_days']}天，"
                    f"符合用户提出的{constraints['max_lead_days']}天内到货条件。\n"
                    f"数据源：{query.data_source}；观察时间：{query.as_of or '未提供'}。"
                )
                continue
            unit = next(iter(unit_values))
            inventory_fields = ("on_hand", "reserved", "inbound", "available", "projected", "shortage",
                                "warning", "safety_stock", "target_stock")
            inventory = {field: _unique_value(scoped_facts, field) for field in inventory_fields}
            has_inventory_core = all(inventory[field] is not None for field in ("available", "projected", "shortage", "warning"))
            if has_inventory_core and any(isinstance(inventory[field], bool) or not isinstance(inventory[field], int)
                                          for field in ("available", "projected", "shortage")):
                has_inventory_core = False
            inventory_summary = ""
            quantity_relation = ""
            if has_inventory_core:
                unit_text = f"{unit}"
                inventory_summary = (
                    f"{part}/{query_warehouse}库存快照："
                    + (f"在手{inventory['on_hand']}{unit_text}，" if isinstance(inventory["on_hand"], int) else "")
                    + (f"预留{inventory['reserved']}{unit_text}，" if isinstance(inventory["reserved"], int) else "")
                    + (f"在途{inventory['inbound']}{unit_text}，" if isinstance(inventory["inbound"], int) else "")
                    + f"可用{inventory['available']}{unit_text}，预计可用{inventory['projected']}{unit_text}，"
                    + (f"安全库存{inventory['safety_stock']}{unit_text}，" if isinstance(inventory["safety_stock"], int) else "")
                    + (f"目标库存{inventory['target_stock']}{unit_text}，" if isinstance(inventory["target_stock"], int) else "")
                    + f"目标缺口{inventory['shortage']}{unit_text}，"
                    + ("安全预警已触发。" if inventory["warning"] else "未触发安全预警。")
                )
                quantity_relation = ("建议数量与目标缺口数量一致。" if values["quantity"] == inventory["shortage"]
                                     else "建议数量由服务端补货预览返回。")

            eligible_quotes: list[str] = []
            part_quote_queries = [item for item in queries if item.tool_name == "quote_list"
                                  and query_scope_complete([item])
                                  and (str(item.arguments.get("part_id") or "").upper() == part
                                       or part in {str(value).upper() for value in item.arguments.get("part_ids", [])})]
            quote_ids = {record_id for item in part_quote_queries for record_id in item.record_ids}
            for quote_record_id in sorted(quote_ids):
                quote_row = [fact for fact in facts
                             if str(fact.get("id") or fact.get("quote_id") or "") == quote_record_id
                             and str(fact.get("part_id") or "").upper() == part
                             and str(fact.get("call_id")) in {item.call_id for item in part_quote_queries}]
                supplier_ids = {str(fact.get("supplier_id") or "").upper() for fact in quote_row if fact.get("supplier_id")}
                supplier_names = {str(fact.get("value")) for fact in quote_row
                                  if fact.get("field") == "supplier_name" and fact.get("value")}
                validity = {fact.get("value") for fact in quote_row if fact.get("field") == "is_valid"}
                if len(supplier_ids) != 1 or len(supplier_names) > 1 or len(validity) != 1:
                    continue
                supplier_id = next(iter(supplier_ids))
                supplier_label = next(iter(supplier_names)) if supplier_names else supplier_id
                is_valid = next(iter(validity))
                if is_valid is False:
                    eligible_quotes.append(f"{part}/{supplier_id}报价{quote_record_id}/{supplier_label}服务端状态无效")
                    continue
                if is_valid is not True or quote_record_id == quote_id:
                    continue
                lead_values = {fact.get("value") for fact in quote_row if fact.get("field") == "lead_days"}
                price_values = {fact.get("value") for fact in quote_row if fact.get("field") == "unit_price_cents"}
                if len(lead_values) != 1 or len(price_values) != 1:
                    continue
                lead_days, price_cents = next(iter(lead_values)), next(iter(price_values))
                if not isinstance(lead_days, int) or isinstance(lead_days, bool) or not isinstance(price_cents, int) or isinstance(price_cents, bool):
                    continue
                if lead_days <= int(constraints["max_lead_days"]):
                    eligible_quotes.append(
                        f"{part}/{supplier_id}报价{quote_record_id}/{supplier_label}交期{lead_days}天、单价{Decimal(price_cents) / 100:.2f}元/{unit}，满足交期上限"
                    )
                else:
                    eligible_quotes.append(
                        f"{part}/{supplier_id}报价{quote_record_id}/{supplier_label}交期{lead_days}天、单价{Decimal(price_cents) / 100:.2f}元/{unit}，超出{constraints['max_lead_days']}天上限"
                    )
            comparison = "报价对比：" + "；".join(eligible_quotes) + "。" if eligible_quotes else ""
            artifact_values = {(fact.get("value")) for fact in facts if fact.get("entity") == "artifact"
                               and fact.get("field") == "filename" and fact.get("value")}
            artifact_summary = "已生成分析报告文件：" + "、".join(sorted(str(value) for value in artifact_values)) + "。" if artifact_values else ""
            rendered = (
                f"范围：{part}/{query_warehouse}；原始筛选：{part}/{query_warehouse}交期不超过{constraints['max_lead_days']}天。"
                 f"{inventory_summary}{quantity_relation}"
                 f"服务端补货预览推荐报价{quote_id}：{part}/{query_warehouse}/{supplier}交期{values['lead_days']}天；"
                 f"{part}/{query_warehouse}数量{values['quantity']}{unit}；"
                 f"{part}/{query_warehouse}/{supplier}单价{Decimal(values['unit_price_cents']) / 100:.2f}元/{unit}；"
                 f"{part}/{query_warehouse}/{supplier}总额{Decimal(values['total_cents']) / 100:.2f}元；"
                 f"{part}/{query_warehouse}符合用户提出的{constraints['max_lead_days']}天内到货条件。"
                 f"{comparison}{artifact_summary}\n"
                 if has_inventory_core or part_quote_queries or artifact_summary else
                 f"服务推荐报价{quote_id}：{part}/{query_warehouse}/{supplier}交期{values['lead_days']}天；"
                 f"{part}/{query_warehouse}数量{values['quantity']}{unit}；"
                 f"{part}/{query_warehouse}/{supplier}单价{Decimal(values['unit_price_cents']) / 100:.2f}元/{unit}；"
                 f"{part}/{query_warehouse}总额{Decimal(values['total_cents']) / 100:.2f}元；"
                 f"{part}/{query_warehouse}符合用户提出的{constraints['max_lead_days']}天内到货条件。\n")
            rendered += f"数据源：{query.data_source}；观察时间：{query.as_of or '未提供'}。"
            if has_inventory_core:
                rendered += "库存字段是该范围的服务端事实；推荐报价是结合本轮交期条件的结论，仅反映本次查询快照，库存和报价可能随时间变化。"
            answers.add(rendered)
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


def _render_single_part_shortage(state: dict[str, Any], constraints: dict[str, Any],
                                 queries: list[QueryEvidence]) -> str | None:
    parts = {str(value).upper() for value in constraints.get("part_ids") or []}
    warehouses = {str(value).upper() for value in constraints.get("warehouse_ids") or []}
    if len(parts) != 1 or not warehouses:
        return None
    part = next(iter(parts))
    scoped_call_ids = {
        query.call_id for query in queries
        if query.tool_name in {"replenishment_preview", "inventory_page"}
        and (query.tool_name == "inventory_page"
             or part in {str(value).upper() for value in query.arguments.get("part_ids") or []})
        and str(query.arguments.get("warehouse_id") or "").upper() in warehouses
    }
    if not scoped_call_ids:
        return None
    facts = [fact for fact in state.get("evidence") or []
             if fact.get("field") == "shortage" and str(fact.get("call_id") or "") in scoped_call_ids
             and str(fact.get("part_id") or "").upper() == part
             and str(fact.get("warehouse_id") or "").upper() in warehouses
             and isinstance(fact.get("value"), int) and not isinstance(fact.get("value"), bool)
             and fact.get("value") >= 0]
    lines = []
    source = None
    observations = []
    for warehouse in sorted(warehouses):
        candidates = [fact for fact in facts if str(fact.get("warehouse_id") or "").upper() == warehouse]
        if not candidates:
            return None
        newest = max((_snapshot_key(str(fact.get("as_of") or "")) for fact in candidates), default=(0, ""))
        current = [fact for fact in candidates if _snapshot_key(str(fact.get("as_of") or "")) == newest]
        values = {fact.get("value") for fact in current}
        units = {str(fact.get("unit") or "count") for fact in current}
        sources = {str(fact.get("data_source") or "unknown") for fact in current}
        timestamps = {str(fact.get("as_of") or "") for fact in current}
        if len(values) != 1 or len(units) != 1 or len(sources) != 1 or len(timestamps) != 1:
            return None
        unit = next(iter(units))
        if unit == "count":
            unit = "件"
        source = next(iter(sources))
        observations.extend(timestamps)
        lines.append(f"{warehouse}仓库的{part}目标库存缺口为{next(iter(values))}{unit}")
    if not source or len(set(observations)) != 1:
        return None
    return f"{'；'.join(lines)}。\n数据源：{source}；观察时间：{observations[0]}。"


def render_verified_core_facts(state: dict[str, Any]) -> str | None:
    """Provide a server-rendered factual core for fully constrained P03 answers.

    Returning ``None`` means the normal reviewer must decide whether evidence is
    sufficient; this function never fills a missing source, scope, or field.
    """
    constraints = state.get("request_constraints") or {}
    queries = _queries(state)
    if constraints.get("intent") == "single_part_shortage":
        return _render_single_part_shortage(state, constraints, queries)
    if constraints.get("intent") == "target_replenishment":
        return _render_target_gaps(state, constraints, queries)
    if constraints.get("intent") == "supplier_recommendation":
        if constraints.get("max_lead_days") is not None:
            return _render_supplier_recommendation(state, constraints, queries)
        return _render_no_valid_quotes(state, constraints, queries)
    return None
