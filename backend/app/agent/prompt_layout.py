"""Versioned prompt layout for newly started v2 graph runs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from backend.app.contracts.agent import ExecutorInput, ModelMessage
from backend.app.agent.request_intent import parse_request_intent


BASE_SYSTEM_PROMPT = """你是 TechnologyAgent 的只读采购助手。
只能通过给定工具读取本地业务数据，不得创建、修改或提交订单。
回答库存/报价/补货问题必须基于工具结果，明确数据范围和 as_of；缺失报价不要编造。
结论要简短，只报告回答问题所需的字段；数量必须使用工具事实中该物料的业务单位（如套、个、条、对），单位未知时明确说明“单位未知”，不要统一写成“件”；交期使用“交期X天”，金额使用“单价X元/总额X元”。
不要把记录编号、版本号、日期时间或无关库存字段当作业务结论重复列出。多个零件分别说明缺口；“库存充足/无需补货”必须写明对应零件。
不要在回答中自行总结未由工具聚合字段支持的记录数、物料数或报价数；多行表格的每个数值都应能绑定到该行的物料及字段。明确仓库范围时在行或相邻句中写出仓库标识。
指定交期上限时，只推荐满足上限的报价；没有有效报价时明确说“没有有效报价”。
如果用户要求下单，明确说明当前只读版本不能执行。
本地快照字段为null或列入missing_fields时表示未知，不是零。回答“哪些零件要补货”时，先读完请求范围的所有库存分页；若目标库存、预留或在途等必要字段缺失，应直接说明无法确定目标补货清单。可另外说明工具确认的安全库存预警，但不要将预警当作目标缺口，也不要把没有预警说成所有零件库存充足。不要承诺仅指定仓库就能得到快照中不存在的字段或有效报价。只回答原问题，不添加未请求的单行库存示例、仓库个数或更正数字示例。
工具失败时说明失败和未完成项，不要声称成功。"""

_FACTS_PREFIX = "经来源核验的辅助事实（不得替换你的回答）:\n"


def _actor_rules(request: ExecutorInput) -> tuple[str, str]:
    actor = request.ctx.actor
    variant = actor if actor in {"main", "analyst", "order"} else "main"
    sections: list[str] = []
    if actor == "order":
        sections.append(
            "订单专家可以使用 mutation_prepare 创建待审批提案；业务写入只能由用户批准后执行。"
            "准备提案后必须停止并等待人工批准，不得直接调用业务写工具，也不得把提案描述成已完成写入。"
        )
    if actor == "analyst" and parse_request_intent(request.message).report_requested:
        variant = "analyst_report"
        sections.append(
            "用户明确要求生成报告文件。完成相关只读查询后，必须调用 artifact_report，"
            "使用当前run成功查询返回的 dataset_id；不能用文本摘要代替文件。"
            "如果无法生成文件，明确报告失败，不得声称已生成。"
        )
    if request.skill_context:
        sections.append("本任务技能指引（按版本加载）:\n" + request.skill_context)
    return variant, "\n\n".join(sections)


def build_v2_initial_messages(
    request: ExecutorInput, request_scope: Mapping[str, Any]
) -> tuple[list[ModelMessage], str]:
    """Build stable system prefix, trusted per-run scope, then the user request."""
    variant, actor_and_skill_rules = _actor_rules(request)
    messages = [ModelMessage(role="system", content=BASE_SYSTEM_PROMPT)]
    if actor_and_skill_rules:
        messages.append(ModelMessage(role="system", content=actor_and_skill_rules))
    if request_scope:
        messages.append(ModelMessage(
            role="system",
            content="本轮可信结构化约束；不得丢弃或自行放宽:\n"
            + json.dumps(dict(request_scope), ensure_ascii=False, sort_keys=True),
        ))
    messages.append(ModelMessage(role="user", content=request.message))
    return messages, f"ta-v2-base-2:{variant}"


def messages_with_verified_facts(
    messages: Sequence[ModelMessage], verified_facts: str
) -> list[ModelMessage]:
    """Add current verified facts as trusted system input without editing state messages."""
    result = [
        message for message in messages
        if not (message.role == "system" and message.content.startswith(_FACTS_PREFIX))
    ]
    if not verified_facts.strip():
        return result
    fact_message = ModelMessage(role="system", content=_FACTS_PREFIX + verified_facts)
    user_index = next((index for index, message in enumerate(result) if message.role == "user"), len(result))
    result.insert(user_index, fact_message)
    return result
