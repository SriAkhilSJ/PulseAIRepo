"""Pinned summary route — hermes-agent parity (Floor-2 Phase A).

Ported from hermes-agent ``agent/context_compressor.py`` (``_SUMMARY_ROUTE_PIN``,
``pin_summary_route``, ``take_pinned_summary_route``, ``_PINNED_ROUTE_FIELDS``),
re-read at upstream ``4dac5f2``, 2026-09.

THE PROBLEM IT SOLVES (their #78981, verbatim logic): the summary call normally
resolves its provider/model from settings (``AUX_LLM_PROVIDER``/``AUX_LLM_MODEL``
here, ``auxiliary.compression`` there). One caller needs to override that for a
SINGLE attempt: after a progress-aware timeout aborts a stalled summary, a retry
re-runs compression with the route pinned to a configured fallback entry.
Nothing raised out of the stalled call, so the aux client's own fallback
handling — which only runs from its exception path — never saw that failure.

WHY A CONTEXTVAR, NOT AN ATTRIBUTE: the aborted worker is detached and still
alive on the pool, and the compactor object is shared with it. Context is copied
per worker, so the pin reaches the retry's whole synchronous call chain and
cannot leak into the stalled attempt or any unrelated auxiliary call.

SINGLE USE BY DESIGN: ``take_pinned_summary_route`` consumes the pin. A summary
route that fails falls back to the main-model path; re-issuing the pinned route
there would spend a second full deadline on the backend that just failed.
"""
from __future__ import annotations

import contextlib
import contextvars
from typing import Any, Callable, Dict, Optional

# call_llm kwargs a pinned route may set. ``timeout`` lets a fallback entry
# keep its own deadline instead of inheriting one the primary already burned.
PINNED_ROUTE_FIELDS: tuple[str, ...] = (
    "provider",
    "model",
    "base_url",
    "api_key",
    "api_mode",
    "timeout",
)

_SUMMARY_ROUTE_PIN: contextvars.ContextVar[Optional[Dict[str, Any]]] = (
    contextvars.ContextVar("pulseai_summary_route_pin", default=None)
)


@contextlib.contextmanager
def pin_summary_route(route: Optional[Dict[str, Any]]):
    """Pin the next summary LLM call in this context to an explicit route.

    ``route`` is a mapping of :data:`PINNED_ROUTE_FIELDS`; ``None`` is a no-op
    passthrough so callers can wire it unconditionally. Re-entrant-safe:
    restores the previous pin on exit.
    """
    token = _SUMMARY_ROUTE_PIN.set(route if isinstance(route, dict) else None)
    try:
        yield
    finally:
        _SUMMARY_ROUTE_PIN.reset(token)


def take_pinned_summary_route() -> Optional[Dict[str, Any]]:
    """Read and consume the pinned summary route, if one is installed.

    Single use by design (see module docstring). Returns ``None`` when no pin
    is installed.
    """
    route = _SUMMARY_ROUTE_PIN.get()
    if route is None:
        return None
    _SUMMARY_ROUTE_PIN.set(None)
    return route


def peek_pinned_summary_route() -> Optional[Dict[str, Any]]:
    """Read the pin WITHOUT consuming it (telemetry/diagnostics only)."""
    return _SUMMARY_ROUTE_PIN.get()


def aux_llm_for_route(aux_llm_getter: Callable[[], Any], route: Optional[Dict[str, Any]]) -> Any:
    """Resolve the aux summary LLM: the pinned route when installed, else the
    caller's normal getter (settings-driven). Only the fields that matter to
    Pulse's ``RequestScopedAuxLLM(provider, model)`` facade are honored; the
    rest (``base_url``/``api_key``/``api_mode``/``timeout``) are validated but
    delegated to the facade, which owns transports."""
    if not route:
        return aux_llm_getter()
    provider = route.get("provider") or None
    model = route.get("model") or None
    if not provider and not model:
        return aux_llm_getter()
    from src.llm.factory import RequestScopedAuxLLM

    return RequestScopedAuxLLM(provider, model)
