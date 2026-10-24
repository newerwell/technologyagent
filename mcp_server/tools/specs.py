"""MCP/模型共享的工具说明与 JSON schema；owner/run 不在参数中。"""

from __future__ import annotations

from typing import Any

from backend.app.ports.tools import ToolSpec

_PAGE = {"type": "integer", "minimum": 1, "default": 1}
_PAGE_SIZE = {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}
_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="inventory_page",
        description="分页查询库存及可用/预计/缺口/预警派生值；可按仓库和物料名筛选。",
        input_schema={
            "type": "object",
            "properties": {
                "warehouse_id": _NULLABLE_STRING,
                "part_name": _NULLABLE_STRING,
                "page": _PAGE,
                "page_size": _PAGE_SIZE,
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="inventory_warning",
        description="只返回预计可用量低于安全库存的预警库存记录。",
        input_schema={
            "type": "object",
            "properties": {
                "warehouse_id": _NULLABLE_STRING,
                "part_name": _NULLABLE_STRING,
                "page": _PAGE,
                "page_size": _PAGE_SIZE,
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="inventory_get",
        description="按 inventory_id 查询单条库存及派生值。",
        input_schema={
            "type": "object",
            "properties": {"inventory_id": {"type": "string", "minLength": 1}},
            "required": ["inventory_id"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="supplier_query",
        description="按名称分页查询供应商，返回 active/inactive 与信用评级。",
        input_schema={
            "type": "object",
            "properties": {"name": _NULLABLE_STRING, "page": _PAGE, "page_size": _PAGE_SIZE},
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="supplier_get",
        description="按 supplier_id 查询单个供应商。",
        input_schema={
            "type": "object",
            "properties": {"supplier_id": {"type": "string", "minLength": 1}},
            "required": ["supplier_id"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="part_search",
        description="按名称分页搜索零件。",
        input_schema={
            "type": "object",
            "properties": {"name": _NULLABLE_STRING, "page": _PAGE, "page_size": _PAGE_SIZE},
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="part_query",
        description="按 part_id 查询单个零件。",
        input_schema={
            "type": "object",
            "properties": {"part_id": {"type": "string", "minLength": 1}},
            "required": ["part_id"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="quote_list",
        description="分页查询报价；is_valid 由后端按当前时间和供应商状态判定。",
        input_schema={
            "type": "object",
            "properties": {
                "part_id": _NULLABLE_STRING,
                "part_name": _NULLABLE_STRING,
                "supplier_id": _NULLABLE_STRING,
                "page": _PAGE,
                "page_size": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="replenishment_preview",
        description="对指定零件/仓库计算补货缺口、有效报价、MOQ、推荐供应商和金额；不创建订单。",
        input_schema={
            "type": "object",
            "properties": {
                "part_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "warehouse_id": {"type": "string", "minLength": 1},
                "max_lead_days": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}], "default": None},
            },
            "required": ["part_ids", "warehouse_id"],
            "additionalProperties": False,
        },
    ),
]

TOOL_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}
READONLY_TOOL_NAMES = frozenset(TOOL_BY_NAME)

P04_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="draft_prepare",
        description="根据服务端本地事实准备订单草稿；缺少仓库时返回结构化缺失字段，不创建订单。",
        input_schema={"type": "object", "properties": {
            "part_ids": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
            "warehouse_id": {"type": "string", "minLength": 1},
            "max_lead_days": {"type": ["integer", "null"], "minimum": 0},
        }, "required": ["part_ids"], "additionalProperties": False},
        effect="write", capability="orders.draft",
    ),
    ToolSpec(
        name="order_create",
        description="仅提交已有且已批准的服务器草稿；必须提供草稿、审批与幂等键，服务端会重新校验。",
        input_schema={"type": "object", "properties": {
            "draft_id": {"type": "string", "minLength": 1},
            "approval_id": {"type": "string", "minLength": 1},
            "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
        }, "required": ["draft_id", "approval_id", "idempotency_key"], "additionalProperties": False},
        effect="write", capability="orders.create_approved",
    ),
    ToolSpec(
        name="order_get", description="按当前操作人查询实际采购订单。",
        input_schema={"type": "object", "properties": {"order_id": {"type": "string", "minLength": 1}},
                      "required": ["order_id"], "additionalProperties": False},
        effect="read", capability="orders.read",
    ),
    ToolSpec(
        name="order_page", description="分页查询当前操作人的采购订单。",
        input_schema={"type": "object", "properties": {
            "page": {"type": "integer", "minimum": 1},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
        }, "additionalProperties": False}, effect="read", capability="orders.read",
    ),
]
P04_TOOL_BY_NAME = {spec.name: spec for spec in P04_TOOL_SPECS}
ALL_TOOL_SPECS = TOOL_SPECS + P04_TOOL_SPECS
