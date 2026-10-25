"""封存的P03/P04 v1实现入口；节点、状态与检查点ABI保持原样。"""

from types import MappingProxyType

from backend.app.agent.graph import build_graph_v1 as _build_graph_v1
from backend.app.agent.order_nodes import build_order_graph as _build_order_graph, workflow_config as _workflow_config
from backend.app.agent.state import AgentStateV1

GRAPH_VERSION = "v1"
V1_STATE_SCHEMA = AgentStateV1
V1_GRAPH_BUILDER = _build_graph_v1
V1_ORDER_GRAPH_BUILDER = _build_order_graph
V1_WORKFLOW_CONFIG = _workflow_config
CHECKPOINT_ABI = MappingProxyType({
    "graph_version": "v1",
    "order_namespace": "run_id",
    "order_thread_key": "thread_id",
    "node_names": ("model", "tools", "prepare_order_v1", "supplement_order_v1",
                   "approve_order_v1", "submit_order_v1"),
})

__all__ = [
    "GRAPH_VERSION", "V1_STATE_SCHEMA", "V1_GRAPH_BUILDER", "V1_ORDER_GRAPH_BUILDER",
    "V1_WORKFLOW_CONFIG", "CHECKPOINT_ABI",
]
