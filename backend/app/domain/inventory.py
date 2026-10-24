"""P04 库存变更领域规则：采购订单只增加在途，不影响现有在手量。"""

from __future__ import annotations

from backend.app.contracts.common import AppError, ErrorCodes
from backend.app.contracts.domain import Inventory


def inbound_after_purchase(inventory: Inventory, quantity: int) -> tuple[int, int]:
    if quantity < 1:
        raise AppError(ErrorCodes.VALIDATION_ERROR, "quantity must be positive", http_status=422)
    return inventory.inbound + quantity, inventory.version + 1
