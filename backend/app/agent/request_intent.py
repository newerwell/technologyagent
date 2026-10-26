"""Deterministic parsing of explicit P07 request intent and preference commands."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestIntent:
    analysis_tasks: tuple[str, ...] = ()
    order_query: bool = False
    order_prepare: bool = False
    order_negated: bool = False
    preference_action: str | None = None
    preference_values: dict[str, object] = field(default_factory=dict)
    constraints: dict[str, object] = field(default_factory=dict)
    part_ids: tuple[str, ...] = ()
    report_requested: bool = False


_ORDER_WORDS = r"(?:订单|下单|采购)"
_NEGATION = re.compile(r"(?:不准备|不生成|不创建|不提交|不发起|不用|不想|暂时不|不要|无需|不需要|不必|暂不|禁止|拒绝|不考虑).{0,24}(?:下单|订单|采购)")
_QUERY = re.compile(r"(?:查询|查找|查看|看看|检索|状态|详情|列表).{0,24}" + _ORDER_WORDS + r"|" + _ORDER_WORDS + r".{0,12}(?:查询|状态|详情|列表)")
_PREPARE = re.compile(r"(?:准备|创建|生成|提交|发起|下)(?:.{0,24})?(?:订单|单)|采购下单|下单")
_ANALYSIS = re.compile(r"(?:分析|库存|缺口|补货|报价|供应商|比较|报告|报表|图表)")
_REPORT_NEGATION = re.compile(r"(?:不要|不需要|无需|暂不|先不|不用).{0,8}(?:生成|制作|出具|导出)?(?:采购|分析)?(?:报告|报表)")


def parse_request_intent(message: str):
    from backend.app.agent.harness import extract_request_constraints

    text = message.strip()
    normalized = text.lower()
    constraints = extract_request_constraints(text)
    part_ids = tuple(sorted({item.upper() for item in re.findall(r"(?<![A-Za-z0-9])P\d{3}(?![A-Za-z0-9])", text, re.I)}))
    clauses = [part for part in re.split(r"[，,。；;]", normalized) if part.strip()]
    negated_order_clauses = [part for part in clauses if _NEGATION.search(part)]
    order_negated = bool(negated_order_clauses)
    order_query = any(_QUERY.search(part) for part in clauses)
    order_prepare = any(_PREPARE.search(part) and not _NEGATION.search(part) and not _QUERY.search(part)
                        for part in clauses) and not order_query

    preference_action = None
    preference_values: dict[str, object] = {}
    explicit_remember = "记住" in text and not re.search(r"不要记住|不记住|别记住", text)
    if explicit_remember:
        warehouse = re.search(r"(?:默认)?仓库\s*(W\d{2})", text, re.I)
        supplier = re.search(r"(?:默认)?供应商\s*(S\d{2,3})", text, re.I)
        lead = re.search(r"(?:最多|不超过|交期上限)\s*(\d+)\s*(?:天|日)?", text)
        if warehouse:
            preference_values["default_warehouse"] = warehouse.group(1).upper()
        if supplier:
            preference_values["preferred_supplier"] = supplier.group(1).upper()
        if lead:
            preference_values["max_lead_days"] = int(lead.group(1))
        if preference_values:
            preference_action = "remember"
    elif re.search(r"(?:删除|清空|重置).{0,12}偏好", text):
        preference_action = "delete_all"
    elif re.search(r"(?:查看|查询|显示).{0,8}(?:我的)?偏好|我的偏好", text):
        preference_action = "list"

    supplier_matches = list(re.finditer(r"(?<![A-Za-z0-9])(S\d{2,3})(?![A-Za-z0-9])", text, re.I))
    usable_suppliers = [match.group(1).upper() for match in supplier_matches
        if not re.search(r"(?:不用|不要|不考虑|排除)\s*$", text[max(0, match.start() - 8):match.start()], re.I)]
    constraints["supplier_id"] = usable_suppliers[-1] if usable_suppliers else None
    constraints["clear_preferred_supplier"] = bool(re.search(r"(?:不用|不要|不使用).{0,8}(?:偏好|默认)?供应商", text))
    constraints["clear_max_lead_days"] = bool(re.search(r"(?:不限|不限制|不设).{0,8}(?:交期|天数)", text))

    analysis_text = text
    if order_prepare:
        # Remove only the order-intent clause. A leading prepare command must
        # not create an empty analyst delegation.
        analysis_text = re.sub(r"(?:然后|再|并且|并)?\s*(?:准备|创建|生成|提交|发起|下单|采购下单)[^，,；;。]*", " ", text)
        analysis_text = re.sub(r"[，,；;。\s]+", " ", analysis_text).strip()
    analysis_tasks = (analysis_text,) if analysis_text and _ANALYSIS.search(analysis_text) else ()
    return RequestIntent(
        analysis_tasks=analysis_tasks,
        order_query=order_query,
        order_prepare=order_prepare,
        order_negated=order_negated,
        preference_action=preference_action,
        preference_values=preference_values,
        constraints=constraints,
        part_ids=part_ids,
        report_requested=bool(re.search(r"(?:报告|报表)", text) and not _REPORT_NEGATION.search(text)),
    )
