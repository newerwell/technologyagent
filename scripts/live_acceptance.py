"""Strict deterministic checks for the P03 live-model acceptance manifest."""

from __future__ import annotations

import json
import re
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


def _has_complete_pages(calls: list[tuple[dict[str, Any], dict[str, Any]]]) -> bool:
    """Prove the query scope is complete from page metadata and unique IDs."""
    groups: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for call, data in calls:
        args = call.get("args_summary") or {}
        total, pages, page = data.get("total"), data.get("pages"), data.get("page")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (total, pages, page)):
            return False
        filters = {key: value for key, value in args.items() if key not in {"page", "page_size"}}
        key = (json.dumps(filters, sort_keys=True), total, pages)
        groups.setdefault(key, []).append(data)
    for (_filters, total, pages), results in groups.items():
        if total == 0 and pages == 0:
            return True
        if pages < 1 or {item.get("page") for item in results} != set(range(1, pages + 1)):
            continue
        records = [row for result in results for row in result.get("records", []) if isinstance(row, dict)]
        ids = {str(row.get("id")) for row in records if row.get("id")}
        if len(ids) >= total:
            return True
    return False


def compare_persisted_terminal(events: list[dict[str, Any]], persisted_run: dict[str, Any] | None) -> list[str]:
    terminal = next((event.get("payload", {}) for event in events if event.get("type") == "run_finished"), None)
    if terminal is None:
        return ["live stream has no run_finished event"]
    if not isinstance(persisted_run, dict):
        return ["persisted RunView is missing"]
    issues = []
    if persisted_run.get("status") != terminal.get("status"):
        issues.append("persisted RunView status differs from terminal event")
    if persisted_run.get("summary") != terminal.get("summary"):
        issues.append("persisted RunView summary differs from terminal event")
    review = persisted_run.get("review") or {}
    if "review_passed" in terminal and review.get("passed") != terminal.get("review_passed"):
        issues.append("persisted RunView review result differs from terminal event")
    return issues


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
    parse_failures: list[dict[str, Any]] = []
    for call in starts:
        outcome = finishes.get(call.get("call_id"))
        if call.get("name") not in READ_ONLY_TOOLS or not outcome or outcome.get("status") != "success":
            continue
        try:
            data = json.loads(outcome.get("result_summary") or "{}")
        except (TypeError, ValueError):
            parse_failures.append(call)
            continue
        if not isinstance(data, dict):
            parse_failures.append(call)
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
        inventory_calls = [(call, data) for call, data in successful
                           if call.get("name") == "inventory_page"
                           and (call.get("args_summary") or {}).get("warehouse_id") == "W01"]
        if not _has_complete_pages(inventory_calls):
            errors.append("target-gap query lacks complete W01 pagination evidence")
        rows = [row for _call, data in inventory_calls for row in data.get("records", []) if isinstance(row, dict)]
        expected = {"P001": 55, "P003": 36, "P004": 10}
        observed = {(str(row.get("part_id")), row.get("shortage")) for row in rows
                    if row.get("warehouse_id") == "W01"}
        if not all((part_id, shortage) in observed for part_id, shortage in expected.items()):
            errors.append("complete target-gap result did not contain P001=55, P003=36, and P004=10")
        cited = {(str(item.get("part_id")), item.get("value")) for item in answer_check.cited_facts
                 if item.get("field") == "shortage" and item.get("warehouse_id") == "W01"}
        normalized = re.sub(r"\s+", "", answer)
        for part_id, shortage in expected.items():
            if (part_id, shortage) not in cited or not re.search(
                rf"{part_id}[^；;。\n]{{0,40}}(?:缺口\s*)?{shortage}件", normalized
            ):
                errors.append(f"final answer did not answer target gap {part_id}/W01={shortage}")
        if any(call.get("name") == "inventory_page" for call in starts) and not inventory_calls:
            errors.append("inventory page result is missing, truncated, or outside W01; insufficient evidence")
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
        quote_calls = [(call, data) for call, data in successful
                       if call.get("name") == "quote_list"
                       and (call.get("args_summary") or {}).get("part_id") == "P003"]
        valid = bool(quote_calls and _has_complete_pages(quote_calls) and all(
            item.get("is_valid") is False for _call, data in quote_calls
            for item in data.get("records", []) if isinstance(item, dict)
        ))
        plain_answer = re.sub(r"[*_`#>]", "", answer)
        normalized_answer = re.sub(r"\s+", "", plain_answer).lower()
        clauses = re.split(r"[。.!?\n；;]", normalized_answer)
        states_no_valid_quote = any(
            "p003" in clause and re.search(
                r"(?:没有|無|无|不存在|不含)(?:任何)?有效报价|(?:no|without)validquotes?",
                clause,
            )
            for clause in clauses
        )
        if not valid or not states_no_valid_quote:
            errors.append("P003 result did not prove there is no valid quote from a complete query; insufficient evidence")
    else:
        errors.append("unknown fixed question index")
    relevant_names = {"inventory_page"} if question_index == 0 else {"replenishment_preview"} if question_index == 1 else {"quote_list"}
    if any(call.get("name") in relevant_names for call in parse_failures):
        errors.append("successful tool result summary is truncated or unparseable; insufficient evidence")
    return not errors, errors
