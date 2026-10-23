"""等待/初始化 MongoDB 单节点 replica set 与 P00 索引。

幂等：可重复运行。只操作配置的数据库，不清理任何业务数据。
"""

from __future__ import annotations

import asyncio
import sys
from urllib.parse import urlparse

from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.uri_parser import parse_uri

from backend.app.config import Settings, load_settings
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.mongo import MongoResources

REPLICA_SET = "ta-rs"


def _direct_target(uri: str) -> tuple[str, int]:
    parsed = parse_uri(uri, warn=False)
    nodelist = parsed.get("nodelist") or []
    if not nodelist:
        raise RuntimeError("MONGODB_URI does not contain a host")
    host, port = nodelist[0]
    return host, port


def _advertised_host(host: str) -> str:
    if host in {"127.0.0.1", "localhost", "::1"}:
        return "localhost"
    return host


async def wait_for_primary(uri: str, timeout_seconds: float = 60.0) -> dict:
    host, port = _direct_target(uri)
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    last_error = ""
    async with AsyncMongoClient(
        host=host,
        port=port,
        directConnection=True,
        serverSelectionTimeoutMS=1000,
        connectTimeoutMS=1000,
    ) as client:
        initiated = False
        while asyncio.get_event_loop().time() < deadline:
            try:
                hello = await client.admin.command("hello")
                if hello.get("isWritablePrimary") and hello.get("setName") == REPLICA_SET:
                    return hello
                if not hello.get("setName") and not initiated:
                    member = {"_id": 0, "host": f"{_advertised_host(host)}:{port}"}
                    await client.admin.command(
                        {"replSetInitiate": {"_id": REPLICA_SET, "members": [member]}}
                    )
                    initiated = True
                last_error = f"primary not ready: setName={hello.get('setName')!r}"
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(1.0)
    raise RuntimeError(
        f"MongoDB replica set {REPLICA_SET} did not become primary within "
        f"{timeout_seconds:.0f}s ({last_error})"
    )


async def initialize(settings: Settings) -> dict:
    uri = settings.mongodb_uri.get_secret_value()
    hello = await wait_for_primary(uri)
    resources = await MongoResources.open(settings)
    try:
        indexes = await ensure_indexes(resources.db)
    finally:
        await resources.close()
    return {
        "database": settings.mongodb_database,
        "replica_set": hello.get("setName"),
        "primary": hello.get("isWritablePrimary"),
        "schema_version": indexes["schema_version"],
        "collections": indexes["collections"],
    }


def main() -> int:
    settings = load_settings()
    try:
        summary = asyncio.run(initialize(settings))
    except Exception as exc:  # noqa: BLE001
        print(f"init_db failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        "init_db ok: "
        f"db={summary['database']} replicaSet={summary['replica_set']} "
        f"primary={summary['primary']} schema_version={summary['schema_version']} "
        f"collections={','.join(summary['collections'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
