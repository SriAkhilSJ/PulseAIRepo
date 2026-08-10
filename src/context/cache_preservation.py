"""
Prompt-cache preservation across provider failover (D37)
========================================================
Hermes doctrine: per-conversation prompt caching must never break. Their
prompt_builder splits the request into [static prefix, volatile tail] and
their failover path re-decorates cache control for the new provider
(_redecorate_prompt_cache_for_provider). PulseAI has no cache_control blocks
today, but the failover chokepoint (ai_node) must still GUARANTEE:

  1. a byte-identical static prefix — the persona + stable context layers
     that provider prompt caches pay out on — survives a provider failover
     untouched; and
  2. any provider-specific cache decoration is stripped when the serving
     provider changes (future-proof: somebody adding cache_control without
     failover awareness would silently poison the new provider's request).

The split boundary is unambiguous by design: ContextEngine emits a constant
sentry SystemMessage (VOLATILE_TAIL_PREAMBLE) between history and the
volatile tail (context_engine.py:370). We locate it by object-identity of
the sentinel STRING — never by sniffing model output — so the split is
invariant to anything a provider or the model says.

All helpers are lossless and must never raise; any failure returns the
input unchanged (the send path is hot).
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage

# The engine's own sentinel; importing the constant keeps split and builder
# in lockstep so a future content change cannot silently desync the audit.
from src.context.context_engine import ContextEngine

_VOLATILE_SENTINEL = ContextEngine.VOLATILE_TAIL_PREAMBLE

# Producer-specific cache-decoration keys, defensively stripped across
# provider transitions. None are emitted today; this is the safety net.
_CACHE_DECORATION_KEYS = frozenset({
    "cache_control",
    "anthropic_lmoe_expert",
    "cache_read",
    "cache_write",
})


def _copy_msg(msg: BaseMessage, **update) -> BaseMessage | None:
    try:
        return msg.model_copy(update=update)
    except Exception:
        pass
    try:
        return msg.copy(update=update)
    except Exception:
        return None


def _has_decorations(msg: BaseMessage) -> bool:
    try:
        kw = msg.additional_kwargs or {}
    except Exception:
        return False
    return bool(_CACHE_DECORATION_KEYS.intersection(kw))


def split_prefix_tail(messages: list) -> tuple[list, list]:
    """Split engine-built messages into (static_prefix, volatile_tail).

    static_prefix = persona + stable layers + history (everything before the
    volatile sentinel). volatile_tail = the sentinel and every message after
    it (git_context etc.). No sentinel (no volatile block this turn) => the
    whole list is the prefix and the tail is empty.
    """
    if not isinstance(messages, list):
        return messages, []
    for i, msg in enumerate(messages):
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content == _VOLATILE_SENTINEL:
            return messages[:i], messages[i:]
    return messages, []


def stable_prefix(messages: list) -> list:
    """The byte-stable head only: the leading run of SystemMessages
    (persona + context layers) up to the first history/preamble boundary."""
    prefix, _tail = split_prefix_tail(messages)
    out: list = []
    for msg in prefix:
        if type(msg).__name__ != "SystemMessage":
            break
        out.append(msg)
    return out


def strip_cache_decorations(messages: list) -> tuple[list, int]:
    """Strip provider cache-decoration keys from every message's
    additional_kwargs. Returns (messages, stripped_count). Mutates nothing
    shared: a stripped message is a fresh copy; untouched ones are reused
    by identity so the prefix stays byte-identical at rest."""
    changed = False
    out: list = []
    stripped = 0
    for msg in messages:
        if not _has_decorations(msg):
            out.append(msg)
            continue
        kw = dict(msg.additional_kwargs or {})
        pruned_keys = _CACHE_DECORATION_KEYS.intersection(kw)
        for k in pruned_keys:
            kw.pop(k, None)
        new_msg = _copy_msg(msg, additional_kwargs=kw)
        if new_msg is None:
            out.append(msg)
            continue
        stripped += len(pruned_keys)
        changed = True
        out.append(new_msg)
    if changed:
        return out, stripped
    return messages, stripped


def redecorate_for_failover(messages: list) -> tuple[list, dict[str, Any]]:
    """Failover-safe re-decoration of a message list.

    (1) Preserves the static prefix VERBATIM — the prefix partition of the
    final list is byte-identical to the input's, item-for-item.
    (2) Strips any provider cache decorations (there are none today; this is
    the failover safety net).
    Returns (out, info). Never raises; on error returns (messages, {}) so the
    failover re-send is never blocked by cleanup bookkeeping.
    """
    try:
        prefix, tail = split_prefix_tail(messages)
        if not isinstance(prefix, list):
            return messages, {"error": "input is not a list"}
        out, stripped = strip_cache_decorations(messages)
        if stripped == 0:
            # Nothing to re-decorate: the prefix is untouched by construction
            # and no decoration was present to strip — hand back the exact
            # input object so callers also preserve reference identity.
            return messages, {
                "prefix_len": len(prefix),
                "tail_len": len(tail),
                "decorations_stripped": 0,
                "changed": False,
            }
        info = {
            "prefix_len": len(prefix),
            "tail_len": len(tail),
            "decorations_stripped": stripped,
            "changed": True,
        }
        return out, info
    except Exception as exc:
        print(f"[CachePreservation] redecorate failed ({exc!r}) — reusing input")
        return messages, {"error": repr(exc)}


def failover_cache_report(messages: list, routed_messages: list) -> dict[str, Any]:
    """D19-backed check: is the static prefix of the failover payload
    byte-identical to the routed payload's? The provider cache pays on this."""
    from src.context.prompt_cache_audit import _serialize
    try:
        base_text, _b = _serialize(messages)
        routed_text, _r = _serialize(routed_messages)
        kept_to = len(base_text) if base_text == routed_text else 0
        return {
            "base_chars": len(base_text),
            "routed_chars": len(routed_text),
            "prefix_identical": base_text == routed_text,
            "kept_chars": kept_to,
        }
    except Exception as exc:
        return {"error": repr(exc)}