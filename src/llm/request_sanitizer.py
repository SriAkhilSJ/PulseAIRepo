"""
Pre-send Request Sanitizer (D36)
===============================
A lossless, deterministic cleanup of the message list that runs at the final
pre-API chokepoint (RetryLLMProxy.invoke). Mirrors hermes' pre-call
sanitizer (agent_runtime_helpers.py:3436-3479) and the byte-identical tool
result dedup (context_compressor.py:3390):

  1. Collapse duplicate tool_call entries WITHIN an assistant message
     (keep the first occurrence of each id). Strict providers (DeepSeek)
     reject a payload where the same tool_call_id appears more than once
     with HTTP 400 "Duplicate value for 'tool_call_id'".
  2. Drop later tool result messages that REUSE an already-seen
     tool_call_id. Duplicates arise from retries, crash/resume glitches, or
     a re-played compression window. Keeps every tool_call satisfied.
  3. Byte-identical tool result dedup: when two DIFFERENT tool results carry
     the exact same content, keep the NEWEST copy and drop the older one,
     re-pointing the older assistant tool_call at the surviving id so no
     tool_call is ever left without a result.

The sanitizer is intentionally lossless: every remaining assistant tool_call
still has a matching tool result, and no unique content is dropped. It must
never raise — the pre-send path is hot, so any failure returns the input
unchanged.
"""

from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


def _call_id(tool_call: dict[str, Any]) -> str:
    return (tool_call.get("id") or "").strip()


def _collapse_duplicate_tool_calls(
    messages: list[BaseMessage],
) -> tuple[list[BaseMessage], int]:
    """(1) Drop duplicate tool_call ids inside a single assistant message.
    Returns (messages, removed_count)."""
    removed = 0
    out: list[BaseMessage] = []
    for msg in messages:
        if not isinstance(msg, AIMessage) or not getattr(msg, "tool_calls", None):
            out.append(msg)
            continue
        seen: set[str] = set()
        kept: list[dict[str, Any]] = []
        dropped_any = False
        for tc in msg.tool_calls:
            cid = _call_id(tc)
            if cid and cid in seen:
                dropped_any = True
                removed += 1
                continue
            if cid:
                seen.add(cid)
            kept.append(tc)
        if dropped_any:
            msg = AIMessage(
                content=msg.content,
                tool_calls=kept,
                additional_kwargs={k: v for k, v in msg.additional_kwargs.items()
                                   if k != "tool_calls"},
                id=msg.id,
            )
        out.append(msg)
    return out, removed


def _drop_reused_result_ids(
    messages: list[BaseMessage],
) -> tuple[list[BaseMessage], int]:
    """(2) Drop tool results whose tool_call_id was already consumed.
    Returns (messages, removed_count)."""
    seen: set[str] = set()
    out: list[BaseMessage] = []
    removed = 0
    for msg in messages:
        cid = ""
        if isinstance(msg, ToolMessage):
            cid = (msg.tool_call_id or "").strip()
        if cid:
            if cid in seen:
                removed += 1
                continue
            seen.add(cid)
        out.append(msg)
    return out, removed


def _dedup_byte_identical_results(
    messages: list[BaseMessage],
) -> tuple[list[BaseMessage], int]:
    """(3) Keep the NEWEST byte-identical tool result; drop older exact
    duplicates and re-point the dropped ids at the surviving copy so every
    assistant tool_call keeps a matching result. Returns (messages,
    removed_count)."""
    # Scan from the tail: first seen content wins (the newest copy).
    hash_to_kept: dict[str, str] = {}          # content hash -> kept id
    dropped_id_map: dict[str, str] = {}        # dropped id -> kept id
    drop_indices: set[int] = set()

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if not isinstance(msg, ToolMessage):
            continue
        cid = (msg.tool_call_id or "").strip()
        if not cid:
            continue
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            continue
        h = hash(content)
        if h in hash_to_kept:
            kept_id = hash_to_kept[h]
            if kept_id != cid:
                # Older exact duplicate of a newer result: drop it and
                # re-point any assistant tool_call that referenced it.
                dropped_id_map[cid] = kept_id
                drop_indices.add(i)
        else:
            hash_to_kept[h] = cid

    if not drop_indices:
        return messages, 0

    out: list[BaseMessage] = []
    removed = 0
    for i, msg in enumerate(messages):
        if i in drop_indices:
            removed += 1
            continue
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            kept = [
                {**tc, "id": dropped_id_map[tc.get("id", "")]}
                if tc.get("id") in dropped_id_map
                else tc
                for tc in msg.tool_calls
            ]
            msg = AIMessage(
                content=msg.content,
                tool_calls=kept,
                additional_kwargs={k: v for k, v in msg.additional_kwargs.items()
                                   if k != "tool_calls"},
                id=msg.id,
            )
        out.append(msg)
    return out, removed


def sanitize_request_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Lossless pre-send cleanup. Never raises; returns the input unchanged
    on any unexpected error."""
    if not isinstance(messages, list) or not messages:
        return messages
    try:
        out = messages
        n1 = n2 = n3 = 0
        out, n1 = _collapse_duplicate_tool_calls(out)
        out, n2 = _drop_reused_result_ids(out)
        out, n3 = _dedup_byte_identical_results(out)
        total = n1 + n2 + n3
        if total:
            print(
                f"[RequestSanitizer] removed {total} item(s) pre-send "
                f"(dup tool_calls={n1}, re-used tool_call_id={n2}, "
                f"byte-identical results={n3})"
            )
            return out
        # Nothing removed: hand back the INPUT object so callers can gate on
        # identity (`result is not messages`) instead of comparing lists.
        return messages
    except Exception as exc:
        print(
            f"[RequestSanitizer] sanitize step failed ({exc!r}) — "
            "sending original messages"
        )
        return messages