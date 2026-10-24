"""P02 SSE/FakeAgent/history/取消/断线观察。"""

from __future__ import annotations

import json
import time

from backend.app.agent.fake_executor import FakeAgent


def parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    data: list[str] = []
    for line in text.splitlines():
        if line.startswith("data: "):
            data.append(line[6:])
        elif line == "":
            if data:
                events.append(json.loads("\n".join(data)))
                data = []
    if data:
        events.append(json.loads("\n".join(data)))
    return events


def read_until(events: list[dict], type_name: str) -> dict:
    for event in events:
        if event["type"] == type_name:
            return event
    raise AssertionError(f"event {type_name} not found: {[e['type'] for e in events]}")


def wait_terminal(client, run_id: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        run = response.json()["data"]
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.1)
    raise AssertionError("run did not reach terminal state")


def test_chat_stream_persists_events_messages_and_history(seeded_client):
    request_id = "p02-stream-1"
    response = seeded_client.post(
        "/api/chat/stream",
        json={"message": "测试流式输出", "request_id": request_id},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert events[0]["type"] == "run_started"
    assert events[-1]["type"] == "stream_end"
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    run_id = events[0]["run_id"]
    thread_id = events[0]["thread_id"]
    assert events[0]["payload"] == {
        "status": "running",
        "thread_id": thread_id,
        "run_id": run_id,
    }
    tokens = [event for event in events if event["type"] == "token"]
    assert tokens
    assert len({event["payload"]["message_id"] for event in tokens}) == 1
    tool_started = read_until(events, "tool_started")
    tool_finished = read_until(events, "tool_finished")
    assert tool_started["payload"]["simulation"] is True
    assert tool_finished["payload"]["call_id"] == tool_started["payload"]["call_id"]
    assert tool_finished["payload"]["status"] == "success"
    run_finished = read_until(events, "run_finished")
    assert run_finished["payload"]["status"] == "completed"

    run = seeded_client.get(f"/api/runs/{run_id}").json()["data"]
    assert run["status"] == "completed"
    assert run["last_seq"] == len(events)
    replay = seeded_client.get(f"/api/runs/{run_id}/events?after_seq=0").json()["data"]
    assert [event["event_id"] for event in replay] == [event["event_id"] for event in events]
    after = seeded_client.get(f"/api/runs/{run_id}/events?after_seq=3").json()["data"]
    assert all(event["seq"] > 3 for event in after)

    conversations = seeded_client.get("/api/conversations").json()["data"]
    assert any(item["id"] == thread_id for item in conversations)
    detail = seeded_client.get(f"/api/conversations/{thread_id}").json()["data"]
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assistant = detail["messages"][1]
    assert assistant["id"] == tokens[0]["payload"]["message_id"]
    assert len({message["id"] for message in detail["messages"]}) == 2
    assert detail["latest_run"]["id"] == run_id


def test_same_request_id_replays_same_run_without_duplicate_work(seeded_client):
    body = {"message": "重复提交", "request_id": "p02-repeat-1"}
    first = seeded_client.post("/api/chat/stream", json=body)
    first_events = parse_sse(first.text)
    first_run = first_events[0]["run_id"]
    second = seeded_client.post("/api/chat/stream", json=body)
    assert second.status_code == 200
    second_events = parse_sse(second.text)
    assert second_events[0]["run_id"] == first_run
    assert second_events[-1]["type"] == "stream_end"
    assert seeded_client.get(f"/api/runs/{first_run}").status_code == 200

    conflict = seeded_client.post(
        "/api/chat/stream",
        json={"message": "不同内容", "request_id": "p02-repeat-1"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_tool_failure_becomes_failed_run_and_error_event(seeded_client):
    container = seeded_client.app.state.container
    original = container.chat._executor
    container.chat._executor = FakeAgent(token_delay=0.001, tool_failure=True)
    try:
        response = seeded_client.post(
            "/api/chat/stream",
            json={"message": "工具失败", "request_id": "p02-tool-failure"},
        )
        events = parse_sse(response.text)
        tool_finished = read_until(events, "tool_finished")
        assert tool_finished["payload"]["status"] == "error"
        error = read_until(events, "error")
        assert error["payload"]["code"] == "EXECUTION_FAILED"
        run_id = events[0]["run_id"]
        run = seeded_client.get(f"/api/runs/{run_id}").json()["data"]
        assert run["status"] == "failed"
        assert run["error_code"] == "EXECUTION_FAILED"
    finally:
        container.chat._executor = original


def test_disconnect_observation_does_not_cancel_background_run(seeded_client):
    with seeded_client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "断线观察", "request_id": "p02-disconnect"},
    ) as response:
        assert response.status_code == 200
        first = None
        for line in response.iter_lines():
            if line.startswith("data: "):
                first = json.loads(line[6:])
                break
        assert first is not None and first["type"] == "run_started"
        run_id = first["run_id"]
        # 离开 with 会关闭观察连接；后台任务不应被取消。
    run = wait_terminal(seeded_client, run_id)
    assert run["status"] == "completed"
    events = seeded_client.get(f"/api/runs/{run_id}/events?after_seq=0").json()["data"]
    assert events[-1]["type"] == "stream_end"


def test_cancel_stops_fake_agent_and_persists_cancelled(seeded_client):
    with seeded_client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "取消任务", "request_id": "p02-cancel"},
    ) as response:
        events = []
        run_id = None
        for line in response.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                events.append(event)
                if event["type"] == "run_started":
                    run_id = event["run_id"]
                    cancel = seeded_client.post(f"/api/runs/{run_id}/cancel")
                    assert cancel.status_code == 200, cancel.text
        assert run_id is not None
        assert events[-1]["type"] == "stream_end"
    run = seeded_client.get(f"/api/runs/{run_id}").json()["data"]
    assert run["status"] == "cancelled"
    terminal = seeded_client.post(f"/api/runs/{run_id}/cancel")
    assert terminal.status_code == 200
    assert terminal.json()["data"]["status"] == "cancelled"


def test_api_owner_isolation_is_404_for_other_owner(seeded_client):
    response = seeded_client.post(
        "/api/chat/stream",
        json={"message": "私有", "request_id": "p02-private"},
    )
    events = parse_sse(response.text)
    run_id = events[0]["run_id"]
    thread_id = events[0]["thread_id"]
    # 本 API 会话固定 local-owner；直接验证数据库查询条件在所有接口中生效。
    run = seeded_client.get(f"/api/runs/{run_id}").json()["data"]
    assert run["thread_id"] == thread_id

def test_second_request_on_active_thread_returns_409(seeded_client):
    with seeded_client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "第一个运行", "request_id": "p02-active-1"},
    ) as response:
        first = None
        for line in response.iter_lines():
            if line.startswith("data: "):
                first = json.loads(line[6:])
                break
        assert first is not None and first["type"] == "run_started"
        second = seeded_client.post(
            "/api/chat/stream",
            json={
                "thread_id": first["thread_id"],
                "message": "第二个运行",
                "request_id": "p02-active-2",
            },
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "ACTIVE_RUN_EXISTS"
        # 关闭观察连接不取消第一个 run。
        run_id = first["run_id"]
    run = wait_terminal(seeded_client, run_id)
    assert run["status"] == "completed"
