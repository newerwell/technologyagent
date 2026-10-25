"""DeepAgents锁定版本兼容探针及LangGraph适配边界。"""

from __future__ import annotations

import inspect
from importlib.metadata import version


def compatibility_report() -> dict[str, object]:
    from deepagents import create_deep_agent

    signature = inspect.signature(create_deep_agent)
    return {
        "deepagents_version": version("deepagents"),
        "accepts_modelport": False,
        "built_in_tools_default": True,
        "supports_checkpointed_langgraph_runtime": "checkpointer" in signature.parameters,
        "supports_interrupts": False,
        "supports_event_sink_contract": False,
        "adapter": "explicit_langgraph_subgraphs",
        "reason": "The pinned factory expects a LangChain model and enables filesystem/execute/task tools by default; that does not preserve ModelPort and the project's capability registry boundary.",
    }


def assert_locked_compatibility() -> dict[str, object]:
    report = compatibility_report()
    if report["deepagents_version"] != "0.7.30":
        raise RuntimeError(f"DeepAgents lock mismatch: {report['deepagents_version']}")
    return report
