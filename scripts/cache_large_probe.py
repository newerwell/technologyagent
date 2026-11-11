"""Synthetic long-input DeepSeek cache comparison; live mode is explicit.

The probe never executes a tool or touches a database. Reports contain only
numeric usage and oracle results, never prompts, tool data, or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values

from backend.app.agent.graph import build_specialist_system_prompt
from backend.app.agent.prompt_layout import (
    build_v2_initial_messages,
    messages_with_verified_facts,
)
from backend.app.agent.skill_loader import (
    render_skill_context,
    select_skills_for_request,
)
from backend.app.config import load_settings
from backend.app.contracts.agent import ExecutorInput, ModelMessage
from backend.app.contracts.common import RequestContext
from backend.app.integrations.model import ModelProviderError, build_model
from backend.app.ports.tools import ToolSpec
from mcp_server.tools.specs import TOOL_SPECS

_SHORTAGES = {
    "W01": {3: 12, 18: 17, 31: 9},
    "W02": {5: 11, 19: 15, 34: 7},
}
_AS_OF = "2026-11-11T00:00:00Z"
_MIN_PROMPT_TOKENS = 4096
_SEQUENCE = (("legacy", "W01"), ("optimized", "W02"),
             ("legacy", "W02"), ("optimized", "W01"))


@dataclass(frozen=True)
class ProbeCase:
    warehouse_id: str
    expected: dict[str, int]
    fixture: dict[str, Any]
    facts_chars: int
    tools: tuple[ToolSpec, ...]
    legacy_messages: tuple[ModelMessage, ...]
    optimized_messages: tuple[ModelMessage, ...]
    template_id: str


def _inventory_page(warehouse_id: str) -> tuple[dict[str, Any], dict[str, int]]:
    shortages = _SHORTAGES[warehouse_id]
    rows = []
    for index in range(1, 37):
        shortage = shortages.get(index, 0)
        projected = 40 - shortage if shortage else 54 + index % 11
        part_id = f"P{100 + index:03d}"
        rows.append({
            "inventory_id": f"I-{warehouse_id}-{index:03d}",
            "part_id": part_id,
            "part_name": f"合成零件{index:02d}",
            "specification": f"验证规格-{index:02d}",
            "unit": "个",
            "warehouse_id": warehouse_id,
            "on_hand": projected + 1,
            "reserved": 3,
            "inbound": 2,
            "available": projected - 2,
            "projected": projected,
            "safety_stock": 20,
            "target_stock": 40,
            "shortage": shortage,
            "warning": projected < 20,
            "source_ref": {"entity": "inventory", "id": f"I-{warehouse_id}-{index:03d}",
                           "data_source": "synthetic_probe", "as_of": _AS_OF},
        })
    result = {
        "ok": True,
        "data": {"records": rows, "total": len(rows), "page": 1, "page_size": 36, "pages": 1},
        "meta": {"warehouse_id": warehouse_id, "as_of": _AS_OF,
                 "data_source": "synthetic_probe", "complete": True},
    }
    expected = {f"P{100 + index:03d}": shortage for index, shortage in shortages.items()}
    return result, expected


def build_case(warehouse_id: str) -> ProbeCase:
    """Build the same synthetic business facts with legacy and v2 prompt layouts."""
    if warehouse_id not in _SHORTAGES:
        raise ValueError("unknown synthetic warehouse")
    question = (
        f"请仅根据本轮已提供的可信库存事实，列出 {warehouse_id} 中目标库存缺口大于 0 的"
        "零件编号、缺口数量及业务单位；无缺口的不要列出。数据已给出，不要再调用工具。"
    )
    ctx = RequestContext(owner_id="synthetic_cache_probe", request_id="synthetic_cache_probe",
                         run_id="synthetic_cache_probe", actor="analyst")
    scope = {"warehouse_ids": [warehouse_id]}
    request = ExecutorInput(
        run_id=ctx.run_id, thread_id="synthetic_cache_probe", message=question,
        ctx=ctx, graph_version="v2", request_constraints=scope,
        skill_context=render_skill_context(select_skills_for_request(question, "analyst")),
    )
    result, expected = _inventory_page(warehouse_id)
    verified_facts = (
        f"库存页范围为 {warehouse_id}；来源 synthetic_probe；as_of 为 {_AS_OF}。\n"
        + json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    )
    old_prompt = build_specialist_system_prompt(request)
    legacy = [
        ModelMessage(role="system", content=old_prompt +
                     "\n\n经来源核验的辅助事实（不得替换你的回答）:\n" + verified_facts),
        ModelMessage(role="user", content=question),
    ]
    optimized, template_id = build_v2_initial_messages(request, scope)
    optimized = messages_with_verified_facts(optimized, verified_facts)
    tools = tuple(spec for spec in TOOL_SPECS if spec.effect == "read")
    return ProbeCase(warehouse_id, expected, result, len(verified_facts), tools,
                     tuple(legacy), tuple(optimized), template_id)


def score_answer(answer: str, tool_calls: list[str], expected: dict[str, int]) -> bool:
    """Require each shortage and no extra part, with no further tool call."""
    if tool_calls:
        return False
    matches = list(re.finditer(r"(?<![A-Za-z0-9])P\d{3}(?!\d)", answer))
    if {match.group() for match in matches} != set(expected):
        return False
    sections = [
        (match.group(), answer[match.end():matches[index + 1].start() if index + 1 < len(matches) else None])
        for index, match in enumerate(matches)
    ]
    return all(
        any(part == part_id and re.search(rf"(?<!\d){amount}(?!\d)\s*个", section)
            for part, section in sections)
        for part_id, amount in expected.items()
    )


def save_probe_progress(
    numeric_path: Path, answer_path: Path, report: dict[str, Any], answers: list[dict[str, Any]],
) -> None:
    """Keep the numeric report separate from local-only synthetic model answers."""
    for path, value in ((numeric_path, report), (answer_path, answers)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _settings(env_file: Path | None):
    if env_file is None:
        return load_settings()
    if not env_file.is_file():
        raise SystemExit("configuration file does not exist")
    source = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
    source.update(os.environ)
    return load_settings(environ=source)


def _is_deepseek_endpoint(base_url: str) -> bool:
    parsed = urlsplit(base_url)
    return parsed.scheme == "https" and parsed.hostname == "api.deepseek.com" and parsed.port in (None, 443)


async def _run_live(
    env_file: Path | None, report_path: Path, answer_path: Path, max_calls: int, source_sha: str,
) -> None:
    if report_path.exists() or answer_path.exists():
        raise SystemExit("probe report path already exists")
    settings = _settings(env_file)
    if not settings.model_configured or not _is_deepseek_endpoint(settings.model_base_url):
        raise SystemExit("DeepSeek live model is not configured")
    model = build_model(settings)
    assert model is not None
    report: dict[str, Any] = {
        "sample_type": "synthetic_adapter_probe_not_end_to_end",
        "source_sha": source_sha,
        "model_name": settings.model_name,
        "at_utc": datetime.now(UTC).isoformat(),
        "minimum_prompt_tokens": _MIN_PROMPT_TOKENS,
        "tool_payload_mode": "canonicalized_for_both_layouts",
        "rows": [],
    }
    answers: list[dict[str, Any]] = []
    for index, (layout, warehouse_id) in enumerate(_SEQUENCE[:max_calls], 1):
        case = build_case(warehouse_id)
        messages = case.legacy_messages if layout == "legacy" else case.optimized_messages
        ctx = RequestContext(owner_id="synthetic_cache_probe", request_id=f"probe_{index}",
                             run_id=f"probe_{index}", actor="analyst")
        usage: dict[str, Any] = {}
        answer_parts: list[str] = []
        tool_calls: list[str] = []
        started = time.perf_counter()
        first_output_ms = None
        # Direct adapter call; one outbound request, no application retry or tool execution.
        try:
            async for delta in model.stream(messages, case.tools, ctx):
                if delta.kind in {"token", "tool_call"} and first_output_ms is None:
                    first_output_ms = round((time.perf_counter() - started) * 1000, 1)
                if delta.kind == "token" and delta.content:
                    answer_parts.append(delta.content)
                elif delta.kind == "tool_call" and delta.tool_call and delta.tool_call.name:
                    tool_calls.append(delta.tool_call.name)
                elif delta.kind == "usage":
                    usage = delta.usage or {}
        except ModelProviderError as exc:
            row = {"attempt": index, "layout": layout, "warehouse_id": warehouse_id,
                   "status": "error", "error_code": exc.code, "usage": None}
            report["rows"].append(row)
            save_probe_progress(report_path, answer_path, report, answers)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            raise
        prompt_tokens = usage.get("prompt_tokens")
        hit = usage.get("prompt_cache_hit_tokens")
        miss = usage.get("prompt_cache_miss_tokens")
        valid_usage = all(type(value) is int and value >= 0 for value in (prompt_tokens, hit, miss))
        valid_usage = valid_usage and prompt_tokens == hit + miss
        row = {
            "attempt": index, "layout": layout, "warehouse_id": warehouse_id,
            "input_chars": sum(len(message.content) for message in messages),
            "prompt_tokens": prompt_tokens, "prompt_cache_hit_tokens": hit,
            "prompt_cache_miss_tokens": miss, "completion_tokens": usage.get("completion_tokens"),
            "first_output_ms": first_output_ms,
            "usage_valid": valid_usage,
            "oracle_passed": score_answer("".join(answer_parts), tool_calls, case.expected),
            "extra_tool_calls": len(tool_calls),
        }
        report["rows"].append(row)
        answers.append({"attempt": index, "layout": layout, "warehouse_id": warehouse_id,
                        "answer": "".join(answer_parts), "expected": case.expected,
                        "tool_calls": tool_calls})
        save_probe_progress(report_path, answer_path, report, answers)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if not valid_usage or prompt_tokens < _MIN_PROMPT_TOKENS:
            raise SystemExit("provider usage is invalid or prompt is below the long-input threshold")
        if index < max_calls:
            await asyncio.sleep(3)
    print("report=" + str(report_path), flush=True)
    print("local_answers=" + str(answer_path), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="make four paid DeepSeek requests")
    parser.add_argument("--max-calls", type=int, default=4, choices=range(1, 5),
                        help="maximum outbound requests in live mode (1-4)")
    parser.add_argument("--env-file", type=Path, help="read model configuration without copying the file")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--answers-report", type=Path)
    args = parser.parse_args()
    if not args.live:
        for warehouse_id in _SHORTAGES:
            case = build_case(warehouse_id)
            print(json.dumps({
                "warehouse_id": warehouse_id, "records": 36, "read_only_tools": len(case.tools),
                "legacy_input_chars": sum(len(m.content) for m in case.legacy_messages),
                "optimized_input_chars": sum(len(m.content) for m in case.optimized_messages),
                "expected_shortages": len(case.expected),
            }, ensure_ascii=False))
        return
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = args.report or Path(f".runtime/reports/deepseek-cache-large-probe-{stamp}.json")
    answer_path = args.answers_report or Path(f".runtime/private/deepseek-cache-large-answers-{stamp}.json")
    repo_root = Path(__file__).resolve().parents[1]
    source_sha = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo_root}", "rev-parse", "HEAD"],
        cwd=repo_root, text=True,
    ).strip()
    asyncio.run(_run_live(args.env_file, report_path, answer_path, args.max_calls, source_sha))


if __name__ == "__main__":
    main()
