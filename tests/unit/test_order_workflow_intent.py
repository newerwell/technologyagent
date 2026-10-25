"""Deterministic boundary checks for live P04 model intent parsing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.contracts.agent import ModelDelta, ModelToolCall
from backend.app.contracts.common import AppError, RequestContext
from backend.app.agent.budget import RunBudget
from backend.app.services.order_workflows import OrderWorkflowService


class _Model:
    def __init__(self, arguments: str) -> None:
        self.arguments = arguments

    async def stream(self, _messages, _tools, _ctx):
        yield ModelDelta(kind="tool_call", tool_call=ModelToolCall(
            id="call-1", name="order_draft_prepare", arguments="", index=0,
        ))
        for fragment in (self.arguments[:12], self.arguments[12:]):
            yield ModelDelta(kind="tool_call", tool_call=ModelToolCall(
                index=0, arguments=fragment,
            ))


class _Catalog:
    async def get_part(self, part_id):
        return SimpleNamespace(id=part_id, active=True)

    async def search_parts(self, name, _page):
        return SimpleNamespace(records=[SimpleNamespace(id="P001")] if name == "刹车片" else [])


@pytest.mark.asyncio
async def test_live_intent_reassembles_fragments_and_maps_only_catalog_part():
    service = OrderWorkflowService(None, None, None, None, None,
        model=_Model('{"part_name":"刹车片","max_lead_days":7}'),
        catalog=_Catalog(), model_mode="live")
    service._drafts = SimpleNamespace(validate_prepare=AsyncMock())

    request = await service._live_draft_request(
        "刹车片补货，7天内到货", RequestContext(owner_id="owner", request_id="req"), RunBudget("run"),
    )

    assert request.part_ids == ["P001"]
    assert request.max_lead_days == 7
    assert request.warehouse_id is None


@pytest.mark.asyncio
async def test_live_intent_revalidates_explicit_part_id_without_requiring_analyst_evidence():
    service = OrderWorkflowService(None, None, None, None, None,
        model=_Model('{"part_id":"P001","max_lead_days":7,"warehouse_id":"W01"}'),
        catalog=_Catalog(), model_mode="live")
    service._drafts = SimpleNamespace(validate_prepare=AsyncMock())

    request = await service._live_draft_request(
        "分析补货后准备 P001 在 W01 的订单，7天内到货",
        RequestContext(owner_id="owner", request_id="req"), RunBudget("run"),
        evidence_refs=[],
    )

    assert request.part_ids == ["P001"]
    assert request.warehouse_id == "W01"
    assert request.max_lead_days == 7
    service._drafts.validate_prepare.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_intent_rejects_model_part_id_outside_user_request():
    service = OrderWorkflowService(None, None, None, None, None,
        model=_Model('{"part_id":"P002","max_lead_days":7}'),
        catalog=_Catalog(), model_mode="live")
    service._drafts = SimpleNamespace(validate_prepare=AsyncMock())

    with pytest.raises(AppError):
        await service._live_draft_request(
            "准备 P001 的订单，7天内到货",
            RequestContext(owner_id="owner", request_id="req"), RunBudget("run"),
            evidence_refs=[],
        )


@pytest.mark.asyncio
async def test_live_intent_keeps_all_explicitly_requested_parts_or_rejects_silent_omission():
    service = OrderWorkflowService(None, None, None, None, None,
        model=_Model('{"part_ids":["P001","P002"],"max_lead_days":7}'),
        catalog=_Catalog(), model_mode="live")
    service._drafts = SimpleNamespace(validate_prepare=AsyncMock())
    result = await service._live_draft_request("准备P001和P002的订单，7天内到货",
        RequestContext(owner_id="owner", request_id="req"), RunBudget("run"))
    assert set(result.part_ids) == {"P001", "P002"}

    service._model = _Model('{"part_id":"P001","max_lead_days":7}')
    with pytest.raises(AppError, match="model omitted or added"):
        await service._live_draft_request("准备P001和P002的订单，7天内到货",
            RequestContext(owner_id="owner", request_id="req"), RunBudget("run"))


@pytest.mark.asyncio
async def test_explicit_supplier_and_effective_request_fields_override_model_intent():
    service = OrderWorkflowService(None, None, None, None, None,
        model=_Model('{"part_id":"P001","max_lead_days":7,"warehouse_id":"W01"}'),
        catalog=_Catalog(), model_mode="live")
    service._drafts = SimpleNamespace(validate_prepare=AsyncMock())
    result = await service._live_draft_request("本轮只用S02，不用S01；准备P001在W02订单，7天内到货",
        RequestContext(owner_id="owner", request_id="req"), RunBudget("run"),
        request_constraints={"warehouse_ids": ["W02"], "supplier_id": "S02", "max_lead_days": 7})
    assert result.supplier_id == "S02"
    assert result.warehouse_id == "W02"


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    "not-json",
    '{"part_name":"unknown","max_lead_days":7}',
    '{"part_name":"刹车片","max_lead_days":"seven"}',
])
async def test_live_intent_rejects_invalid_json_unknown_part_and_bad_fields(arguments):
    service = OrderWorkflowService(None, None, None, None, None,
        model=_Model(arguments), catalog=_Catalog(), model_mode="live")
    service._drafts = SimpleNamespace(validate_prepare=AsyncMock())

    with pytest.raises(AppError):
        await service._live_draft_request(
            "刹车片补货，7天内到货", RequestContext(owner_id="owner", request_id="req"), RunBudget("run"),
        )
