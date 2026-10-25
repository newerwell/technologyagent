"""最多两次、不可递归的专家派发；调用方传入同一父RunBudget。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend.app.agent.budget import RunBudget
from backend.app.contracts.agent import ExecutionOutcome
from backend.app.contracts.delegation import DelegationRequest, DelegationResult


class SpecialistDispatcher:
    def __init__(self, max_delegations: int = 2):
        self.max_delegations = min(2, max(0, max_delegations))
        self._count = 0

    async def dispatch(self, *, owner_id: str, run_id: str, specialist: str, task: str,
                       data_scope: dict[str, Any], evidence_refs: list[dict[str, Any]],
                       preferences: dict[str, Any], parent_call_id: str, budget: RunBudget,
                       invoke: Callable[[DelegationRequest], Awaitable[ExecutionOutcome]],
                       recursive: bool = False) -> ExecutionOutcome:
        if recursive:
            return ExecutionOutcome(status="failed", summary="专家委派不支持递归。", error_code="DELEGATION_RECURSION")
        if self._count >= self.max_delegations:
            return ExecutionOutcome(status="failed", summary="父run专家委派次数已达上限。", error_code="DELEGATION_LIMIT")
        self._count += 1
        await budget.check_cancelled()
        await budget.check_active()
        request = DelegationRequest(owner_id=owner_id, run_id=run_id, specialist=specialist,
            task=task, data_scope=data_scope, evidence_refs=evidence_refs,
            preferences=preferences, parent_call_id=parent_call_id)
        outcome = await invoke(request)
        result = DelegationResult(
            status=outcome.status if outcome.status in {"completed", "failed", "waiting_input"} else "failed",
            summary=outcome.summary, evidence_refs=outcome.evidence,
            artifact_ids=[str(item["id"]) for item in outcome.evidence if item.get("entity") == "artifact" and item.get("id")],
            pending_interrupt=outcome.pending_interrupt,
            errors=[outcome.error_code] if outcome.error_code else [],
        )
        if result.status != "completed":
            return outcome.model_copy(update={"summary": result.summary})
        return outcome
