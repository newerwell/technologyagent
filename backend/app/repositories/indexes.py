"""collection 约定、schema_version 与幂等索引初始化。"""

from __future__ import annotations

from datetime import datetime, timezone

from pymongo.errors import CollectionInvalid, OperationFailure
from pymongo.asynchronous.database import AsyncDatabase

SCHEMA_VERSION = 1

SESSIONS = "sessions"
SYSTEM_META = "system_meta"
HEALTH_PROBE = "_health_probe"

PARTS = "parts"
SUPPLIERS = "suppliers"
QUOTES = "quotes"
INVENTORIES = "inventories"
DRAFTS = "drafts"
ORDERS = "orders"

THREADS = "threads"
RUNS = "runs"
MESSAGES = "messages"
EVENTS = "events"
MCP_SESSIONS = "mcp_sessions"

P00_COLLECTIONS = (SESSIONS, SYSTEM_META, HEALTH_PROBE)
P01_COLLECTIONS = (PARTS, SUPPLIERS, QUOTES, INVENTORIES, DRAFTS, ORDERS)
P02_COLLECTIONS = (THREADS, RUNS, MESSAGES, EVENTS)
P03_COLLECTIONS = (MCP_SESSIONS,)
ALL_COLLECTIONS = P00_COLLECTIONS + P01_COLLECTIONS + P02_COLLECTIONS + P03_COLLECTIONS


async def _ensure_collection(db: AsyncDatabase, name: str) -> None:
    try:
        await db.create_collection(name)
    except CollectionInvalid:
        return
    except OperationFailure as exc:
        # NamespaceExists
        if exc.code != 48:
            raise


async def ensure_indexes(db: AsyncDatabase) -> dict[str, object]:
    """幂等初始化 P00/P01/P02 实际使用的 collection 与索引。"""
    for name in ALL_COLLECTIONS:
        await _ensure_collection(db, name)

    await db[SESSIONS].create_index(
        [("expires_at", 1)], name="ttl_expires_at", expireAfterSeconds=0
    )
    await db[SESSIONS].create_index([("owner_id", 1)], name="owner_id_1")
    await db[PARTS].create_index([("code", 1)], name="code_unique", unique=True)
    await db[SUPPLIERS].create_index([("code", 1)], name="code_unique", unique=True)
    await db[QUOTES].create_index([("part_id", 1)], name="part_id_1")
    await db[QUOTES].create_index([("supplier_id", 1)], name="supplier_id_1")
    await db[INVENTORIES].create_index(
        [("part_id", 1), ("warehouse_id", 1)],
        name="part_warehouse_unique",
        unique=True,
    )
    await db[INVENTORIES].create_index([("warehouse_id", 1)], name="warehouse_id_1")
    await db[DRAFTS].create_index([("owner_id", 1)], name="owner_id_1")
    await db[ORDERS].create_index([("number", 1)], name="number_unique", unique=True)
    await db[ORDERS].create_index(
        [("draft_id", 1)], name="draft_id_unique", unique=True
    )
    await db[ORDERS].create_index([("owner_id", 1)], name="owner_id_1")
    await db[THREADS].create_index(
        [("owner_id", 1), ("updated_at", -1)], name="owner_updated"
    )
    await db[RUNS].create_index(
        [("owner_id", 1), ("request_id", 1)], name="owner_request_unique", unique=True
    )
    await db[RUNS].create_index(
        [("thread_id", 1), ("created_at", -1)], name="thread_created"
    )
    await db[RUNS].create_index([("status", 1)], name="status_1")
    await db[MESSAGES].create_index(
        [("thread_id", 1), ("created_at", 1)], name="thread_created"
    )
    await db[MESSAGES].create_index([("run_id", 1), ("role", 1)], name="run_role")
    await db[EVENTS].create_index(
        [("run_id", 1), ("seq", 1)], name="run_seq_unique", unique=True
    )
    await db[EVENTS].create_index(
        [("thread_id", 1), ("seq", 1)], name="thread_seq"
    )
    await db[MCP_SESSIONS].create_index(
        [("expires_at", 1)], name="ttl_expires_at", expireAfterSeconds=0
    )
    await db[MCP_SESSIONS].create_index(
        [("owner_id", 1), ("run_id", 1)], name="owner_run"
    )
    await db[SYSTEM_META].update_one(
        {"_id": "schema_version"},
        {
            "$set": {
                "value": SCHEMA_VERSION,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    return {"schema_version": SCHEMA_VERSION, "collections": list(ALL_COLLECTIONS)}