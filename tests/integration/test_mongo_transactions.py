"""P00-T03：真实 replica set 事务提交/回滚，不使用 mock。"""

from __future__ import annotations

import pytest
from pymongo.errors import OperationFailure

from backend.app.repositories.mongo import MongoResources
from tests.integration.conftest import assert_test_db, make_settings


def test_guard_refuses_non_test_database():
    with pytest.raises(AssertionError):
        assert_test_db("technologyagent_dev")


async def _prepare(mongo: MongoResources, *names: str) -> None:
    for name in names:
        try:
            await mongo.db.create_collection(name)
        except OperationFailure as exc:
            if exc.code != 48:
                raise


async def test_transaction_rolls_back_both_collections(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        await _prepare(mongo, "p00_tx_a", "p00_tx_b")
        with pytest.raises(RuntimeError, match="intentional rollback"):
            async with mongo.transaction() as session:
                await mongo.db.p00_tx_a.insert_one({"marker": "rollback"}, session=session)
                await mongo.db.p00_tx_b.insert_one({"marker": "rollback"}, session=session)
                raise RuntimeError("intentional rollback")
        assert await mongo.db.p00_tx_a.count_documents({"marker": "rollback"}) == 0
        assert await mongo.db.p00_tx_b.count_documents({"marker": "rollback"}) == 0
    finally:
        await mongo.close()
        assert_test_db(db_name)
        mongo_admin.drop_database(db_name)


async def test_transaction_commits_both_collections(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        await _prepare(mongo, "p00_tx_a", "p00_tx_b")
        async with mongo.transaction() as session:
            await mongo.db.p00_tx_a.insert_one({"marker": "commit"}, session=session)
            await mongo.db.p00_tx_b.insert_one({"marker": "commit"}, session=session)
        assert await mongo.db.p00_tx_a.count_documents({"marker": "commit"}) == 1
        assert await mongo.db.p00_tx_b.count_documents({"marker": "commit"}) == 1
    finally:
        await mongo.close()
        assert_test_db(db_name)
        mongo_admin.drop_database(db_name)
