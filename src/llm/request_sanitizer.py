"""
Pre-send Request Sanitizer (D36, hermes outstanding-call semantics)
===================================================================
A deterministic cleanup of the message list that runs at the final pre-API
chokepoint (RetryLLMProxy.invoke). Ported from hermes' pre-call sanitizer
``_dedupe_tool_call_ids`` (agent/agent_runtime_helpers.py:2690) — same
tracking discipline, adapted to LangChain messages:

  1. Collapse duplicate tool_call entries WITHIN an assistant message
     (keep the first occurrence of each id). Strict providers (DeepSeek)
     reject a payload where the same tool_call_id appears more than once
     with HTTP 400 "Duplicate value for 'tool_call_id'".
  2. OUTSTANDING-CALL tracking (the hermes core): an assistant tool_call
     REGISTERS its id as outstanding; a tool result CONSUMES the matching
     outstanding id; a result that answers no outstanding call is dropped.

    Why NOT "seen-once-drop-forever": hermes' docstring names the exact
    failure — llama.cpp reuses one constant id for every tool call, and a
    seen-once rule "reads the SECOND legitimate tool result of such a
    session as a duplicate and deletes it, so from the second tool call
    onward the model never sees any result — it announces its next action
    and the turn dies with the work unfinished." Pulse field proof
    (2026-09-06): the byte-identical content dedup below that rule kept
    `terminal ls -la` results invisible and the model re-ran the same
    command four times in one turn. A genuine new call that reuses an id
    re-arms it first; only a result with no PENDING call is dropped.

  3. Empty tool-result content becomes a placeholder (strict providers
     such as Sarvam HTTP-400 an empty ToolMessage string).

There is deliberately NO content-based dedup: hermes keeps every result
visible and never re-points one assistant tool_call at another call's
result — manufactured pairings read as amnesia to the model and are what
produced the repeated-command flail the first sanitizer version caused.

The sanitizer must never raise — the pre-send path is hot, so any failure
returns the input unchanged.
"""

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


def _call_id(tool_call: dict[str, Any]) -> str:
    return (tool_call.get("id") or "").strip()


def _rebuild_ai_message(msg: AIMessage, kept_tool_calls: list[dict[str, Any]]) -> AIMessage:
    return AIMessage(
        content=msg.content,
        tool_calls=kept_tool_calls,
        additional_kwargs={k: v for k, v in msg.additional_kwargs.items()
                           if k != "tool_calls"},
        id=msg.id,
    )


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
            msg = _rebuild_ai_message(msg, kept)
        out.append(msg)
    return out, removed


def _dedupe_by_outstanding_calls(
    messages: list[BaseMessage],
) -> tuple[list[BaseMessage], int]:
    """(2) Outstanding-call tracking, ported from hermes
    ``_dedupe_tool_call_ids``: every assistant tool_call re-arms its id; a
    tool result consumes the outstanding id it answers; a result answering
    NO outstanding call is dropped. A repeated assistant tool_call whose id
    is STILL outstanding (unanswered duplicate — retries, crash/resume
    glitches) drops the LATER CALL, the same choice hermes makes: keep
    exactly one live call per id so its result has one unambiguous owner.

    Returns (messages, removed_count)."""
    outstanding: dict[str, None] = {}
    out: list[BaseMessage] = []
    removed = 0

    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            kept: list[dict[str, Any]] = []
            dropped_any = False
            for tc in msg.tool_calls:
                cid = _call_id(tc)
                if cid and cid in outstanding:
                    # Unanswered duplicate of a live call: drop THIS call,
                    # keep the model's newest intent unambiguous.
                    dropped_any = True
                    removed += 1
                    continue
                if cid:
                    outstanding[cid] = None
                kept.append(tc)
            if dropped_any:
                msg = _rebuild_ai_message(msg, kept)
        elif isinstance(msg, ToolMessage):
            cid = (msg.tool_call_id or "").strip()
            if cid:
                if cid not in outstanding:
                    # Answers no pending call: retry echoes and re-played
                    # compression windows land here. Hermes keeps such a
                    # result OUT — it cannot be paired to any live call.
                    removed += 1
                    continue
                # Consumed: the id may be legitimately re-armed by a NEW
                # call later in the conversation (llama.cpp constant-id
                # sessions run entirely on this re-arm path).
                del outstanding[cid]
        out.append(msg)

    return out, removed


def _ensure_nonempty_tool_content(messages: list[BaseMessage]) -> tuple[list[BaseMessage], int]:
    """(3) Strict providers (e.g. Sarvam) HTTP-400 a ToolMessage whose content is an
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


def sanitize_request_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Deterministic pre-send cleanup (hermes outstanding-call semantics).
    Never raises; returns the input unchanged on any unexpected error."""
    if not isinstance(messages, list) or not messages:
        return messages
    try:
        out = messages
        n1 = n2 = n3 = 0
        out, n1 = _collapse_duplicate_tool_calls(out)
        out, n2 = _dedupe_by_outstanding_calls(out)
        out, n3 = _ensure_nonempty_tool_content(out)
        total = n1 + n2 + n3
        if total:
            print(
                f"[RequestSanitizer] removed/fixed {total} item(s) pre-send "
                f"(dup tool_calls={n1}, unpaired results/calls={n2}, "
                f"empty-tool-content={n3})"
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
