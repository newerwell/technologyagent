"""P07 专家v2集成回归。"""

from __future__ import annotations

import json


def _events(text: str):
    result = []
    for block in text.split("\n\n"):
        data = next((line[6:] for line in block.splitlines() if line.startswith("data: ")), None)
        if data:
            result.append(json.loads(data))
    return result


def test_v2_inventory_run_is_delegated_and_records_skill_provenance(seeded_client):
    response = seeded_client.post("/api/chat/stream", json={
        "message": "P001 在 W01 缺多少？", "request_id": "p07-analyst-delegation",
    })
    assert response.status_code == 200, response.text
    events = _events(response.text)
    run_id = events[0]["run_id"]
    run = seeded_client.get(f"/api/runs/{run_id}").json()["data"]
    assert run["graph_version"] == "v2"
    assert any(item["name"] == "analyst" and item["run_id"] == run_id for item in run["specialist_trace"]), run
    skill = next(item for item in run["skill_manifest"] if item["id"] == "inventory-replenishment")
    assert skill["version"] == "1.0.0" and len(skill["content_hash"]) == 64
    assert any(event["type"] == "tool_started" and event["payload"]["actor"] == "analyst" for event in events)
    assert any(event["type"] == "token" and event["payload"]["actor"] == "analyst" for event in events)
