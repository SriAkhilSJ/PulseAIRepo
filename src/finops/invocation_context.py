"""Invocation identity and the authoritative provider-invocation ledger.

Every real provider call must be attributable and financially governed. The
orchestrator already reserves/settles through the task FinOps governor; this
module lets every call (task, auxiliary, background) carry the same identity and
write one record that the acceptance guard and session reports can reconcile.

A scope is set around the actual ``invoke``. In acceptance mode the provider
proxy refuses to run without one, so a hidden call cannot reach the network.
"""
from __future__ import annotations

from src.runtime.app_paths import app_data_root

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


class UnaccountedProviderCall(RuntimeError):
    """A provider invocation was attempted without a financial reservation."""


_CURRENT_SCOPE: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "crusor_invocation_scope", default=None,
)
_CURRENT_SUBMISSION: ContextVar[str] = ContextVar(
    "crusor_submission_id", default="",
)
_LEDGER_LOCK = threading.Lock()


def set_submission_id(submission_id: str | None):
    """Bind the current thread/context to one submission id."""
    return _CURRENT_SUBMISSION.set(str(submission_id or ""))


def reset_submission_id(token) -> None:
    _CURRENT_SUBMISSION.reset(token)


def current_submission_id() -> str:
    return _CURRENT_SUBMISSION.get() or os.environ.get("CRUSORAI_SUBMISSION_ID", "")


def new_invocation_id() -> str:
    """Canonical invocation id format, shared with the model gateway."""
    return f"inv-{uuid.uuid4().hex[:16]}"


def current_scope() -> Optional[Dict[str, Any]]:
    return _CURRENT_SCOPE.get()


@contextmanager
def invocation_scope(
    *,
    subsystem: str,
    reservation_id: str,
    operation_type: str,
    task_id: str = "",
    provider: str = "",
    model: str = "",
    purpose: str = "",
    submission_id: str = "",
) -> Iterator[Dict[str, Any]]:
    """Mark the next provider call as financially reserved and attributable."""
    scope = {
        "managed": True,
        "subsystem": subsystem,
        "reservation_id": reservation_id,
        "operation_type": operation_type,
        "task_id": task_id,
        "provider": provider,
        "model": model,
        "purpose": purpose,
        "submission_id": submission_id or current_submission_id(),
    }
    token = _CURRENT_SCOPE.set(scope)
    try:
        yield scope
    finally:
        _CURRENT_SCOPE.reset(token)


def assert_governed_for_acceptance() -> None:
    """Fail closed in acceptance mode when no reservation scope is active."""
    try:
        from src.llm.acceptance_guard import acceptance_active

        active = acceptance_active()
    except Exception:
        active = False
    if active and current_scope() is None:
        raise UnaccountedProviderCall(
            "acceptance mode: provider invocation attempted without a financial "
            "reservation scope; refusing the request before dispatch"
        )


def ledger_path(workspace: str | Path) -> Path:
    from src.runtime.app_paths import app_data_root

    return app_data_root(workspace) / "finops" / "provider_invocations.jsonl"


def record_invocation(workspace: str | Path, record: Dict[str, Any]) -> str:
    """Append one invocation record (authoritative attribution, not cost truth)."""
    path = ledger_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "invocation_id": record.get("invocation_id") or new_invocation_id(),
        "run_id": record.get("run_id") or os.environ.get("CRUSORAI_ACCEPTANCE_RUN_ID", ""),
        "session_id": record.get("session_id") or os.environ.get("CRUSORAI_SESSION_ID", ""),
        "turn_id": record.get("turn_id") or os.environ.get("CRUSORAI_TURN_ID", ""),
        "submission_id": record.get("submission_id") or current_submission_id(),
        "workspace_id": record.get("workspace_id") or os.environ.get("CRUSORAI_WORKSPACE_ID", ""),
        "parent_invocation_id": record.get("parent_invocation_id", ""),
        "task_id": record.get("task_id", ""),
        "subsystem": record.get("subsystem", "unknown"),
        "operation_type": record.get("operation_type", "unknown"),
        "provider": record.get("provider", ""),
        "model": record.get("model", ""),
        "attempt_number": int(record.get("attempt_number") or 1),
        "retry_count": int(record.get("retry_count") or 0),
        "attempts": list(record.get("attempts") or []),
        "latency_ms": record.get("latency_ms"),
        "provider_reported_cost": record.get("provider_reported_cost"),
        "estimated_cost_inr": record.get("estimated_cost_inr"),
        "pricing_version": record.get("pricing_version", ""),
        "cost_unknown": record.get("cost_unknown"),
        "reservation_id": record.get("reservation_id", ""),
        "usage_record_id": record.get("usage_record_id", ""),
        "settlement_id": record.get("settlement_id", ""),
        "status": record.get("status", "unknown"),
        "requested_output_tokens": (
            int(record["requested_output_tokens"])
            if record.get("requested_output_tokens") is not None else None
        ),
        "finish_reason": record.get("finish_reason", ""),
        "response_received_at": (
            float(record["response_received_at"])
            if record.get("response_received_at") is not None else None
        ),
        "usage_receipt_present": record.get("usage_receipt_present"),
        "input_tokens": int(record.get("input_tokens") or 0),
        "output_tokens": int(record.get("output_tokens") or 0),
        "cached_tokens": int(record.get("cached_tokens") or 0),
        "actual_cost_inr": (
            None if record.get("cost_unknown") or record.get("actual_cost_inr") is None
            else float(record.get("actual_cost_inr"))
        ),
        "actual_cost_usd": (
            None if record.get("cost_unknown") or record.get("actual_cost_usd") is None
            else float(record.get("actual_cost_usd"))
        ),
        "started_at": float(record.get("started_at") or time.time()),
        "completed_at": float(record.get("completed_at") or time.time()),
        "purpose": record.get("purpose", ""),
        "mode": record.get("mode", "provider"),
        "error": record.get("error", ""),
    }
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with _LEDGER_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return payload["invocation_id"]


def read_invocations(workspace: str | Path) -> list[Dict[str, Any]]:
    path = ledger_path(workspace)
    if not path.exists():
        return []
    records: list[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return records


def latest_invocations(records: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Collapse replayed/updated ledger lines to one row per invocation id.

    The ledger is append-only: a retry or a later settlement can append a new
    line for the same physical invocation. Counting every line would double
    count usage and cost, so callers report the latest state once. Distinct
    invocation ids (genuine retries) stay separate and traceable.
    """
    latest: Dict[str, Dict[str, Any]] = {}
    order: list[str] = []
    for index, record in enumerate(records):
        key = str(record.get("invocation_id") or "")
        if not key:
            key = f"unidentified-{index}"
        if key not in latest:
            order.append(key)
        latest[key] = record
    return [latest[key] for key in order]


def summarize_invocations(records: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Reports at invocation/task/session/daily level from one ledger."""
    records = latest_invocations(records)
    by_subsystem: Dict[str, Dict[str, Any]] = {}
    by_model: Dict[str, Dict[str, Any]] = {}
    by_task: Dict[str, Dict[str, Any]] = {}
    by_session: Dict[str, Dict[str, Any]] = {}
    by_day: Dict[str, Dict[str, Any]] = {}
    statuses: Dict[str, int] = {}
    total = 0.0
    total_tokens = 0
    total_latency_ms = 0.0
    unknown_cost_calls = 0

    def _bucket(store, key):
        return store.setdefault(key or "unknown", {
            "calls": 0, "cost_inr": 0.0, "input_tokens": 0,
            "output_tokens": 0, "latency_ms": 0.0, "cost_unknown_calls": 0,
        })

    for record in records:
        cost = float(record.get("actual_cost_inr") or 0.0)
        total += cost
        in_tok = int(record.get("input_tokens") or 0)
        out_tok = int(record.get("output_tokens") or 0)
        total_tokens += in_tok + out_tok
        latency = float(record.get("latency_ms") or 0.0)
        total_latency_ms += latency
        cost_unknown = bool(record.get("cost_unknown")) or cost == 0.0
        if cost_unknown:
            unknown_cost_calls += 1

        for store, key in (
            (by_subsystem, str(record.get("subsystem") or "unknown")),
            (by_task, str(record.get("task_id") or "unassigned")),
            (by_session, str(record.get("session_id") or "unassigned")),
        ):
            bucket = _bucket(store, key)
            bucket["calls"] += 1
            bucket["cost_inr"] = round(bucket["cost_inr"] + cost, 8)
            bucket["input_tokens"] += in_tok
            bucket["output_tokens"] += out_tok
            bucket["latency_ms"] = round(bucket["latency_ms"] + latency, 3)
            bucket["cost_unknown_calls"] += 1 if cost_unknown else 0

        completed = float(record.get("completed_at") or 0.0)
        if completed:
            day = time.strftime("%Y-%m-%d", time.gmtime(completed))
        else:
            day = "unknown"
        bucket = _bucket(by_day, day)
        bucket["calls"] += 1
        bucket["cost_inr"] = round(bucket["cost_inr"] + cost, 8)
        bucket["input_tokens"] += in_tok
        bucket["output_tokens"] += out_tok
        bucket["latency_ms"] = round(bucket["latency_ms"] + latency, 3)
        bucket["cost_unknown_calls"] += 1 if cost_unknown else 0

        model = str(record.get("model") or "unknown")
        model_bucket = by_model.setdefault(model, {"calls": 0, "cost_inr": 0.0})
        model_bucket["calls"] += 1
        model_bucket["cost_inr"] = round(model_bucket["cost_inr"] + cost, 8)
        status = str(record.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1

    return {
        "total_calls": len(records),
        "total_cost_inr": round(total, 8),
        "total_tokens": total_tokens,
        "total_latency_ms": round(total_latency_ms, 3),
        "unknown_cost_calls": unknown_cost_calls,
        "by_subsystem": by_subsystem,
        "by_model": by_model,
        "by_task": by_task,
        "by_session": by_session,
        "by_day": by_day,
        "statuses": statuses,
        "settled_calls": statuses.get("settled", 0),
        "uncertain_calls": statuses.get("uncertain", 0),
        "released_calls": statuses.get("released", 0),
        "local_fallback_calls": statuses.get("local_fallback", 0),
    }
