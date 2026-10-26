"""Conservative recovery decisions for persisted runs and business operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    retry_business_write: bool
    reason: str


def classify_recovery(run: dict[str, Any], operations: list[dict[str, Any]]) -> RecoveryDecision:
    """Choose a safe next action; never infer that an uncertain write did not commit."""
    status = run.get("status")
    if status in {"completed", "failed", "cancelled"}:
        return RecoveryDecision("terminal", False, "run is already terminal")
    if status == "waiting_input" and run.get("pending_interrupt"):
        return RecoveryDecision("preserve_checkpoint", False, "human decision is durable")
    for operation in operations:
        op_status = operation.get("status")
        if op_status == "succeeded":
            return RecoveryDecision("return_committed_result", False, "operation already committed")
        if op_status == "outcome_unknown":
            return RecoveryDecision("reconcile_external", False, "write outcome requires reconciliation")
        if op_status == "processing":
            return RecoveryDecision("inspect_lease", False, "active or expired lease requires inspection")
    if run.get("checkpoint_exists"):
        return RecoveryDecision("resume_checkpoint", False, "resume from persisted graph state")
    if status in {"created", "running"}:
        return RecoveryDecision("mark_interrupted", False, "no safe checkpoint or business result exists")
    return RecoveryDecision("manual_review", False, "unrecognized run state")
