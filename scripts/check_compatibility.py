"""P00 依赖兼容探针：真实导入 + 最小调用，失败退出非 0。

不连接外部 ERP/真实模型；FastMCP 只绑定 127.0.0.1 随机端口并在 finally 回收。
缺少 MongoDB replica set 时 DB 探针标记 not_run，整体不能通过。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import platform
import socket
import sys
import time
import uuid
from dataclasses import dataclass, field
from importlib import metadata
from typing import Annotated, Any, Callable, TypedDict

from pymongo import MongoClient

from backend.app.config import Settings, load_settings
from backend.app.repositories.mongo import MongoResources

REQUIRED_PROBES = (
    "fastapi_request",
    "langgraph_graph",
    "fake_tool_call_loop",
    "model_adapter",
    "mongo_transaction",
    "mongo_checkpointer",
    "fastmcp_http",
    "deepagents_fake_graph",
)

def _append_messages(left: list, right: list) -> list:
    return (left or []) + (right or [])


TRACKED_PACKAGES = (
    "fastapi",
    "starlette",
    "pydantic",
    "pymongo",
    "langgraph",
    "langchain-core",
    "langchain-openai",
    "langgraph-checkpoint-mongodb",
    "fastmcp",
    "mcp",
    "deepagents",
    "uvicorn",
)


@dataclass
class ProbeOutcome:
    name: str
    status: str
    detail: str
    duration_ms: float = 0.0


@dataclass
class CompatibilityReport:
    outcomes: list[ProbeOutcome] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(item.status == "ok" for item in self.outcomes) and {
            item.name for item in self.outcomes
        } == set(REQUIRED_PROBES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "environment": self.environment,
            "probes": [
                {
                    "name": item.name,
                    "status": item.status,
                    "detail": item.detail,
                    "duration_ms": round(item.duration_ms, 2),
                }
                for item in self.outcomes
            ],
        }


def _database_settings() -> Settings:
    database = f"technologyagent_test_compat_{uuid.uuid4().hex[:10]}"
    return load_settings().model_copy(update={"mongodb_database": database})


def _require_primary(uri: str) -> None:
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    try:
        hello = client.admin.command("hello")
        if not hello.get("isWritablePrimary"):
            raise RuntimeError("MongoDB is reachable but is not a writable primary")
        if not hello.get("setName"):
            raise RuntimeError("MongoDB is not running as a replica set")
    finally:
        client.close()


def probe_fastapi_request() -> str:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"pong": "ok"}

    with TestClient(app) as client:
        response = client.get("/ping")
    if response.status_code != 200 or response.json() != {"pong": "ok"}:
        raise RuntimeError(f"unexpected FastAPI response: {response.status_code}")
    return "GET /ping -> 200"


def probe_langgraph_graph() -> str:
    from langgraph.graph import END, START, StateGraph

    class State(TypedDict):
        value: int

    def bump(state: State) -> State:
        return {"value": state["value"] + 1}

    graph = StateGraph(State)
    graph.add_node("bump", bump)
    graph.add_edge(START, "bump")
    graph.add_edge("bump", END)
    result = graph.compile().invoke({"value": 41})
    if result != {"value": 42}:
        raise RuntimeError(f"unexpected LangGraph result: {result}")
    return "StateGraph invoke -> value=42"


def probe_fake_tool_call_loop() -> str:
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.tools import tool
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode

    class State(TypedDict):
        messages: Annotated[list, _append_messages]

    @tool
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    turn = {"count": 0}

    def fake_model(state: State) -> State:
        turn["count"] += 1
        if turn["count"] == 1:
            message = AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"a": 2, "b": 3}, "id": "call-1"}],
            )
        else:
            message = AIMessage(content="result is 5")
        return {"messages": [message]}

    graph = StateGraph(State)
    graph.add_node("model", fake_model)
    graph.add_node("tools", ToolNode([add]))
    graph.add_edge(START, "model")
    graph.add_conditional_edges(
        "model",
        lambda state: "tools" if getattr(state["messages"][-1], "tool_calls", None) else END,
        {"tools": "tools", END: END},
    )
    graph.add_edge("tools", "model")
    result = graph.compile().invoke({"messages": [HumanMessage("2+3?")]})
    tool_messages = [m for m in result["messages"] if type(m).__name__ == "ToolMessage"]
    if not tool_messages or str(tool_messages[0].content) != "5":
        raise RuntimeError("fake tool call loop did not return tool result 5")
    return "AIMessage(tool_call) -> ToolNode -> AIMessage"


def probe_model_adapter() -> str:
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model="compatibility-probe",
        api_key="probe-not-a-real-key",
        base_url="http://127.0.0.1:1/v1",
        timeout=1,
    )
    if model.model_name != "compatibility-probe":
        raise RuntimeError("ChatOpenAI model name was not retained")
    return "ChatOpenAI constructed offline (no network call)"


async def _mongo_transaction_probe(settings: Settings) -> str:
    resources = await MongoResources.open(settings)
    try:
        for name in ("p00_probe_a", "p00_probe_b"):
            try:
                await resources.db.create_collection(name)
            except Exception as exc:  # noqa: BLE001
                if getattr(exc, "code", None) != 48:
                    raise
        try:
            async with resources.transaction() as session:
                await resources.db.p00_probe_a.insert_one({"probe": "rollback"}, session=session)
                await resources.db.p00_probe_b.insert_one({"probe": "rollback"}, session=session)
                raise RuntimeError("intentional rollback")
        except RuntimeError as exc:
            if str(exc) != "intentional rollback":
                raise
        if await resources.db.p00_probe_a.count_documents({"probe": "rollback"}) != 0:
            raise RuntimeError("rollback left documents in collection A")
        if await resources.db.p00_probe_b.count_documents({"probe": "rollback"}) != 0:
            raise RuntimeError("rollback left documents in collection B")
        return "transaction aborted; both collections empty"
    finally:
        await resources.close()


def probe_mongo_transaction() -> str:
    settings = _database_settings()
    try:
        _require_primary(settings.mongodb_uri.get_secret_value())
        result = asyncio.run(_mongo_transaction_probe(settings))
        return result
    finally:
        with contextlib.suppress(Exception):
            _drop_database(settings, "mongo_transaction")


def _checkpointer_graph():
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    class State(TypedDict):
        value: int

    def first(state: State) -> State:
        return {"value": state["value"] + 1}

    def ask(state: State) -> State:
        answer = interrupt({"question": "approve?"})
        return {"value": state["value"] + (1 if answer == "yes" else 0)}

    graph = StateGraph(State)
    graph.add_node("first", first)
    graph.add_node("ask", ask)
    graph.add_edge(START, "first")
    graph.add_edge("first", "ask")
    graph.add_edge("ask", END)
    return graph


def probe_mongo_checkpointer() -> str:
    from langgraph.checkpoint.mongodb import MongoDBSaver
    from langgraph.types import Command

    settings = _database_settings()
    uri = settings.mongodb_uri.get_secret_value()
    _require_primary(uri)
    try:
        with MongoDBSaver.from_conn_string(uri, db_name=settings.mongodb_database) as saver:
            graph = _checkpointer_graph().compile(checkpointer=saver)
            config = {"configurable": {"thread_id": f"probe-{uuid.uuid4().hex}"}}
            graph.invoke({"value": 1}, config)
            state = graph.get_state(config)
            if state.next != ("ask",):
                raise RuntimeError(f"interrupt was not persisted, next={state.next}")
            resumed = graph.invoke(Command(resume="yes"), config)
            if resumed != {"value": 3}:
                raise RuntimeError(f"resume in the same saver instance returned {resumed}")
        return (
            "MongoDBSaver persisted interrupt and resumed in the same graph/saver instance; "
            "process restart recovery is P04"
        )
    finally:
        with contextlib.suppress(Exception):
            _drop_database(settings, "mongo_checkpointer")


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def probe_fastmcp_http() -> str:
    from fastmcp import Client, FastMCP

    mcp = FastMCP("compatibility-probe")

    @mcp.tool
    def add_tool(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
    logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
    port = _free_port()

    async def run() -> str:
        server = asyncio.create_task(
            mcp.run_async(
                transport="http",
                host="127.0.0.1",
                port=port,
                show_banner=False,
                log_level="critical",
            )
        )
        last_error: Exception | None = None
        try:
            for _ in range(60):
                if server.done():
                    exception = server.exception()
                    raise RuntimeError(f"FastMCP server exited early: {exception}")
                try:
                    async with Client(f"http://127.0.0.1:{port}/mcp", timeout=2) as client:
                        tools = await client.list_tools()
                        names = [item.name for item in tools]
                        if "add_tool" not in names:
                            raise RuntimeError(f"tool missing from list: {names}")
                        result = await client.call_tool("add_tool", {"a": 2, "b": 4})
                        if result.data != 6:
                            raise RuntimeError(f"unexpected tool result: {result.data}")
                        return f"list_tools={names}; call_tool add_tool(2,4)={result.data}"
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    await asyncio.sleep(0.2)
            raise RuntimeError(f"FastMCP server did not become ready: {last_error}")
        finally:
            server.cancel()
            with contextlib.suppress(BaseException):
                await server

    return asyncio.run(run())


def probe_deepagents_fake_graph() -> str:
    from deepagents import create_deep_agent
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class FakeChatModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "p00-compatibility-fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="fake answer"))])

        def bind_tools(self, tools, **kwargs):
            return self

    agent = create_deep_agent(model=FakeChatModel(), tools=[])
    result = agent.invoke({"messages": [HumanMessage("hello")]})
    contents = [getattr(message, "content", "") for message in result["messages"]]
    if "fake answer" not in contents:
        raise RuntimeError("DeepAgents fake graph did not reach final answer")
    return "create_deep_agent assembled and invoked with fake chat model"


def _drop_database(settings: Settings, _label: str) -> None:
    database = settings.mongodb_database
    if not database.startswith("technologyagent_test_"):
        raise RuntimeError(f"refusing to drop non-test database {database!r}")
    client = MongoClient(settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=2000)
    try:
        client.drop_database(database)
    finally:
        client.close()


def _versions() -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    for name in TRACKED_PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": packages,
    }


def _run(name: str, probe: Callable[[], str]) -> ProbeOutcome:
    started = time.perf_counter()
    try:
        detail = probe()
        status = "ok"
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        detail = f"{type(exc).__name__}: {exc}"
    return ProbeOutcome(
        name=name,
        status=status,
        detail=detail,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


def run_compatibility() -> CompatibilityReport:
    probes: tuple[tuple[str, Callable[[], str]], ...] = (
        ("fastapi_request", probe_fastapi_request),
        ("langgraph_graph", probe_langgraph_graph),
        ("fake_tool_call_loop", probe_fake_tool_call_loop),
        ("model_adapter", probe_model_adapter),
        ("mongo_transaction", probe_mongo_transaction),
        ("mongo_checkpointer", probe_mongo_checkpointer),
        ("fastmcp_http", probe_fastmcp_http),
        ("deepagents_fake_graph", probe_deepagents_fake_graph),
    )
    report = CompatibilityReport(environment=_versions())
    for name, probe in probes:
        report.outcomes.append(_run(name, probe))
    return report


def main() -> int:
    report = run_compatibility()
    print("environment:")
    print(f"  python={report.environment['python']} platform={report.environment['platform']}")
    for name, version in report.environment["packages"].items():
        print(f"  {name}=={version}")
    print("probes:")
    for item in report.outcomes:
        print(f"  [{item.status}] {item.name} ({item.duration_ms:.1f} ms): {item.detail}")
    print(f"compatibility_ok={report.ok}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
