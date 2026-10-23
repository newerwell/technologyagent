"""P00 collection 约定、schema_version 与幂等索引初始化。"""

from __future__ import annotations

from datetime import datetime, timezone

from pymongo.errors import CollectionInvalid, OperationFailure
from pymongo.asynchronous.database import AsyncDatabase

SCHEMA_VERSION = 1

SESSIONS = "sessions"
SYSTEM_META = "system_meta"
HEALTH_PROBE = "_health_probe"

P00_COLLECTIONS = (SESSIONS, SYSTEM_META, HEALTH_PROBE)


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
    """幂等初始化 P00 实际使用的 collection 与索引。"""
    for name in P00_COLLECTIONS:
        await _ensure_collection(db, name)

    await db[SESSIONS].create_index(
        [("expires_at", 1)], name="ttl_expires_at", expireAfterSeconds=0
    )
    await db[SESSIONS].create_index([("owner_id", 1)], name="owner_id_1")
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
    return {"schema_version": SCHEMA_VERSION, "collections": list(P00_COLLECTIONS)}
