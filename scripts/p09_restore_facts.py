"""Read-only fingerprints for the isolated P09 full database/storage restore."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

from bson import json_util
from pymongo import MongoClient

ISOLATED_URI = "mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true"


def validate_target(database: str, uri: str) -> None:
    if not re.fullmatch(r"technologyagent_test_p09_(clean|restored)_[a-zA-Z0-9_]+", database):
        raise ValueError("Only an isolated P09 clean/restored test database is accepted")
    if uri != ISOLATED_URI:
        raise ValueError("P09 restore fingerprints require the isolated 27028 ta-rs target")


def collect_facts(db, storage: Path) -> dict:
    storage = storage.resolve(strict=True)
    collections = {}
    for name in sorted(db.list_collection_names()):
        documents = list(db[name].find({}).sort("_id", 1))
        canonical = json_util.dumps(documents, json_options=json_util.CANONICAL_JSON_OPTIONS,
                                    sort_keys=True, separators=(",", ":")).encode("utf-8")
        collections[name] = {"count": len(documents), "sha256": hashlib.sha256(canonical).hexdigest()}
    artifacts = []
    for artifact in db.artifacts.find({}).sort("_id", 1):
        key = artifact.get("storage_key")
        if artifact.get("status") != "ready" or not key or "\\" in key:
            raise ValueError("Artifact must be ready with a safe storage key")
        path = (storage / key).resolve(strict=True)
        if not path.is_relative_to(storage):
            raise ValueError("Artifact escapes storage root")
        content = path.read_bytes()
        if len(content) != artifact["size_bytes"]:
            raise ValueError("Artifact bytes differ from its persisted size")
        artifacts.append({**{name: artifact[name] for name in ("_id", "owner_id", "run_id", "storage_key")},
                          "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                          "source_refs": artifact.get("source_refs", [])})
    return {
        "collections": collections,
        "artifacts": artifacts,
        "business": {
            "orders": db.orders.count_documents({}),
            "successful_operations": db.operations.count_documents({"status": "succeeded"}),
            "inventory": db.inventories.find_one({"_id": "I001"}, {"_id": 0, "inbound": 1, "on_hand": 1, "version": 1}),
            "approvals": list(db.approvals.find({}, {"_id": 1, "owner_id": 1, "status": 1, "decision": 1,
                                                     "draft_id": 1, "draft_version": 1, "order_id": 1}).sort("_id", 1)),
            "order_operation_links": list(db.orders.find({}, {"_id": 1, "operation_id": 1}).sort("_id", 1)),
            "successful_operation_links": list(db.operations.find({"status": "succeeded"},
                {"_id": 1, "owner_id": 1, "action": 1, "order_id": 1}).sort("_id", 1)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    args = parser.parse_args()
    uri = os.environ.get("MONGODB_URI", "")
    validate_target(args.database, uri)
    with MongoClient(uri, serverSelectionTimeoutMS=3000) as client:
        hello = client.admin.command("hello")
        if hello.get("setName") != "ta-rs" or hello.get("isWritablePrimary") is not True:
            raise ValueError("P09 restore target must be a writable ta-rs PRIMARY")
        print(json.dumps(collect_facts(client[args.database], args.storage_root), sort_keys=True))


if __name__ == "__main__":
    main()
