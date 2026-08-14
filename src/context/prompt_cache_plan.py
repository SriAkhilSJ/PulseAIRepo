"""
Prompt-cache plan (P1, hermes illegal-copy of agent/prompt_caching.py)
======================================================================

Hermes treats per-conversation prompt caching as sacred: a long-lived
conversation reuses a cached prefix every turn, and anything that mutates
past context, swaps toolsets, or rebuilds the system prompt mid-conversation
invalidates that cache and multiplies the user's cost. Their
``prompt_caching.py`` is the planner: choose the stable-prefix byte range,
drop cache breakpoints on it, and re-decide per provider (failover must
never re-dress a stale plan).

PulseAI already holds the prerequisites:
  * a byte-stable static prefix by construction (toolsets resolver is
    deterministic per task, ``test_toolsets.py::test_resolver_is_deterministic_per_task``);
  * the D19 audit proving the prefix holds through the history boundary
    (``prompt_cache_audit.py``);
  * the failover stripping net in ``cache_preservation.py``.

This module is the missing planner: it marks the stable head of an outgoing
message list with cache breakpoints, provider-conditional, graceful no-op.

Safety rail (the reason it is DEFAULT OFF):
  some OpenAI-compatible endpoints (the Sarvam 105B conversations route on
  this box) reject unknown content-block fields; a malformed request could
  4xx the whole turn. So markers are emitted ONLY when the caller opts in
  (``PULSEAI_PROMPT_CACHE=1``) AND the provider/model is allowlisted. The
  module itself never raises and never touches provider framing — it only
  decorates ``additional_kwargs`` on BaseMessages, which the failover
  stripper already knows how to remove.

All functions are pure; nothing here calls an LLM.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

# Providers/Hostnames verified (or explicitly opted) to honor cache markers.
_DEFAULT_CACHEABLE_PROVIDERS = frozenset(
    {
        "openai",
        "groq",  # Anthropic-style cache_control breakpoints are honored
        "gemini",  # caching is native via cachedContent; markers no-op
    }
)

# 4 breakpoints, mirroring hermes' default layout (their prompt_caching.py).
_CACHE_BREAKPOINTS = 4
_TTL = "5m"


def _cache_enabled(provider: str | None = None, model: str | None = None) -> bool:
    """Opt-in switch: env must enable, and the provider must be allowlisted."""
    val = os.environ.get("PULSEAI_PROMPT_CACHE", "").strip().lower()
    if val not in ("1", "true", "yes", "on"):
        return False
    if provider and provider.strip().lower() in _DEFAULT_CACHEABLE_PROVIDERS:
        return True
    if provider and provider.strip().lower() == "custom":
        # The custom/base_url route must be explicitly verified per endpoint.
        allow = os.environ.get("PULSEAI_PROMPT_CACHE_CUSTOM", "").strip().lower()
        return allow in ("1", "true", "yes", "on")
    return False


def _cache_marker() -> dict[str, Any]:
    return {"type": "ephemeral", "ttl": _TTL}


def _can_carry_marker(msg: Any) -> bool:
    """Only SystemMessages on the stable head carry breakpoints — marking a
    tool/assistant message would key the cache to a volatile tail and bust
    it next turn (hermes: markers must land on messages that count)."""
    return type(msg).__name__ == "SystemMessage"


def build_prompt_cache_plan(
    messages: list,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[list, dict[str, Any]]:
    """Decorate the stable-prefix head of ``messages`` with cache breakpoints.

    Returns (out, info). Pure and never raises. ``info`` reports whether
    markers were applied and how many, so the caller (and the audit in
    ``prompt_cache_audit.py``) can observe the plan without string-sniffing.

    Layout: the leading SystemMessages (persona + stable context layers) are
    the byte-stable head. Mark the LAST ``_CACHE_BREAKPOINTS`` of them so a
    short new session still reuses the full stable prefix, and mid-session
    churn after the head does not invalidate earlier breakpoints.
    """
    if not isinstance(messages, list) or not messages:
        return messages, {"enabled": False, "markers": 0, "reason": "empty"}
    if not _cache_enabled(provider, model):
        return messages, {"enabled": False, "markers": 0, "reason": "opt-in"}

    marker = _cache_marker()
    breakpoints: list[Any] = []
    for msg in messages:
        if _can_carry_marker(msg):
            breakpoints.append(msg)

    # Mark the last N of the stable head (keep order/identity; rebuild only
    # when a marker is actually missing so the at-rest prefix never churns).
    mark = set(id(m) for m in breakpoints[-_CACHE_BREAKPOINTS:]) if breakpoints else set()
    marked = 0
    out: list = []
    changed = False
    for msg in messages:
        if id(msg) in mark:
            kw = dict(getattr(msg, "additional_kwargs", None) or {})
            if kw.get("cache_control") == marker:
                out.append(msg)
                marked += 1
                continue
            kw["cache_control"] = marker
            try:
                new = msg.model_copy(update={"additional_kwargs": kw})
            except Exception:
                try:
                    new = msg.copy(update={"additional_kwargs": kw})
                except Exception:
                    new = None
            if new is None:
                out.append(msg)
                continue
            out.append(new)
            changed = True
            marked += 1
        else:
            out.append(msg)

    if not changed:
        return messages, {"enabled": True, "markers": marked, "reason": "unchanged"}
    return out, {"enabled": True, "markers": marked, "reason": "applied"}