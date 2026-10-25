"""封存的P03/P04 v1实现入口；节点与检查点配置保持原样。"""

from backend.app.agent.graph import build_graph_v1
from backend.app.agent.order_nodes import build_order_graph, workflow_config

GRAPH_VERSION = "v1"

__all__ = ["GRAPH_VERSION", "build_graph_v1", "build_order_graph", "workflow_config"]
