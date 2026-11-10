"""N06：订单写入后说明失败时，before/after 与原始失败都保留在持久 trace。

用本地替身驱动真实 live 测试模块的 trace 包装，不调用模型。
"""

from __future__ import annotations

import pytest

from tests.live import test_order_workflow as live_order


class _Collection:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents

    def count_documents(self, query: dict) -> int:
        return sum(1 for document in self.documents
                   if all(document.get(key) == value for key, value in query.items()))

    def find_one(self, query: dict) -> dict | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None


class _Database:
    def __init__(self, data: dict[str, list[dict]]) -> None:
        self.data = data

    def __getitem__(self, name: str) -> _Collection:
        return _Collection(self.data.setdefault(name, []))


class _BrokenDatabase:
    def __getitem__(self, name: str):
        raise RuntimeError("database read failed")


def _seed_data() -> dict[str, list[dict]]:
    return {
        "inventories": [{"_id": "I001", "on_hand": 20, "inbound": 10}],
        "orders": [], "operations": [], "approvals": [],
    }


def test_order_written_before_explanation_failure_keeps_both_snapshots():
    data = _seed_data()
    db = _Database(data)
    trace = {"steps": [], "database_before": live_order._capture_database_state(db)}

    def action() -> None:
        data["orders"].append({"_id": "po-1", "operation_id": "op-1"})
        data["operations"].append({"_id": "op-1", "action": "order_create",
                                   "status": "succeeded", "order_id": "po-1"})
        data["approvals"].append({"_id": "apr-1", "order_id": "po-1", "status": "consumed"})
        trace["order_id"] = "po-1"
        raise AssertionError("订单说明核验失败")

    with pytest.raises(AssertionError, match="订单说明"):
        live_order._run_with_trace(db, trace, action)

    assert trace["database_before"]["order_count"] == 0
    assert trace["database_after"]["order_count"] == 1
    assert trace["database_after"]["order_operation_count"] == 1
    assert trace["database_after"]["order"]["_id"] == "po-1"
    assert trace["database_after"]["operation"]["_id"] == "op-1"
    assert trace["database_after"]["approval"]["status"] == "consumed"
    assert trace["database_after"]["inventory"]["on_hand"] == 20
    assert trace["failure"] == "AssertionError: 订单说明核验失败"


def test_database_read_error_does_not_replace_the_original_failure():
    trace = {"steps": []}

    def action() -> None:
        raise AssertionError("review failed")

    with pytest.raises(AssertionError, match="review failed"):
        live_order._run_with_trace(_BrokenDatabase(), trace, action)

    assert trace["failure"] == "AssertionError: review failed"
    assert "database read failed" in trace["database_after_error"]
    assert "database_after" not in trace
