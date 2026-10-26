"""启动时校验专家声明，并在运行时执行工具白名单。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from backend.app.agent.budget import RunBudget
from backend.app.contracts.common import RequestContext
from backend.app.ports.tools import ToolResult, ToolSpec


def _is_schema(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    allowed_types = {"object", "array", "string", "integer", "number", "boolean", "null"}
    schema_type = value.get("type")
    types = schema_type if isinstance(schema_type, list) else [schema_type]
    if not types or not all(isinstance(item, str) for item in types) or not set(types) <= allowed_types:
        return False
    required = value.get("required", [])
    properties = value.get("properties", {})
    if not isinstance(required, list) or not all(isinstance(key, str) for key in required):
        return False
    if not isinstance(properties, dict) or not set(required) <= set(properties):
        return False
    if not all(_is_schema(child) for child in properties.values()):
        return False
    if "array" in types and not _is_schema(value.get("items")):
        return False
    additional = value.get("additionalProperties", True)
    if isinstance(additional, dict) and not _is_schema(additional):
        return False
    if not isinstance(additional, (dict, bool)):
        return False
    return True


@dataclass(frozen=True)
class SpecialistSpec:
    name: str
    objective: str
    tools: frozenset[str]
    skills: tuple[str, ...]
    recursive_delegation: bool
    can_approve: bool
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


def load_specialists(root: Path | None = None) -> dict[str, SpecialistSpec]:
    from mcp_server.tools.specs import READONLY_TOOL_NAMES

    known = set(READONLY_TOOL_NAMES) | {"artifact_chart", "artifact_report", "analysis_execute", "order_page", "order_get", "mutation_prepare"}
    directory = root or Path(__file__).parent
    result: dict[str, SpecialistSpec] = {}
    for name in ("analyst", "order"):
        payload = yaml.safe_load((directory / f"{name}.yaml").read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("name") != name:
            raise ValueError(f"invalid specialist declaration: {name}")
        tools = payload.get("tools")
        skills = payload.get("skills")
        if (not isinstance(tools, list) or not all(isinstance(item, str) for item in tools)
                or not isinstance(skills, list) or not all(isinstance(item, str) for item in skills)):
            raise ValueError(f"invalid specialist capabilities: {name}")
        unknown = set(tools) - known
        if unknown:
            raise ValueError(f"unknown specialist tools for {name}: {sorted(unknown)}")
        input_schema, output_schema = payload.get("input_schema"), payload.get("output_schema")
        if (not _is_schema(input_schema) or input_schema.get("type") != "object"
                or not _is_schema(output_schema) or output_schema.get("type") != "object"):
            raise ValueError(f"specialist schemas are invalid: {name}")
        if payload.get("recursive_delegation") is not False or payload.get("can_approve") is not False:
            raise ValueError(f"unsafe specialist policy: {name}")
        result[name] = SpecialistSpec(name, str(payload["objective"]), frozenset(tools), tuple(skills),
                                      False, False, input_schema, output_schema)
    if "order_create" in result["analyst"].tools or "analysis_execute" in result["order"].tools:
        raise ValueError("specialist tool boundary violated")
    return result


class RoleToolRegistry:
    """Both discovery and invocation enforce role capabilities."""

    def __init__(self, base, role: str, allowed_tools: set[str] | frozenset[str]):
        self._base, self.role, self.allowed_tools = base, role, frozenset(allowed_tools)

    def available(self, ctx: RequestContext) -> list[ToolSpec]:
        if ctx.actor != self.role:
            return []
        return [spec for spec in self._base.available(ctx) if spec.name in self.allowed_tools]

    async def invoke(self, name: str, arguments: dict[str, Any], ctx: RequestContext,
                     budget: RunBudget) -> ToolResult:
        if ctx.actor != self.role or name not in self.allowed_tools:
            return ToolResult(ok=False, error={"code": "ACTOR_FORBIDDEN",
                "message": f"{ctx.actor} is not allowed to invoke {name}"}, call_id=ctx.call_id or "")
        spec = next((item for item in self._base.available(ctx) if item.name == name), None)
        if spec is None:
            return ToolResult(ok=False, error={"code": "UNKNOWN_TOOL", "message": name}, call_id=ctx.call_id or "")
        return await self._base.invoke(name, arguments, ctx, budget)

    async def close(self) -> None:
        close = getattr(self._base, "close", None)
        if close is not None:
            await close()
