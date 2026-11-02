# src/context/token_budget.py
"""
Token Budget Manager
====================

This file makes sure we don't send too many words to the AI.

Every AI has a "token limit" (like a max word count).
If we go over, the AI gets confused or the API rejects us.
"""
try:
    import tiktoken
except ImportError:
    tiktoken = None

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from src.config.settings import CONTEXT_MODEL

# Budget replay keys — hermes parity: ALWAYS vs NEWEST_TURN_ONLY
_ALWAYS_REPLAYED_BUDGET_KEYS = frozenset({"tool_call_id", "name"})
_NEWEST_TURN_ONLY_BUDGET_KEYS = frozenset({"codex_reasoning_items", "reasoning_details"})


def count_tokens(messages: list[BaseMessage], model: str | None = None) -> int:
    """
    Count how many tokens a list of messages uses.

    Think of tokens as "AI words" — roughly 1 token = 0.75 English words.
    """
    model_name = model or CONTEXT_MODEL

    encoder = None
    try:
        try:
            encoder = tiktoken.encoding_for_model(model_name)
        except Exception as exc:
            from src.context.tokenizer_fallback import HEURISTIC_ENCODER, warn_once
            warn_once(f"encoding_for_model({model_name!r})", exc, note="using the standard cl100k_base tokenizer (exact counts)")
            encoder = tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        from src.context.tokenizer_fallback import HEURISTIC_ENCODER, warn_once
        warn_once("tiktoken cache lookup", exc)
        encoder = HEURISTIC_ENCODER

    total = 0

    for message in messages:
        total += 4  # Start of message
        if isinstance(message.content, str):
            total += len(encoder.encode(message.content))
        else:
            total += len(encoder.encode(str(message.content)))
        total += len(encoder.encode(message.type))
        total += 2  # End of message

    total += 2

    try:
        try:
            from src.context.budgeting.token_calibration import calibration_factor
        except ImportError:
            from src.context.token_calibration import calibration_factor
        _factor = calibration_factor(model_name)
        if _factor != 1.0:
            total = max(1, int(round(total * _factor)))
    except Exception:
        pass

    return total


def _group_turns(messages: list[BaseMessage]) -> list[list[BaseMessage]]:
    """Group messages into Human-anchored turns."""
    turns: list[list[BaseMessage]] = []
    cur: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, HumanMessage) and cur:
            turns.append(cur)
            cur = [m]
        else:
            cur.append(m)
    if cur:
        turns.append(cur)
    return turns


def _enforce_tool_pairing(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Keep AIMessage(tool_calls) + ToolMessage atomic, drop orphans."""
    out: list[BaseMessage] = []
    pending_tool_ids: set[str] = set()
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            pending_tool_ids = {tc.get("id") or tc.get("tool_call_id") for tc in m.tool_calls if isinstance(tc, dict)}
            try:
                pending_tool_ids.update({getattr(tc, "id", "") for tc in m.tool_calls if hasattr(tc, "id")})
            except Exception:
                pass
            out.append(m)
        elif isinstance(m, ToolMessage):
            tid = getattr(m, "tool_call_id", None)
            if tid in pending_tool_ids:
                out.append(m)
                pending_tool_ids.discard(tid)
            elif not pending_tool_ids:
                continue
            else:
                out.append(m)
        else:
            out.append(m)
    sanitized: list[BaseMessage] = []
    for m in out:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            has_match = any(isinstance(n, ToolMessage) and getattr(n, "tool_call_id", None) in {tc.get("id") for tc in m.tool_calls if isinstance(tc, dict)} for n in out)
            if not has_match:
                sanitized.append(AIMessage(content=m.content or ""))
            else:
                sanitized.append(m)
        else:
            sanitized.append(m)
    return sanitized


def trim_messages_to_budget(
    messages: list[BaseMessage],
    max_tokens: int,
    model: str | None = None,
) -> list[BaseMessage]:
    """Turn-atomic trim — never split tool pairs, never start on ToolMessage."""
    if not messages:
        return []
    system_messages = [m for m in messages if isinstance(m, SystemMessage)]
    other = [m for m in messages if not isinstance(m, SystemMessage)]
    if not other:
        return system_messages[:]

    turns = _group_turns(other)
    kept: list[list[BaseMessage]] = []
    for turn in reversed(turns):
        candidate = system_messages + turn + sum(kept, [])
        if count_tokens(candidate, model) <= max_tokens:
            kept = [turn] + kept
        elif not kept:
            kept = [turn]
            break
        else:
            break

    result = system_messages + sum(kept, [])
    result = _enforce_tool_pairing(result)
    while result and isinstance(result[0], ToolMessage):
        result.pop(0)
        result = _enforce_tool_pairing(result)
    return result
