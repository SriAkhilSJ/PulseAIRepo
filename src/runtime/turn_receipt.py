"""Canonical terminal receipt for one interactive turn (Increment 3).

One typed, replayable object correlates the user request, task classification,
engineering delivery, approvals, mutations, model invocations, verification and
the evidence manifest. It is persisted in the LangGraph checkpoint (state key
``turn_receipt``) and emitted on the terminal bridge frame.

Pure builder: callers provide already-persisted inputs; nothing here performs a
provider call or a second lifecycle.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

SCHEMA_VERSION = 1

# Terminal statuses (the only values the renderer can trust).
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
DENIED = "DENIED"
PARTIAL = "PARTIAL"
NOT_VERIFIED = "NOT_VERIFIED"


def _stable_id(payload: Dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "receipt_id"}
    encoded = json.dumps(body, sort_keys=True, default=str, ensure_ascii=False)
    return "rcpt-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _records(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _terminal_status(
    *,
    delivery: Dict[str, Any],
    state: Dict[str, Any],
    completed: bool,
    cancelled: bool,
    denied: bool,
) -> tuple[str, str]:
    """Return (terminal_status, reason). Never infers success from prose."""
    if denied:
        return DENIED, str(state.get("denial_reason") or "approval_denied")
    if cancelled:
        return CANCELLED, "user_cancelled"

    verdict = str(delivery.get("verdict") or "").upper()
    task_status = str(state.get("task_status") or "").lower()
    run_outcome = str(state.get("run_outcome") or "").lower()

    if verdict == "CANCELLED" or task_status == "cancelled" or run_outcome == "cancelled":
        return CANCELLED, "cancelled"
    if verdict == "PARTIALLY_COMPLETED":
        return PARTIAL, "partially_completed"
    if verdict in {"FAILED", "BLOCKED"}:
        return FAILED, str(delivery.get("user_action_required") or "engineering_failed")
    if delivery:
        if not bool(delivery.get("independently_verified")):
            return NOT_VERIFIED, "engineering_delivery_not_verified"
        if verdict == "COMPLETED":
            return COMPLETED, ""
    if not completed:
        if task_status in {"unverified", "stale"} or run_outcome == "unverified":
            return NOT_VERIFIED, task_status or "unverified"
        return FAILED, str(state.get("failure_reason") or task_status or "turn_incomplete")
    if task_status == "unverified" or run_outcome == "unverified":
        return NOT_VERIFIED, "unverified"
    return COMPLETED, ""


def build_turn_receipt(
    *,
    session_id: str,
    turn_id: str,
    state: Dict[str, Any],
    message: str = "",
    completed: bool = True,
    cancelled: bool = False,
    denied: bool = False,
    evidence: Dict[str, Any] | None = None,
    workspace: str = "",
    started_at: float | None = None,
    completed_at: float | None = None,
) -> Dict[str, Any]:
    """Build the one authoritative terminal result for a turn."""
    state = dict(state or {})
    delivery = dict(state.get("engineering_delivery") or {})
    task_action = str(state.get("task_action") or "")
    classification = (
        "engineering"
        if delivery or task_action == "engineering"
        else "chat"
    )
    status, reason = _terminal_status(
        delivery=delivery, state=state, completed=completed,
        cancelled=cancelled, denied=denied,
    )

    approval_receipts = _records(
        state.get("approval_receipts")
        or delivery.get("approval_receipts")
    )
    mutation_receipts = _records(
        state.get("mutation_receipts")
        or delivery.get("mutation_receipts")
    )
    if not mutation_receipts and workspace:
        try:
            from src.workspace.mutation_broker import WorkspaceMutationBroker

            broker = WorkspaceMutationBroker.get_instance(str(workspace))
            task_key = str(delivery.get("task_id") or session_id or "default")
            for record in broker.ledger.get_records(task_key):
                mutation_receipts.append({
                    "operation_id": getattr(record, "operation_id", ""),
                    "file_path": getattr(record, "file_path", ""),
                    "operation_type": str(
                        getattr(getattr(record, "operation_type", ""), "value",
                                getattr(record, "operation_type", ""))
                    ),
                    "status": str(
                        getattr(getattr(record, "status", ""), "value",
                                getattr(record, "status", ""))
                    ),
                    "original_hash": getattr(record, "original_hash", None),
                    "new_hash": getattr(record, "new_hash", None),
                    "approval_ref": str(getattr(record, "approval_ref", "") or "")[:12],
                })
        except Exception:
            pass

    invocation_records: List[Dict[str, Any]] = []
    invocation_summary: Dict[str, Any] = {}
    if workspace:
        try:
            from src.finops.invocation_context import (
                latest_invocations,
                read_invocations,
                summarize_invocations,
            )

            all_records = read_invocations(workspace)
            invocation_records = latest_invocations([
                record for record in all_records
                if str(record.get("session_id") or "") == str(session_id)
                and (
                    not turn_id
                    or str(record.get("turn_id") or "") in {"", str(turn_id)}
                    or str(record.get("task_id") or "") == str(session_id)
                )
            ])
            invocation_summary = summarize_invocations(invocation_records)
        except Exception:
            invocation_records = []
            invocation_summary = {}

    changed_files = list(delivery.get("files_changed") or [])
    if not changed_files:
        changed_files = sorted({
            str(item.get("file_path") or "")
            for item in mutation_receipts
            if item.get("file_path")
        })

    usage_cost_inr = delivery.get("cost_inr")
    usage_cost_usd = delivery.get("cost_usd")
    cost_unknown = bool(delivery.get("cost_unknown")) or any(
        bool(record.get("cost_unknown")) for record in invocation_records
    )
    if cost_unknown:
        usage_cost_inr = None
        usage_cost_usd = None
    else:
        if usage_cost_inr is None:
            usage_cost_inr = sum(float(r.get("actual_cost_inr") or 0.0) for r in invocation_records)
        if usage_cost_usd is None:
            usage_cost_usd = sum(float(r.get("actual_cost_usd") or 0.0) for r in invocation_records)

    evidence_payload = dict(evidence or {})
    receipt: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "session_id": str(session_id or ""),
        "turn_id": str(turn_id or ""),
        "task_id": str(delivery.get("task_id") or state.get("task_id") or ""),
        "task_classification": classification,
        "terminal_status": status,
        "reason": reason,
        "message": str(message or "")[:4000],
        "engineering_verdict": str(delivery.get("verdict") or ""),
        "verification_status": (
            "verified" if delivery.get("independently_verified")
            else ("not_verified" if delivery else str(state.get("verification_status") or ""))
        ),
        "delivery": {
            "what_was_requested": delivery.get("what_was_requested", ""),
            "what_was_implemented": list(delivery.get("what_was_implemented") or []),
            "remaining_limitations": list(delivery.get("remaining_limitations") or []),
            "production_readiness_verdict": delivery.get("production_readiness_verdict"),
            "contract": dict(delivery.get("contract") or {}),
            "requirement_verification": list(
                delivery.get("requirement_verification") or []
            ),
            "repair_attempts": list(delivery.get("repair_attempts") or []),
            "generation_recoveries": list(delivery.get("generation_recoveries") or []),
        },
        "plan": list(state.get("plan") or []),
        "changed_files": changed_files,
        "tests": {
            "executed": list(delivery.get("tests_executed") or []),
            "passed": list(delivery.get("tests_passed") or []),
            "failed": list(delivery.get("tests_failed") or []),
            "evidence": dict(delivery.get("test_evidence") or {}),
        },
        "approval_receipts": approval_receipts,
        "mutation_receipts": mutation_receipts,
        "model_invocations": {
            "ids": [str(r.get("invocation_id") or "") for r in invocation_records],
            "summary": invocation_summary,
        },
        "usage": {
            "cost_inr": None if usage_cost_inr is None else float(usage_cost_inr),
            "cost_usd": None if usage_cost_usd is None else float(usage_cost_usd),
            "cost_unknown": bool(cost_unknown),
            "token_usage": dict(delivery.get("token_usage") or state.get("token_usage") or {}),
            "duration_seconds": float(delivery.get("duration_seconds") or 0.0),
        },
        "evidence": evidence_payload,
        "timing": {
            "started_at": started_at,
            "completed_at": completed_at,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "langgraph",
    }
    receipt["receipt_id"] = _stable_id(receipt)
    return receipt


def enrich_receipt(
    receipt: Dict[str, Any],
    *,
    evidence: Dict[str, Any] | None = None,
    denied: bool | None = None,
    reason: str | None = None,
) -> Dict[str, Any]:
    """Attach the bridge evidence manifest and re-seal the receipt id."""
    enriched = dict(receipt or {})
    if evidence is not None:
        enriched["evidence"] = dict(evidence)
    if denied is True:
        enriched["terminal_status"] = DENIED
        enriched["reason"] = reason or enriched.get("reason") or "approval_denied"
    elif reason is not None and not enriched.get("reason"):
        enriched["reason"] = reason
    enriched["receipt_id"] = _stable_id(enriched)
    return enriched
