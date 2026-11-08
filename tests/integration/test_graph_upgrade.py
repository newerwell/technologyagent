"""P07-T01: capture a real P06 v1 approval checkpoint before graph routing changes."""

from pathlib import Path
import json

from bson import json_util
from langgraph.graph import END, START, StateGraph
from pymongo import MongoClient
from backend.app.agent.state_v2 import AgentStateV2
import backend.app.agent.versions.v2 as v2_module
import backend.app.services.order_workflows as order_workflows_module


FIXTURE = Path(__file__).parents[1] / "fixtures" / "p07-v1-pending-approval.json"


def _restore_preupgrade_checkpoint(client, db):
    snapshot = json_util.loads(FIXTURE.read_text(encoding="utf-8"))
    assert snapshot["provenance"]["created_before_p07_graph_upgrade"] is True
    assert snapshot["provenance"]["source_commit"] == "95740ef7c589ac007a794ec9682654f6e55ef2f0"
    assert snapshot["provenance"]["graph_version"] == "v1"
    for collection, documents in snapshot["collections"].items():
        # The integration fixture starts from seeded catalog facts. Add only this
        # historical run's records, avoiding duplicates for the seeded drafts.
        for document in documents:
            if collection == "drafts" and document["_id"] in {"D001", "D002"}:
                continue
            db[collection].insert_one(document)
    return snapshot


def _sse_payloads(response_text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in response_text.splitlines() if line.startswith("data: ")]


def _v2_probe_builder(original_builder):
    def build(*args, **kwargs):
        original_graph = original_builder(*args, **kwargs)
        sink = args[2] if len(args) > 2 else kwargs["sink"]

        class ProbeState(AgentStateV2, total=False):
            v2_probe: str

        async def v2_probe_node(_state):
            await sink.emit("token", {
                "message_id": "p09-a3-v2-probe", "delta": "[v2_probe_node] v2_probe=executed", "actor": "main",
            })
            return {"v2_probe": "executed"}

        async def verify_v2_probe_state(state):
            await sink.emit("token", {
                "message_id": "p09-a3-v2-state", "delta": f"[verify_v2_probe_state] v2_probe={state.get('v2_probe')}",
                "actor": "main",
            })
            return {}

        async def run_v2_core_graph(state):
            return await original_graph.ainvoke(state, config={"recursion_limit": 80})

        builder = StateGraph(ProbeState)
        builder.add_node("v2_probe_node", v2_probe_node)
        builder.add_node("v2_core_graph", run_v2_core_graph)
        builder.add_node("verify_v2_probe_state", verify_v2_probe_state)
        # This test-only edge is traversed before the production v2 core graph.
        builder.add_edge(START, "v2_probe_node")
        builder.add_edge("v2_probe_node", "v2_core_graph")
        builder.add_edge("v2_core_graph", "verify_v2_probe_state")
        builder.add_edge("verify_v2_probe_state", END)
        return builder.compile()

    return build

def test_preupgrade_v1_approval_checkpoint_resumes_once_after_upgrade(seeded_client, monkeypatch):
    container = seeded_client.app.state.container
    client = MongoClient(container.settings.mongodb_uri.get_secret_value())
    db = client[container.settings.mongodb_database]
    try:
        snapshot = _restore_preupgrade_checkpoint(client, db)
        run_doc = snapshot["collections"]["runs"][0]
        run_id = run_doc["_id"]
        old_checkpoint_ids = {item["checkpoint_id"] for item in snapshot["collections"]["lg_checkpoints"]}
        assert old_checkpoint_ids
        old_checkpoint_docs = list(db["lg_checkpoints"].find({
            "thread_id": run_doc["thread_id"], "checkpoint_ns": "",
        }).sort("checkpoint_id", 1))
        assert {item["checkpoint_id"] for item in old_checkpoint_docs} == old_checkpoint_ids
        before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
        assert before == 2
        order_ids_before = {item["_id"] for item in db["orders"].find({}, {"_id": 1})}
        successful_operations_before = db["operations"].count_documents({
            "action": "order_create", "status": "succeeded",
        })
        inventory_before = db["inventories"].find_one({"part_id": "P001", "warehouse_id": "W01"})
        assert (inventory_before["on_hand"], inventory_before["inbound"]) == (20, 10)
        assert seeded_client.get(f"/api/runs/{run_id}").json()["data"]["pending_interrupt"]["kind"] == "approval"

        # A v2 run must prove that a version-specific node/state/edge actually ran,
        # while this historical v1 approval is still pending.
        pending = run_doc["pending_interrupt"]
        decision = {
            "interrupt_id": pending["interrupt_id"], "decision": "approve",
            "expected_version": pending["version"], "payload": {},
            "idempotency_key": "p07-v1-approval-once",
        }
        def changed_v2_builder(*_args, **_kwargs):
            raise AssertionError("simulated v2 graph rewrite must not affect v1 resume")

        with monkeypatch.context() as v2_changed:
            original_v2_builder = v2_module.V2_GRAPH_BUILDER
            v2_changed.setattr(v2_module, "V2_GRAPH_BUILDER", _v2_probe_builder(original_v2_builder))
            v2_changed.setattr(order_workflows_module, "V2_ORDER_GRAPH_BUILDER", changed_v2_builder)
            v2_response = seeded_client.post("/api/chat/stream", json={
                "message": "P001 在 W01 缺多少？", "request_id": "p09-a3-v2-probe",
            })
            assert v2_response.status_code == 200, v2_response.text
            v2_events = _sse_payloads(v2_response.text)
            v2_run_id = v2_events[0]["run_id"]
            assert seeded_client.get(f"/api/runs/{v2_run_id}").json()["data"]["graph_version"] == "v2"
            v2_event_log = seeded_client.get(f"/api/runs/{v2_run_id}/events?after_seq=0").json()["data"]
            probe_events = [item for item in v2_event_log if item["type"] == "token"
                            and item["payload"].get("delta") == "[v2_probe_node] v2_probe=executed"]
            assert probe_events, [(item["type"], item["payload"]) for item in v2_event_log]
            state_events = [item for item in v2_event_log if item["type"] == "token"
                            and item["payload"].get("delta") == "[verify_v2_probe_state] v2_probe=executed"]
            assert state_events

            first = seeded_client.post(f"/api/runs/{run_id}/resume", json=decision)
        assert first.status_code == 200, first.text
        assert first.json()["data"]["status"] == "completed"
        assert db["runs"].find_one({"_id": run_id})["graph_version"] == "v1"
        assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1

        replay = seeded_client.post(f"/api/runs/{run_id}/resume", json=decision)
        assert replay.status_code == 200, replay.text
        assert replay.json()["data"]["status"] == "completed"
        assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1
        new_orders = list(db["orders"].find({"_id": {"$nin": list(order_ids_before)}}))
        assert len(new_orders) == 1
        assert new_orders[0]["total_cents"] == 66000
        approval_id = snapshot["collections"]["approvals"][0]["_id"]
        assert db["approvals"].find_one({"_id": approval_id})["status"] == "consumed"
        successful_operations_after = db["operations"].count_documents({
            "action": "order_create", "status": "succeeded",
        })
        assert successful_operations_after == successful_operations_before + 1
        inventory_after = db["inventories"].find_one({"part_id": "P001", "warehouse_id": "W01"})
        assert (inventory_after["on_hand"], inventory_after["inbound"]) == (20, 65)

        # A v2 workflow can now persist its own namespace beside the restored
        # v1 checkpoint; the pending v1 run was not migrated or overwritten.
        old_checkpoints = list(db["lg_checkpoints"].find({
            "thread_id": run_doc["thread_id"], "checkpoint_ns": "",
        }))
        assert old_checkpoint_ids.issubset({item["checkpoint_id"] for item in old_checkpoints})
        upgraded = seeded_client.post("/api/order-workflows", json={
            "message": "补货 P001 并准备订单",
            "request_id": "p07-v2-beside-restored-v1",
            "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
        })
        assert upgraded.status_code == 200, upgraded.text
        v2_run = upgraded.json()["data"]
        assert v2_run["graph_version"] == "v2"
        v2_thread = f"p07:v2:{v2_run['thread_id']}:{v2_run['id']}"
        assert db["lg_checkpoints"].count_documents({"thread_id": v2_thread, "checkpoint_ns": ""}) > 0
        assert db["lg_checkpoints"].count_documents({"thread_id": f"p07:v2:{run_doc['thread_id']}:{run_id}"}) == 0
        assert db["lg_checkpoints"].count_documents({
            "thread_id": run_doc["thread_id"], "checkpoint_ns": "",
            "checkpoint_id": {"$in": list(old_checkpoint_ids)},
        }) == len(old_checkpoint_ids)
        unchanged_old_checkpoint_docs = list(db["lg_checkpoints"].find({
            "_id": {"$in": [item["_id"] for item in old_checkpoint_docs]},
        }).sort("checkpoint_id", 1))
        assert unchanged_old_checkpoint_docs == old_checkpoint_docs
        assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1
    finally:
        client.close()


def test_new_order_run_is_persistently_routed_to_v2(seeded_client):
    response = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001 并准备订单",
        "request_id": "p07-new-order-v2",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    assert response.status_code == 200, response.text
    run = response.json()["data"]
    assert run["graph_version"] == "v2"
    container = seeded_client.app.state.container
    client = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        key = f"p07:v2:{run['thread_id']}:{run['id']}"
        assert client[container.settings.mongodb_database]["lg_checkpoints"].count_documents({
            "thread_id": key, "checkpoint_ns": "",
        }) > 0
    finally:
        client.close()
