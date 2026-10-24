"""P03-T06 显式 live 验收：三个固定问题各 3 次，记录真实轨迹。

没有 MODEL_API_KEY/MODEL_NAME 或未设置 RUN_LIVE_MODEL=1 时整个文件 skip，
不得把 skip 当成 live 通过。运行前需启动 API/MCP 与独立测试库。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_MODEL") != "1"
    or not os.environ.get("MODEL_API_KEY")
    or not os.environ.get("MODEL_NAME"),
    reason="live model not configured: set RUN_LIVE_MODEL=1, MODEL_NAME and MODEL_API_KEY",
)

QUESTIONS = [
    ("哪些零件要补货？只看W01。", lambda answer, tools: "P001" in answer and "55" in answer and bool(tools)),
    (
        "刹车片要求7天内到货，推荐哪家？",
        lambda answer, tools: "S01" in answer and "660" in answer and any("preview" in name for name in tools),
    ),
    (
        "P003买哪家的最便宜？",
        lambda answer, tools: ("无" in answer or "缺" in answer or "Q03" in answer)
        and "Q02" not in answer
        and bool(tools),
    ),
]


def parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        data = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


def test_live_readonly_three_questions_three_times():
    base = os.environ.get("LIVE_API_URL", "http://127.0.0.1:8030")
    trace: list[dict] = []
    try:
        with httpx.Client(base_url=base, timeout=180) as client:
            session = client.post("/api/session/local")
            assert session.status_code == 200, session.text
            for question, check in QUESTIONS:
                for attempt in range(3):
                    request_id = f"p03-live-{int(time.time() * 1000)}-{attempt}"
                    response = client.post(
                        "/api/chat/stream",
                        json={"message": question, "request_id": request_id},
                    )
                    events = parse_sse(response.text)
                    finished = next((e for e in events if e["type"] == "run_finished"), None)
                    answer = (finished or {}).get("payload", {}).get("summary", "")
                    tools = [
                        e["payload"].get("name", "")
                        for e in events
                        if e["type"] == "tool_started"
                    ]
                    passed = bool(finished) and check(answer, tools)
                    trace.append(
                        {
                            "question": question,
                            "attempt": attempt,
                            "passed": passed,
                            "answer": answer,
                            "tools": tools,
                            "event_types": [e["type"] for e in events],
                        }
                    )
    finally:
        path = Path(".runtime/live/p03-readonly.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    passed_count = sum(1 for item in trace if item["passed"])
    assert len(trace) == 9
    assert passed_count == 9, f"live pass rate {passed_count}/9; trace={path}"
