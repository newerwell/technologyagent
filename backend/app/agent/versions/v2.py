"""P07 v2：以显式命名的LangGraph专家子图适配现有ModelPort。"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph


class SpecialistState(TypedDict, total=False):
    request: Any
    result: Any


def build_specialist_subgraph(handler: Callable[[Any], Awaitable[Any]]):
    async def analyst_specialist(state: SpecialistState) -> dict[str, Any]:
        return {"result": await handler(state["request"])}

    graph = StateGraph(SpecialistState)
    graph.add_node("analyst_specialist", analyst_specialist)
    graph.add_edge(START, "analyst_specialist")
    graph.add_edge("analyst_specialist", END)
    return graph.compile()
