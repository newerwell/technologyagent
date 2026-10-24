"""P04 MongoDB 持久检查点资源。"""

from __future__ import annotations

from langgraph.checkpoint.mongodb import MongoDBSaver


def saver_from_resources(resources) -> MongoDBSaver:
    """返回应用生命周期持有的 saver；配置在 MongoResources.configure_checkpointer 中完成。"""
    return resources.checkpointer
