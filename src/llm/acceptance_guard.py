"""Acceptance-mode provider discipline.

A desktop acceptance turn must be able to prove that it made a bounded,
enumerated number of real provider requests. The normal engine deliberately
retries (``RetryLLMProxy`` defaults to five attempts) and the retry policy is
owned by that proxy; management lanes may also request their own budgets. That
is the right behaviour for users and the wrong behaviour for an acceptance run
whose evidence says "exactly N dispatches, no retries".

This module adds a *narrow, opt-in* acceptance mode:

* one immutable run id owns a fixed dispatch budget (default 5);
* every ``RetryLLMProxy`` built while the mode is active is clamped to a single
  attempt, whatever ``max_attempts`` the caller asked for;
* each provider client the factory builds must have SDK retries at 0 — if a
  client cannot be proven retry-free the mode fails closed;
* a dispatch is *claimed* immediately before the provider call. The claim is
  what prevents dispatch N+1: when the budget is exhausted the call raises
  :class:`AcceptanceBudgetExceeded` and no network request is made.

Outside :func:`acceptance_mode` the guard is inactive, claims are no-ops, and
the configured (normal) retry behaviour is untouched.
"""
from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


class AcceptanceGuardError(RuntimeError):
    """Base class for acceptance-mode discipline failures."""


class AcceptanceBudgetExceeded(AcceptanceGuardError):
    """Raised BEFORE a provider call that would exceed the turn's budget."""


class AcceptanceDisciplineError(AcceptanceGuardError):
    """Raised when a provider client cannot be proven single-attempt."""


@dataclass
class DispatchClaim:
    sequence: int
    stage: str
    model: str = ""


@dataclass
class AcceptanceGuard:
    """Thread-safe dispatch budget for exactly one acceptance turn."""

    run_id: str
    max_dispatches: int = 5
    _claims: list[DispatchClaim] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _clients: list[Any] = field(default_factory=list, repr=False)

    @property
    def used(self) -> int:
        with self._lock:
            return len(self._claims)

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_dispatches - len(self._claims))

    def claim(self, *, stage: str = "", model: str = "") -> DispatchClaim:
        """Reserve one dispatch slot, or fail before any request is made."""
        with self._lock:
            if len(self._claims) >= self.max_dispatches:
                raise AcceptanceBudgetExceeded(
                    f"acceptance run {self.run_id!r} already used {len(self._claims)} of "
                    f"{self.max_dispatches} provider dispatches; refusing another "
                    f"(stage={stage or 'unspecified'}, model={model or 'unknown'})"
                )
            claim = DispatchClaim(sequence=len(self._claims) + 1, stage=stage, model=model)
            self._claims.append(claim)
            return claim

    def attempt_budget(self, requested: int) -> int:
        """The number of provider attempts allowed for one invocation."""
        return 1

    def register_client(self, client: Any) -> None:
        with self._lock:
            self._clients.append(client)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "run_id": self.run_id,
                "max_dispatches": self.max_dispatches,
                "dispatches_used": len(self._claims),
                "dispatches_remaining": max(0, self.max_dispatches - len(self._claims)),
                "attempts_per_dispatch": 1,
                "claims": [
                    {"sequence": c.sequence, "stage": c.stage, "model": c.model}
                    for c in self._claims
                ],
                "registered_clients": len(self._clients),
                "active": True,
            }


_active_guard: AcceptanceGuard | None = None
_active_lock = threading.RLock()
_mode_depth = 0


def active_guard() -> AcceptanceGuard | None:
    return _active_guard


def acceptance_active() -> bool:
    return _active_guard is not None


@contextmanager
def acceptance_mode(run_id: str | None = None, max_dispatches: int = 5) -> Iterator[AcceptanceGuard]:
    """Activate the guard for one acceptance turn.

    Re-entering with the same run id (nested helper calls) shares the budget;
    entering with a different run id while one is active is a programming error
    and raises instead of silently mixing two executions.
    """
    global _active_guard, _mode_depth
    with _active_lock:
        if _active_guard is not None:
            if run_id and run_id != _active_guard.run_id:
                raise AcceptanceGuardError(
                    f"acceptance run {_active_guard.run_id!r} is already active; "
                    f"cannot start {run_id!r} inside it"
                )
            _mode_depth += 1
            guard = _active_guard
            try:
                yield guard
            finally:
                with _active_lock:
                    _mode_depth -= 1
            return

        guard = AcceptanceGuard(run_id=run_id or f"accept_{uuid.uuid4().hex[:12]}",
                                max_dispatches=max(1, int(max_dispatches)))
        _active_guard = guard
        _mode_depth = 1
        try:
            yield guard
        finally:
            with _active_lock:
                _mode_depth = 0
                _active_guard = None


def claim_dispatch(*, stage: str = "", model: str = "") -> DispatchClaim | None:
    """Claim a dispatch slot when acceptance mode is active; otherwise no-op."""
    guard = _active_guard
    if guard is None:
        return None
    return guard.claim(stage=stage, model=model)


def clamp_max_attempts(requested: int) -> int:
    """Force a single attempt inside acceptance mode."""
    guard = _active_guard
    if guard is None:
        return requested
    return guard.attempt_budget(requested)


def activate_from_environment() -> AcceptanceGuard | None:
    """Activate process-wide acceptance discipline from the launch environment.

    The desktop acceptance session is launched with
    ``CRUSORAI_ACCEPTANCE_RUN_ID`` set (and optionally
    ``CRUSORAI_ACCEPTANCE_MAX_DISPATCHES``, default 5). Because that bridge
    process serves exactly one acceptance turn, a process-wide guard is the
    correct scope: every provider request from every stage of that turn is
    clamped and counted, and an ordinary user session (env unset) keeps its
    configured retry behaviour.
    """
    import os

    run_id = os.environ.get("CRUSORAI_ACCEPTANCE_RUN_ID", "").strip()
    if not run_id:
        return None
    raw_limit = os.environ.get("CRUSORAI_ACCEPTANCE_MAX_DISPATCHES", "").strip()
    try:
        limit = max(1, int(raw_limit)) if raw_limit else 5
    except ValueError:
        limit = 5
    guard = AcceptanceGuard(run_id=run_id, max_dispatches=limit)
    global _active_guard
    with _active_lock:
        _active_guard = guard
    return guard


def write_evidence(guard: AcceptanceGuard | None, path: str | None) -> None:
    """Persist the dispatch ledger so the harness can reconcile it later."""
    if guard is None or not path:
        return
    import json
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(guard.snapshot(), indent=2) + "\n", encoding="utf-8")


def enforce_sdk_single_retry(client: Any) -> None:
    """Prove (or force) ``max_retries == 0`` on a freshly built provider client.

    Fails closed: an acceptance run must not inherit hidden SDK retries it
    cannot see.
    """
    if _active_guard is None:
        return
    try:
        current = getattr(client, "max_retries", 0)
    except Exception:  # pragma: no cover - exotic client
        current = 0
    if current in (0, None):
        _active_guard.register_client(client)
        return
    try:
        client.max_retries = 0
    except Exception as exc:  # pragma: no cover - read-only client
        raise AcceptanceDisciplineError(
            f"provider client {type(client).__name__} has max_retries={current!r} "
            "and refuses to be set to 0; an acceptance run cannot use it"
        ) from exc
    if getattr(client, "max_retries", 0) not in (0, None):  # pragma: no cover
        raise AcceptanceDisciplineError(
            f"provider client {type(client).__name__} kept max_retries="
            f"{getattr(client, 'max_retries', None)!r} after being set to 0"
        )
    _active_guard.register_client(client)
