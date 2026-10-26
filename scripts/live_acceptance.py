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


def _invalid_quote_conclusion_issues(answer: str, successful: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[str]:
    """Independent acceptance oracle for positive claims about invalid quotes."""
    invalid: set[tuple[str, str]] = set()
    for call, data in successful:
        if call.get("name") != "quote_list":
            continue
        for row in data.get("records", []):
            if isinstance(row, dict) and row.get("is_valid") is False:
                part = str(row.get("part_id") or (call.get("args_summary") or {}).get("part_id") or "").upper()
                supplier = str(row.get("supplier_id") or "").upper()
                invalid.add((part, supplier))
    issues: list[str] = []
    plain = re.sub(r"[*_`#>]", "", answer)
    for paragraph in re.split(r"\n+", re.sub(r"\s+", "", plain)):
        positive_text = re.sub(
            r"(?:没有|无|不含|不存在)(?:任何)?有效报价|无法判断最便宜|无法推荐|不(?:推荐|建议|选择|采购|下单)",
            "", paragraph,
        )
        positive_action = bool(re.search(
            r"(?:推荐|建议|选择|下单|报价有效|有效报价|采购(?:该|这|此)?(?:报价|供应商|物料|零件|P\d{3}))",
            positive_text,
        ))
        for part, supplier in invalid:
            scoped = (part and part in paragraph) or (supplier and supplier in paragraph and len({key[0] for key in invalid}) == 1)
            if scoped and positive_action:
                issues.append(f"answer contains a positive conclusion/recommendation for invalid quote {part or 'unknown part'}/{supplier or 'unknown supplier'}")
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
    errors.extend(_invalid_quote_conclusion_issues(answer, successful))
    if question_index == 0:
        inventory_calls = [(call, data) for call, data in successful
                           if call.get("name") == "inventory_page"
                           and (call.get("args_summary") or {}).get("warehouse_id") == "W01"]
        if not _has_complete_pages(inventory_calls):
            errors.append("target-gap query lacks complete W01 pagination evidence")
        rows = [row for _call, data in inventory_calls for row in data.get("records", []) if isinstance(row, dict)]
        # Concrete units come from the checked-in v1 catalog fixture, independently
        # of the model answer being scored.
        expected = {"P001": (55, "套"), "P003": (36, "个"), "P004": (10, "条")}
        observed = {(str(row.get("part_id")), row.get("shortage"), row.get("unit")) for row in rows
                    if row.get("warehouse_id") == "W01"}
        if not all((part_id, shortage, unit) in observed for part_id, (shortage, unit) in expected.items()):
            errors.append("complete target-gap result did not contain P001=55, P003=36, and P004=10")
        cited = {(str(item.get("part_id")), item.get("value")) for item in answer_check.cited_facts
                 if item.get("field") == "shortage" and item.get("warehouse_id") == "W01"}
        normalized = re.sub(r"\s+", "", answer)
        for part_id, (shortage, unit) in expected.items():
            if (part_id, shortage) not in cited or not re.search(
                rf"{part_id}[^；;。\n]{{0,40}}(?:缺口\s*)?{shortage}{re.escape(unit)}", normalized
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


def completed_live_run_issues(events: Any, *, expected_mode: str = "live") -> list[str]:
    """Validate the whole persisted event boundary; tool_started alone is not success."""
    if not isinstance(events, list) or not events:
        return ["event stream is empty"]
    issues: list[str] = []
    starts = [event for event in events if event.get("type") == "run_started"]
    finishes = [event for event in events if event.get("type") == "run_finished"]
    ends = [event for event in events if event.get("type") == "stream_end"]
    if len(starts) != 1:
        issues.append("expected exactly one run_started event")
    elif starts[0].get("payload", {}).get("model_mode") != expected_mode:
        issues.append(f"run_started mode is not {expected_mode}")
    if len(finishes) != 1:
        issues.append("expected exactly one run_finished event")
    else:
        terminal = finishes[0].get("payload", {})
        if terminal.get("status") != "completed":
            issues.append("run did not finish completed")
        if terminal.get("review_passed") is not True:
            issues.append("terminal review_passed is not true")
    if len(ends) != 1:
        issues.append("expected exactly one stream_end event")
    else:
        ended = ends[0].get("payload", {})
        if ended.get("reason") != "completed":
            issues.append("stream_end did not confirm completed")
        seqs = [event.get("seq") for event in events]
        if any(not isinstance(seq, int) or isinstance(seq, bool) for seq in seqs):
            issues.append("event sequence contains a non-integer sequence")
        elif seqs != list(range(1, len(events) + 1)):
            issues.append("event stream has a sequence gap or is truncated")
        if ended.get("last_seq") != (seqs[-1] if seqs else None):
            issues.append("stream_end last_seq does not match the final event")
    if any(event.get("type") == "error" for event in events):
        issues.append("run emitted an error event")
    run_ids = {event.get("run_id") for event in events if event.get("run_id")}
    started_run_id = starts[0].get("run_id") if len(starts) == 1 else None
    if len(run_ids) > 1 or (started_run_id and run_ids and run_ids != {started_run_id}):
        issues.append("event stream contains mixed run IDs")
    # A review event may fail before a later revision. The persisted terminal
    # review is authoritative, but the last emitted review may never be failure.
    reviews = [event.get("payload", {}) for event in events if event.get("type") == "review"]
    if reviews and reviews[-1].get("passed") is not True:
        issues.append("last review event did not pass")
    return issues


def successful_tool_results(events: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Pair successful tool events and parse their structured result summaries."""
    started = [event.get("payload", {}) for event in events if event.get("type") == "tool_started"]
    finished = {event.get("payload", {}).get("call_id"): event.get("payload", {})
                for event in events if event.get("type") == "tool_finished"}
    results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for call in started:
        outcome = finished.get(call.get("call_id"))
        if not outcome or outcome.get("status") != "success":
            continue
        try:
            data = json.loads(outcome.get("result_summary") or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            results.append((call, data))
    return results


def validate_preference_attempt(attempt: dict[str, Any]) -> list[str]:
    """Prove preference persistence, live execution, answer facts, and read-only effects."""
    issues: list[str] = []
    if not isinstance(attempt, dict):
        return ["attempt record is missing"]
    for name in ("remember_events", "query_events"):
        issues.extend(f"{name}: {issue}" for issue in completed_live_run_issues(attempt.get(name)))
    for name in ("remember_run", "query_run"):
        run = attempt.get(name)
        if not isinstance(run, dict) or run.get("status") != "completed":
            issues.append(f"{name} persisted run is not completed")
        elif (run.get("review") or {}).get("passed") is not True:
            issues.append(f"{name} persisted review did not pass")
    remembered = attempt.get("remember_preferences")
    queried = attempt.get("query_preferences")
    if not isinstance(remembered, dict) or remembered.get("default_warehouse") != "W01":
        issues.append("remember run did not persist default_warehouse=W01")
    if not isinstance(queried, dict) or queried.get("default_warehouse") != "W01":
        issues.append("follow-up run did not read persisted default_warehouse=W01")
    before, after = attempt.get("database_before"), attempt.get("database_after")
    if not isinstance(before, dict) or not isinstance(after, dict) or before != after:
        issues.append("read-only preference query changed business database facts")

    events = attempt.get("query_events") if isinstance(attempt.get("query_events"), list) else []
    results = successful_tool_results(events)
    relevant: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for call, data in results:
        args = call.get("args_summary") or {}
        if call.get("name") not in {"inventory_page", "replenishment_preview", "inventory_get"}:
            continue
        if args.get("warehouse_id") != "W01":
            continue
        rows = data.get("records", [])
        lines = data.get("lines", [])
        if call.get("name") == "inventory_get":
            rows = [data]
        facts = [row for row in [*rows, *lines] if isinstance(row, dict)]
        if any(row.get("part_id") == "P001" and row.get("warehouse_id") == "W01"
               and row.get("shortage") == 55 for row in facts):
            relevant.append((call, data))
    if not relevant:
        issues.append("no successful W01 query proved P001 shortage=55")
    answer = attempt.get("answer")
    if not isinstance(answer, str) or "P001" not in answer or "55" not in answer or "套" not in answer:
        issues.append("final assistant answer did not state P001 shortage=55套")
    return issues


def pytest_execution_issues(output: str) -> list[str]:
    """Require an executed, non-skipped pytest case for a live acceptance command."""
    summary = None
    for line in reversed((output or "").splitlines()):
        if re.search(r"\bin\s+[0-9]+(?:\.[0-9]+)?s\b", line) and re.search(
            r"\b(?:passed|failed|skipped|errors?|deselected|xfailed|xpassed)\b", line
        ):
            summary = line
            break
    if summary is None:
        return ["pytest output has no completed test summary"]
    counts = {name: int(value) for value, name in re.findall(
        r"\b(\d+)\s+(passed|failed|skipped|errors?|deselected|xfailed|xpassed)\b", summary
    )}
    if counts.get("passed", 0) < 1:
        return ["pytest completed without a passed test"]
    rejected = {name: value for name, value in counts.items()
                if name in {"failed", "skipped", "error", "errors", "deselected", "xfailed", "xpassed"} and value}
    if rejected:
        return [f"pytest summary contains non-accepting outcomes: {rejected}"]
    return []
