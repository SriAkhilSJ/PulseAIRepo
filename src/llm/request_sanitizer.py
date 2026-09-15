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


def _ensure_nonempty_tool_content(messages: list[BaseMessage]) -> tuple[list[BaseMessage], int]:
    """Strict providers (e.g. Sarvam) HTTP-400 a ToolMessage whose content is an
    empty string ("String should have at least 1 character"). A tool that returns
    "" (empty dir listing, no-op, etc.) produces exactly that. Replace empty
    content with a minimal placeholder so the request is always accepted.
    Lossless for non-empty content; never raises."""
    out: list[BaseMessage] = []
    fixed = 0
    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or content == "":
                out.append(ToolMessage(
                    content="(tool returned no output)",
                    tool_call_id=getattr(msg, "tool_call_id", "") or "",
                    name=getattr(msg, "name", None) or "",
                ))
                fixed += 1
                continue
        out.append(msg)
    return out, fixed


def _drop_empty_tool_calls_arrays(
    messages: list[BaseMessage],
) -> tuple[list[BaseMessage], int]:
    """Hermes _drop_empty_tool_calls_arrays: DeepSeek strict 400 on
    `tool_calls: []`. An AIMessage with an empty tool_calls list is not a
    tool call — strip the field so it becomes a normal text message.
    Returns (messages, fixed_count)."""
    out: list[BaseMessage] = []
    fixed = 0
    for msg in messages:
        if isinstance(msg, AIMessage):
            tcs = getattr(msg, "tool_calls", None)
            # LangChain may represent empty as [] — that's the DeepSeek 400
            if isinstance(tcs, list) and len(tcs) == 0:
                try:
                    # Create clean AIMessage without tool_calls
                    new_msg = AIMessage(
                        content=msg.content,
                        additional_kwargs={
                            k: v for k, v in (msg.additional_kwargs or {}).items()
                            if k != "tool_calls"
                        },
                        id=getattr(msg, "id", None),
                        response_metadata=getattr(msg, "response_metadata", None) or {},
                    )
                    out.append(new_msg)
                except Exception:
                    # Fallback: keep original but clear tool_calls
                    try:
                        # AIMessage stores tool_calls as property, clear via additional_kwargs
                        if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
                            msg.additional_kwargs.pop("tool_calls", None)
                        # Also try direct attribute
                        if hasattr(msg, "tool_calls"):
                            msg.tool_calls = []  # type: ignore
                    except Exception:
                        pass
                    out.append(msg)
                fixed += 1
                continue
        out.append(msg)
    return out, fixed


def _drop_results_without_ids(
    messages: list[BaseMessage],
) -> tuple[list[BaseMessage], int]:
    """Hermes _drop_results_without_ids: ToolMessage without tool_call_id
    is a stray — drop it ONLY when there is at least one valid tool_call_id
    in the history (otherwise we would delete the only tool result and leave
    a dangling tool_call). This preserves the 'never raises' contract and
    matches existing test expectations for adversarial inputs."""
    # Collect valid ids first
    has_valid = False
    for msg in messages:
        if isinstance(msg, ToolMessage):
            cid = (getattr(msg, "tool_call_id", "") or "").strip()
            if cid:
                has_valid = True
                break
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if _call_id(tc):
                    has_valid = True
                    break
    if not has_valid:
        return messages, 0

    out: list[BaseMessage] = []
    removed = 0
    for msg in messages:
        if isinstance(msg, ToolMessage):
            cid = (getattr(msg, "tool_call_id", "") or "").strip()
            if not cid:
                removed += 1
                continue
        out.append(msg)
    return out, removed


def _repair_nameless_tool_calls(
    messages: list[BaseMessage],
) -> tuple[list[BaseMessage], int]:
    """Hermes _repair_nameless_tool_calls → invalid_tool_call.
    If a tool call has no name, repair to `invalid_tool_call` so provider
    doesn't 400 on missing name."""
    out: list[BaseMessage] = []
    fixed = 0
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            new_calls = []
            changed = False
            for tc in msg.tool_calls:
                name = str(tc.get("name", "") or "").strip()
                if not name:
                    new_tc = dict(tc)
                    new_tc["name"] = "invalid_tool_call"
                    new_calls.append(new_tc)
                    changed = True
                    fixed += 1
                else:
                    new_calls.append(tc)
            if changed:
                try:
                    out.append(msg.model_copy(update={"tool_calls": new_calls}))
                except Exception:
                    msg.tool_calls = new_calls
                    out.append(msg)
                continue
        out.append(msg)
    return out, fixed


def strip_tool_pairs(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Strip tool-call/result pairs from a message list so it is a valid
    NO-TOOLS request. The grace call binds no tools, so any AIMessage with
    tool_calls and the ToolMessages answering them must not be sent —
    OpenAI-compat providers hard-400 on "Tool messages found but no tools
    provided". Text-only AIMessages survive (they carry reasoning).

    This is the D40 fallback and the final safety net in RequestSanitizer
    when has_tools=False.
    """
    out: list = []
    for m in messages:
        if isinstance(m, ToolMessage):
            continue
        tcs = getattr(m, "tool_calls", None)
        if tcs:
            # If content is empty and only tool_calls, drop entirely
            # If content has text, keep text but drop tool_calls
            content = getattr(m, "content", "")
            text = content if isinstance(content, str) else str(content or "")
            if text.strip():
                try:
                    out.append(
                        AIMessage(
                            content=text,
                            id=getattr(m, "id", None),
                            additional_kwargs={
                                k: v
                                for k, v in (getattr(m, "additional_kwargs", {}) or {}).items()
                                if k != "tool_calls"
                            },
                        )
                    )
                except Exception:
                    out.append(AIMessage(content=text))
            continue
        out.append(m)
    return out


def _pair_tool_calls_positionally(
    messages: list[BaseMessage],
) -> tuple[list[BaseMessage], int]:
    """Hermes _pair_tool_calls_positionally: ensures tool result immediately
    after its call, stubs missing, drops positional orphans.
    Simplified for Crusor: this is a safety check that drops ToolMessages
    without a preceding matching AIMessage in the same turn. However, to
    avoid breaking valid flows where history is truncated, we only drop
    if we can prove it's stray (no matching call_id seen at all in history).

    For now, conservative: track all call_ids ever seen, not just outstanding.
    Drop only if tool result's id was never seen.
    """
    # Collect all tool_call_ids ever emitted in this message list
    all_call_ids: set[str] = set()
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                cid = _call_id(tc)
                if cid:
                    all_call_ids.add(cid)
    # If no calls at all, but tool messages exist, they are stray — but we
    # should NOT drop them here if has_tools is unknown (caller will decide).
    # Instead, only drop if we have seen at least one call and this result
    # doesn't match any.
    if not all_call_ids:
        return messages, 0

    out: list[BaseMessage] = []
    fixed = 0
    for msg in messages:
        if isinstance(msg, ToolMessage):
            cid = (getattr(msg, "tool_call_id", "") or "").strip()
            if cid and cid not in all_call_ids:
                fixed += 1
                continue
        out.append(msg)
    return out, fixed


def sanitize_request_messages(
    messages: list[BaseMessage], has_tools: bool | None = None
) -> list[BaseMessage]:
    """Lossless pre-send cleanup. Never raises; returns the input unchanged
    on any unexpected error.

    has_tools: if False, strip all tool pairs (no-tools request). If None,
    auto-detect from messages (if tool messages present but we don't know,
    preserve them — caller should pass has_tools explicitly when known).
    """
    if not isinstance(messages, list) or not messages:
        return messages
    try:
        out = messages
        # If explicitly no tools, strip immediately — this is the final safety net
        # for Sarvam and other strict providers that 400 on tool messages without tools.
        if has_tools is False:
            stripped = strip_tool_pairs(out)
            if len(stripped) != len(out):
                print(
                    f"[RequestSanitizer] stripped {len(out) - len(stripped)} tool message(s) "
                    f"for no-tools request (has_tools=False)"
                )
            out = stripped
            # After stripping, no further tool sanitization needed
            # But still ensure no empty tool_calls arrays remain
            out, n_empty = _drop_empty_tool_calls_arrays(out)
            if n_empty:
                print(f"[RequestSanitizer] fixed {n_empty} empty tool_calls array(s)")
            return out

        n1 = n2 = n3 = n4 = n5 = n6 = n7 = n8 = 0
        out, n5 = _drop_empty_tool_calls_arrays(out)
        out, n6 = _repair_nameless_tool_calls(out)
        out, n7 = _drop_results_without_ids(out)
        out, n1 = _collapse_duplicate_tool_calls(out)
        out, n2 = _drop_reused_result_ids(out)
        out, n3 = _dedup_byte_identical_results(out)
        out, n4 = _ensure_nonempty_tool_content(out)
        out, n8 = _pair_tool_calls_positionally(out)

        total = n1 + n2 + n3 + n4 + n5 + n6 + n7 + n8
        if total:
            print(
                f"[RequestSanitizer] removed/fixed {total} item(s) pre-send "
                f"(dup tool_calls={n1}, re-used tool_call_id={n2}, "
                f"byte-identical results={n3}, empty-tool-content={n4}, "
                f"empty-tool-calls={n5}, nameless-tool-calls={n6}, "
                f"no-id-results={n7}, stray-results={n8})"
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