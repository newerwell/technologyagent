"""Read-only restore evidence must distinguish equal counts with different facts."""

from bson.binary import Binary

from scripts.p09_restore_facts import collect_facts


def test_restore_fingerprints_cover_checkpoint_bytes_approval_links_and_file_source(
    db_name, mongo_admin, tmp_path,
):
    db = mongo_admin[db_name]
    content = b'{"synthetic":true}'
    storage = tmp_path / "storage"
    path = storage / "local-owner/run-test/art-test.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    try:
        db.checkpoints.insert_one({"_id": "checkpoint-test", "checkpoint": Binary(b"before")})
        db.approvals.insert_one({"_id": "apr-test", "owner_id": "local-owner", "run_id": "run-test",
                                 "status": "consumed", "decision": "approve", "draft_id": "draft-test",
                                 "draft_version": 2, "order_id": "order-test"})
        db.orders.insert_one({"_id": "order-test", "operation_id": "operation-test"})
        db.operations.insert_one({"_id": "operation-test", "owner_id": "local-owner",
                                  "action": "order_create", "status": "succeeded", "order_id": "order-test"})
        source = [{"data_source": "local_seed", "as_of": "2026-01-01T00:00:00Z", "id": "I001"}]
        db.artifacts.insert_one({"_id": "art-test", "owner_id": "local-owner", "run_id": "run-test",
                                 "status": "ready", "storage_key": "local-owner/run-test/art-test.json",
                                 "size_bytes": len(content), "source_refs": source})
        before = collect_facts(db, storage)
        assert before["business"]["approvals"][0]["order_id"] == "order-test"
        assert before["business"]["approvals"][0]["_id"] == "apr-test"
        assert before["business"]["approvals"][0]["run_id"] == "run-test"
        assert before["business"]["order_operation_links"][0]["operation_id"] == "operation-test"
        assert before["business"]["successful_operation_links"][0]["_id"] == "operation-test"
        assert before["artifacts"][0]["source_refs"] == source
        assert before == collect_facts(db, storage)
        db.checkpoints.update_one({"_id": "checkpoint-test"}, {"$set": {"checkpoint": Binary(b"after!")}})
        changed = collect_facts(db, storage)
        assert changed["collections"]["checkpoints"]["count"] == before["collections"]["checkpoints"]["count"]
        assert changed["collections"]["checkpoints"]["sha256"] != before["collections"]["checkpoints"]["sha256"]
        path.write_bytes(b"x" * len(content))
        changed_file = collect_facts(db, storage)
        assert changed_file["collections"] == changed["collections"]
        assert changed_file["artifacts"][0]["sha256"] != changed["artifacts"][0]["sha256"]
    finally:
        mongo_admin.drop_database(db_name)
