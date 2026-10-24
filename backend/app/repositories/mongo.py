"""MongoDB 异步连接、关闭与事务边界。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
from typing import AsyncIterator
import asyncio

from pymongo import MongoClient
from langgraph.checkpoint.mongodb import MongoDBSaver

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from backend.app.config import Settings


class MongoResources:
    """持有应用生命周期的 AsyncMongoClient。

    构造时不强制连接，数据库暂时不可用时 /health 仍可返回；
    /ready 通过 ping/primary/真实事务探针报告实际状态。
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncMongoClient | None = None
        self._db: AsyncDatabase | None = None
        self._checkpoint_client: MongoClient | None = None
        self._checkpointer: MongoDBSaver | None = None

    async def connect(self) -> None:
        """建立客户端（不强制完成 server selection）。"""
        self._client = AsyncMongoClient(
            self._settings.mongodb_uri.get_secret_value(),
            serverSelectionTimeoutMS=2500,
            connectTimeoutMS=2500,
            socketTimeoutMS=5000,
            tz_aware=True,
            appname="technologyagent",
        )
        self._db = self._client.get_database(self._settings.mongodb_database)

    async def configure_checkpointer(self) -> None:
        """单独持有 sync Mongo client；MongoDBSaver 的异步接口会在线程池运行同步 I/O。"""
        if self._checkpointer is not None:
            return

        def create():
            client = MongoClient(
                self._settings.mongodb_uri.get_secret_value(),
                serverSelectionTimeoutMS=2500,
                connectTimeoutMS=2500,
                socketTimeoutMS=5000,
                tz_aware=True,
                appname="technologyagent-checkpointer",
            )
            saver = MongoDBSaver(
                client,
                db_name=self._settings.mongodb_database,
                checkpoint_collection_name="lg_checkpoints",
                writes_collection_name="lg_checkpoint_writes",
            )
            return client, saver

        self._checkpoint_client, self._checkpointer = await asyncio.to_thread(create)

    @property
    def checkpointer(self) -> MongoDBSaver:
        if self._checkpointer is None:
            raise RuntimeError("Mongo checkpointer is not configured")
        return self._checkpointer

    @classmethod
    async def open(cls, settings: Settings) -> "MongoResources":
        resources = cls(settings)
        await resources.connect()
        return resources

    @property
    def client(self) -> AsyncMongoClient:
        if self._client is None:
            raise RuntimeError("MongoResources is not open")
        return self._client

    @property
    def db(self) -> AsyncDatabase:
        if self._db is None:
            raise RuntimeError("MongoResources is not open")
        return self._db

    async def ping(self) -> float:
        started = perf_counter()
        await self.client.admin.command("ping")
        return (perf_counter() - started) * 1000

    async def hello(self) -> dict:
        return await self.client.admin.command("hello")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncClientSession]:
        """真实 MongoDB 事务；异常时由驱动 abort。"""
        async with asyncio.timeout(15):
            async with self.client.start_session() as session:
                transaction = await session.start_transaction(max_commit_time_ms=15000)
                async with transaction:
                    yield session

    async def close(self) -> None:
        if self._checkpointer is not None:
            await asyncio.to_thread(self._checkpointer.close)
        if self._checkpoint_client is not None:
            await asyncio.to_thread(self._checkpoint_client.close)
        self._checkpointer = None
        self._checkpoint_client = None
        if self._client is not None:
            await self._client.close()
        self._client = None
        self._db = None
