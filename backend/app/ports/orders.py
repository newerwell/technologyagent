"""P04 写入端口；订单事实只接受已校验草稿和事务操作标识。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pymongo.asynchronous.client_session import AsyncClientSession

from backend.app.contracts.domain import OrderDraft, PurchaseOrder


class OrderWriter(Protocol):
    async def create_from_draft(
        self, draft: OrderDraft, operation_id: str, now: datetime,
        *, session: AsyncClientSession,
    ) -> PurchaseOrder: ...
