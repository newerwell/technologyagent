"""Strict deterministic checks for the P03 live-model acceptance manifest."""

from __future__ import annotations

import json
from typing import Any

from backend.app.agent.evidence import collect_evidence, validate_business_claims
from backend.app.ports.tools import ToolResult

READ_ONLY_TOOLS = {
    "inventory_page", "inventory_warning", "inventory_get", "supplier_query",
    "supplier_get", "part_search", "part_query", "quote_list", "replenishment_preview",
}


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def validate_live_run(events: list[dict[str, Any]], question_index: int) -> tuple[bool, list[str]]:
    errors: list[str] = []
    started = next((event for event in events if event.get("type") == "run_started"), None)
    finished = next((event for event in events if event.get("type") == "run_finished"), None)
    ended = next((event for event in events if event.get("type") == "stream_end"), None)
    if not started or started.get("payload", {}).get("model_mode") != "live":
        errors.append("run_started did not confirm live model mode")
    if not finished or finished.get("payload", {}).get("status") != "completed":
        errors.append("run did not finish completed")
    if not ended or ended.get("payload", {}).get("reason") != "completed":
        errors.append("stream_end did not confirm completed")
    if any(event.get("type") == "error" for event in events):
        errors.append("run emitted an error event")
    starts = [event.get("payload", {}) for event in events if event.get("type") == "tool_started"]
    finishes = {event.get("payload", {}).get("call_id"): event.get("payload", {}) for event in events if event.get("type") == "tool_finished"}
    if not starts:
        errors.append("run did not call a read-only tool")
    successful: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for call in starts:
        outcome = finishes.get(call.get("call_id"))
        if call.get("name") not in READ_ONLY_TOOLS or not outcome or outcome.get("status") != "success":
            continue
        try:
            data = json.loads(outcome.get("result_summary") or "{}")
        except (TypeError, ValueError):
            continue
        successful.append((call, data))
    if not successful:
        errors.append("no successful read-only tool result was recorded")
    answer = str((finished or {}).get("payload", {}).get("summary", ""))
    evidence = []
    for call, data in successful:
        evidence.extend(collect_evidence(
            str(call.get("name")), ToolResult(ok=True, data=data, call_id=str(call.get("call_id"))),
            call_id=str(call.get("call_id")), arguments=call.get("args_summary") or {},
        ))
    answer_check = validate_business_claims(answer, evidence)
    if not answer_check.passed:
        errors.append("final answer failed validation against successful tool facts")
    if question_index == 0:
        valid = any(
            call.get("args_summary", {}).get("warehouse_id") == "W01"
            and
            item.get("part_id") == "P001" and item.get("warehouse_id") == "W01" and item.get("shortage") == 55
            for call, data in successful for item in _walk(data)
        )
        if not valid:
            errors.append("successful result did not contain P001/W01 shortage=55")
        p001_aliases = {"P001"}
        for _call, data in successful:
            for record in _walk(data):
                if record.get("id") == "P001":
                    p001_aliases.update(str(record[key]) for key in ("code", "name") if record.get(key))
        answered = (
            any(alias in answer for alias in p001_aliases) and "W01" in answer
            and any(item.get("field") == "shortage" and item.get("value") == 55
                    and item.get("part_id") == "P001" and item.get("warehouse_id") == "W01"
                    for item in answer_check.cited_facts)
        )
        if not answered:
            errors.append("final answer did not answer P001/W01 shortage=55")
    elif question_index == 1:
        valid = any(
            call.get("name") == "replenishment_preview"
            and call.get("args_summary", {}).get("warehouse_id") == "W01"
            and call.get("args_summary", {}).get("part_ids") == ["P001"]
            and call.get("args_summary", {}).get("max_lead_days") == 7
            and any(
                line.get("part_id") == "P001" and line.get("warehouse_id") == "W01"
                and line.get("quantity") == 55 and line.get("total_cents") == 66000
                and any(quote.get("supplier_id") == "S01" and quote.get("lead_days") == 5
                        for quote in line.get("candidate_quotes", []))
                for line in data.get("lines", [])
            )
            for call, data in successful
        )
        if not valid:
            errors.append("successful 7-day preview did not match S01/5 days/55 units/66000 cents")
        cited = answer_check.cited_facts
        filter_is_verified = any(
            call.get("name") == "replenishment_preview"
            and call.get("args_summary", {}).get("max_lead_days") == 7
            for call, _data in successful
        )
        states_seven_day_scope = "7" in answer and any(term in answer for term in ("天", "日"))
        s01_aliases = {"S01"}
        for _call, data in successful:
            for record in _walk(data):
                if record.get("supplier_id") == "S01" and record.get("supplier_name"):
                    s01_aliases.add(str(record["supplier_name"]))
        answered = (
            any(alias in answer for alias in s01_aliases)
            and any(item.get("field") == "lead_days" and item.get("value") == 5 for item in cited)
            and filter_is_verified and states_seven_day_scope
        )
        if not answered:
            errors.append("final answer did not answer the 7-day supplier question with S01/5 days")
    elif question_index == 2:
        valid = any(
            call.get("name") == "quote_list"
            and call.get("args_summary", {}).get("part_id") == "P003"
            and bool(data.get("records"))
            and all(item.get("is_valid") is False for item in data.get("records", []))
            for call, data in successful
        )
        if not valid or "P003" not in answer or not any(word in answer for word in ("无", "缺", "没有")):
            errors.append("P003 result did not prove there is no valid quote")
    else:
        errors.append("unknown fixed question index")
    return not errors, errors
