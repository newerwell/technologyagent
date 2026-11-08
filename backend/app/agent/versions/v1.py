"""P03/P04 v1 durable execution ABI, isolated from v2 builders."""

from types import MappingProxyType

from backend.app.agent.versions.v1_impl import build_graph_v1
from backend.app.agent.versions.v1_order_impl import (
    OrderWorkflowState as _V1OrderState,
    build_order_graph_v1,
    workflow_config_v1,
)
from backend.app.agent.state import AgentStateV1

GRAPH_VERSION = "v1"
V1_STATE_SCHEMA = AgentStateV1
V1_GRAPH_BUILDER = build_graph_v1
V1_ORDER_STATE_SCHEMA = _V1OrderState
V1_ORDER_GRAPH_BUILDER = build_order_graph_v1
V1_WORKFLOW_CONFIG = workflow_config_v1
CHECKPOINT_ABI = MappingProxyType({
    "graph_version": "v1",
    "order_namespace": "run_id",
    "order_thread_key": "thread_id",
    "node_names": ("model", "tools", "prepare_order_v1", "supplement_order_v1",
                   "approve_order_v1", "submit_order_v1"),
})

__all__ = [
    "GRAPH_VERSION", "V1_STATE_SCHEMA", "V1_GRAPH_BUILDER", "V1_ORDER_STATE_SCHEMA",
    "V1_ORDER_GRAPH_BUILDER", "V1_WORKFLOW_CONFIG", "CHECKPOINT_ABI",
]
