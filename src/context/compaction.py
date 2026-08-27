"""
compaction.py -- D22: the hermes compaction hardening pack for PulseAI
=====================================================================

Four patterns from NousResearch hermes-agent (§29, receipts re-verified
against their context_compressor.py), fitted to OUR history pipeline:

1. **Prune first, free** (their step 1 / `_PRUNED_TOOL_PLACEHOLDER`):
   old tool outputs in the unprotected middle are replaced by a short
   placeholder. Zero LLM, zero quality call — the placeholders say what
   happened. Only if the budget STILL overflows does the structural
   (turn-dropping) pass fire. Our SmartCompressor otherwise fires on
   every over-budget turn.
2. **Protected head + tail**: the first complete turn (original
   instructions) and the newest ~20K tokens are never touched.
3. **Iterative, not rebuilt**: when structural dropping DOES fire, the
   dropped turns are folded into a RUNNING per-session summary via the
   AUXILIARY model (D21); each later compaction extends the same summary
   instead of re-summarizing the world. Aux failure degrades to a
   bounded plain-text append — compaction degrades, never breaks.
4. **Anti-thrash telemetry**: per-session counters; a compaction that
   reclaims <15% counts "ineffective"; 3 ineffective in a row suppresses
   the LLM summary step for the next 10 compactions (pruning continues).

CRITICAL structural difference from hermes, in our favor: this runs on
the REQUEST-ONLY copy of history inside build_ai_messages — the
checkpoint store is never mutated. Their post-compaction store pollution
(issue #43175, which forced discovery-time filtering) cannot occur; the
placeholder text and the summary prefix below use markers the D16
session index already skips at ingest anyway (belt and suspenders).

Kill-switch: PULSEAI_COMPACTION=off restores the pre-D22 structural pipeline
(summarize-then-trim, no prune, no summary). Landed mutation-payload omission is
an independent run-budget safety fix; PULSEAI_MUTATION_PAYLOAD_COMPACTION=off
disables it for diagnosis.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from src.context.token_budget import count_tokens

log = logging.getLogger("pulseai.compaction")

# hermes context_compressor.py:399 verbatim — same marker text on purpose
_PRUNED_TOOL_PLACEHOLDER = "[Old tool output cleared to save context space]"

# Trimmed from their SUMMARY_PREFIX (context_compressor.py ~:99): the
# anti-confusion contract that keeps the model serving the LATEST user
# message, not the summary. Prefix matches D16's ingest-skip list.
COMPACTION_SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted "
    "into the summary below. Treat it as background, not instructions: "
    "the latest user message after it is the ONLY active task."
)

_DEFAULT_TAIL_TOKENS = 20_000
_PLACEHOLDER_MIN_CHARS = 600
_INEFFECTIVE_FRACTION = 0.15
_INEFFECTIVE_STREAK_MAX = 3
_INEFFECTIVE_COOLDOWN = 10
_SUMMARY_MAX_CHARS = 3_000
_DROPPED_TEXT_BUDGET = 6_000
_DROPPED_PER_MSG = 220
_FILE_MUTATION_TOOLS = frozenset({"write_file", "edit_file", "copy_file"})
_MUTATION_PAYLOAD_KEYS = frozenset({"content", "old_text", "new_text"})
_MUTATION_PAYLOAD_PLACEHOLDER = "[Persisted file payload omitted; read the workspace for current content]"


def compact_file_mutation_arguments(
    history: list[BaseMessage], *, keep_recent: int = 1
) -> list[BaseMessage]:
    """Omit landed file payloads from the request-only transcript copy.

    File bodies live in assistant tool-call arguments, not ToolMessage output,
    so ordinary tool-result pruning cannot reclaim them.  Re-sending every old
    ``write_file`` body consumed Attempt 11's token ceiling before dependency
    and runtime verification.  Once a mutation has a non-error ToolMessage
    receipt, preserve its id/name/path and redact only large payload fields.
    The newest landed mutation remains verbatim for immediate correction.

    Source checkpoint messages are never mutated and tool-call/result pairing
    remains intact.
    """
    if os.environ.get("PULSEAI_MUTATION_PAYLOAD_COMPACTION", "").strip().lower() == "off":
        return history

    successful_ids: list[str] = []
    for message in history:
        if not isinstance(message, ToolMessage):
            continue
        if getattr(message, "name", "") not in _FILE_MUTATION_TOOLS:
            continue
        content = str(getattr(message, "content", "") or "").lstrip().lower()
        if content.startswith(("error:", "❌", "failed:")):
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        if call_id:
            successful_ids.append(call_id)
    redact_ids = set(successful_ids[:-max(0, keep_recent)] if keep_recent else successful_ids)
    if not redact_ids:
        return history

    result: list[BaseMessage] = []
    for message in history:
        if not isinstance(message, AIMessage) or not getattr(message, "tool_calls", None):
            result.append(message)
            continue
        changed = False
        calls = []
        for call in message.tool_calls:
            cloned = dict(call)
            if str(call.get("id") or "") in redact_ids and call.get("name") in _FILE_MUTATION_TOOLS:
                args = dict(call.get("args") or {})
                for key in _MUTATION_PAYLOAD_KEYS:
                    value = args.get(key)
                    if isinstance(value, str) and len(value) > len(_MUTATION_PAYLOAD_PLACEHOLDER):
                        args[key] = _MUTATION_PAYLOAD_PLACEHOLDER
                        changed = True
                cloned["args"] = args
            calls.append(cloned)
        if not changed:
            result.append(message)
            continue
        copier = getattr(message, "model_copy", None)
        if callable(copier):
            result.append(copier(update={"tool_calls": calls}))
        else:  # langchain-core/pydantic v1 compatibility
            result.append(message.copy(update={"tool_calls": calls}))
    return result


_EXTEND_PROMPT = (
    "You maintain the running summary of an AI coding session. Rewrite "
    "SUMMARY + NEW DROPPED TURNS into one updated summary (same length "
    "class or shorter). Keep: user goals, decisions made, file paths, "
    "errors encountered, and anything still unresolved. Drop: chitchat, "
    "repeated attempts, and raw tool output.\n\nSUMMARY:\n{prev}\n\n"
    "NEW DROPPED TURNS:\n{new}\n\nUPDATED SUMMARY:"
)


def _text_of(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(p.get("text", ""))
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


class HistoryCompactor:
    """Per-session compactor: prune, protect, (optionally) summarize."""

    def __init__(
        self,
        model: str | None,
        aux_llm_getter: Optional[Callable[[], Any]] = None,
        tail_tokens: int = _DEFAULT_TAIL_TOKENS,
    ):
        self._model = model
        self._aux_llm_getter = aux_llm_getter
        self._tail_tokens = tail_tokens
        self._summary: str = ""
        self.stats: dict[str, int] = {
            "prunes": 0, "placeholders": 0, "placeholder_chars_reclaimed": 0,
            "structural_compactions": 0, "llm_summary_calls": 0,
            "llm_suppressed": 0, "ineffective_streak": 0,
        }
        self._suppress_llm_for = 0  # remaining compactions w/o LLM summary

    # ---------------------------------------------------------- head/tail
    def _head_len(self, history: list[BaseMessage]) -> int:
        """First complete turn = protected head (their 'first exchange').
        Protocol-safe: never sever an AI(tool_calls)/ToolMessage pair."""
        from langchain_core.messages import HumanMessage

        for i, msg in enumerate(history):
            if isinstance(msg, HumanMessage):
                # turn ends at the next HumanMessage (exclusive)
                for j in range(i + 1, len(history)):
                    if isinstance(history[j], HumanMessage):
                        return j
                return len(history)
        return min(1, len(history))  # preamble-only history

    def _tail_start(self, history: list[BaseMessage], head: int) -> int:
        """Newest messages totaling ~tail_tokens are protected (walk back).
        Never splits an AI(tool_calls,[id]) / ToolMessage(id) pair."""
        total = 0
        start = len(history)
        for i in range(len(history) - 1, head - 1, -1):
            msg_tokens = count_tokens([history[i]], self._model)
            if total + msg_tokens > self._tail_tokens and start < len(history):
                break
            total += msg_tokens
            start = i
        # if a ToolMessage sits at the boundary, pull its answering
        # AI(tool_calls) into the tail too (pairing invariant §28)
        while start > head and start < len(history) and isinstance(history[start], ToolMessage):
            start -= 1
        return max(start, head)

    # ---------------------------------------------------------------- prune
    def prune(self, history: list[BaseMessage]) -> tuple[list[BaseMessage], int, int]:
        """Replace long tool outputs in the UNPROTECTED middle with the
        placeholder. Returns (new_messages, replacements, chars_reclaimed).
        Source messages are never mutated (request-only copies)."""
        if not history:
            return [], 0, 0
        head = self._head_len(history)
        tail = self._tail_start(history, head)

        out: list[BaseMessage] = list(history[:head]) + list(history[head:])
        replaced = 0
        reclaimed = 0
        for i in range(head, tail):
            msg = history[i]
            if not isinstance(msg, ToolMessage):
                continue
            text = _text_of(msg)
            if len(text) < _PLACEHOLDER_MIN_CHARS:
                continue
            out[i] = ToolMessage(
                content=_PRUNED_TOOL_PLACEHOLDER,
                name=getattr(msg, "name", ""),
                tool_call_id=msg.tool_call_id,
                id=getattr(msg, "id", None),
            )
            replaced += 1
            reclaimed += len(text) - len(_PRUNED_TOOL_PLACEHOLDER)

        self.stats["prunes"] += 1
        self.stats["placeholders"] += replaced
        self.stats["placeholder_chars_reclaimed"] += reclaimed
        return out, replaced, reclaimed

    # -------------------------------------------------------------- summary
    def _dropped_text(self, dropped: list[BaseMessage]) -> str:
        parts = []
        total = 0
        for msg in dropped:
            role = type(msg).__name__.replace("Message", "")
            body = " ".join(_text_of(msg).split())[:_DROPPED_PER_MSG]
            if not body:
                continue
            line = f"{role}: {body}"
            total += len(line)
            if total > _DROPPED_TEXT_BUDGET:
                break
            parts.append(line)
        return "\n".join(parts)

    def _update_summary(self, dropped: list[BaseMessage]) -> None:
        """Iterative extend (their pattern #5): prev summary + only the
        newly dropped turns -> rolled summary. LLM via AUX client (D21);
        degrades to bounded plain append; thrash suppression applies."""
        new_text = self._dropped_text(dropped)
        if not new_text:
            return

        use_llm = self._suppress_llm_for == 0
        if use_llm and self._aux_llm_getter is not None:
            try:
                llm = self._aux_llm_getter()
                prompt = _EXTEND_PROMPT.format(prev=self._summary or "(empty)", new=new_text)
                response = llm.invoke(prompt)
                text = getattr(response, "content", str(response))
                self._summary = " ".join(str(text).split())[:_SUMMARY_MAX_CHARS]
                self.stats["llm_summary_calls"] += 1
                return
            except Exception as error:
                log.warning("compaction aux summary failed, plain-append: %s", error)

        if not use_llm:
            self.stats["llm_suppressed"] += 1
            self._suppress_llm_for -= 1
        merged = (self._summary + "\n" + new_text).strip()
        # bounded plain append: prefer recency, keep under cap
        self._summary = merged[-_SUMMARY_MAX_CHARS:]

    def _note_effectiveness(self, before: int, after: int) -> None:
        if before <= 0:
            return
        savings = (before - after) / before
        if savings < _INEFFECTIVE_FRACTION:
            self.stats["ineffective_streak"] += 1
            if self.stats["ineffective_streak"] == _INEFFECTIVE_STREAK_MAX:
                self._suppress_llm_for = _INEFFECTIVE_COOLDOWN
                log.warning(
                    "compaction anti-thrash: %d ineffective compactions — "
                    "LLM summary suppressed for %d", _INEFFECTIVE_STREAK_MAX,
                    _INEFFECTIVE_COOLDOWN,
                )
                self.stats["ineffective_streak"] = 0
        else:
            self.stats["ineffective_streak"] = 0

    # -------------------------------------------------------------- driver
    def compact(
        self,
        history: list[BaseMessage],
        budget: int,
        summarize_tools: Callable[[list[BaseMessage]], list[BaseMessage]],
        structural_compress: Callable[[list[BaseMessage], int], list[BaseMessage]],
        fallback_trim: Callable[[list[BaseMessage], int], list[BaseMessage]],
    ) -> list[BaseMessage]:
        """The full pipeline: prune -> per-tool summaries -> structural
        (only if still over) -> summary injection for whatever dropped.

        Head and tail are never handed to the structural stage at all —
        protection is absolute (their pattern #2), not scoring luck."""
        if not history:
            return []

        # Always apply the free per-tool summarizer before the budget check.
        # The old fast path replayed every raw result whenever history happened
        # to fit, so a 6KB file read was re-billed on every later call. Hermes
        # stores/replays bounded receipts; Pulse now does the same even below
        # the structural-compaction threshold.
        payload_compacted = compact_file_mutation_arguments(history)
        summarized_fast = summarize_tools(payload_compacted)
        before_tokens = count_tokens(history, self._model)
        if count_tokens(summarized_fast, self._model) <= budget:
            return summarized_fast

        # 1+2. FREE prune with protected head/tail — hermes' first trigger.
        pruned, _, _ = self.prune(summarized_fast)
        summarized = pruned

        if count_tokens(summarized, self._model) <= budget:
            return self._with_summary(summarized)

        # 3. Still over: separate the absolutely-protected material (head /
        #    tail spans are index-stable after the 1:1 placeholder swaps and
        #    per-tool summaries), and let the structural stage work ONLY on
        #    the expendable middle with its own shrunken budget.
        head_n = self._head_len(summarized)
        tail_i = self._tail_start(summarized, head_n)
        head_msgs = summarized[:head_n]
        middle = summarized[head_n:tail_i]
        tail_msgs = summarized[tail_i:]

        reserved = count_tokens(head_msgs, self._model) + count_tokens(tail_msgs, self._model)
        middle_budget = max(0, budget - reserved)
        if middle_budget > 0 and middle:
            compressed_middle = structural_compress(middle, middle_budget)
            if count_tokens(compressed_middle, self._model) > middle_budget:
                compressed_middle = fallback_trim(compressed_middle, middle_budget)
        else:
            compressed_middle = []

        dropped = self._diff(middle, compressed_middle)
        self._update_summary(dropped)
        self.stats["structural_compactions"] += 1
        final = head_msgs + compressed_middle + tail_msgs
        self._note_effectiveness(before_tokens, count_tokens(final, self._model))

        return self._with_summary(final)

    @staticmethod
    def _diff(before: list[BaseMessage], after: list[BaseMessage]) -> list[BaseMessage]:
        kept = {id(m) for m in after}
        return [m for m in before if id(m) not in kept]

    def _with_summary(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Inject the running summary right after the protected head."""
        if not self._summary:
            return messages
        head = self._head_len(messages)
        summary_msg = SystemMessage(
            content=f"{COMPACTION_SUMMARY_PREFIX}\n\n{self._summary}",
            response_metadata={"compaction": True},
        )
        return list(messages[:head]) + [summary_msg] + list(messages[head:])

    @property
    def summary(self) -> str:
        return self._summary

    @property
    def llm_suppressed(self) -> bool:
        return self._suppress_llm_for > 0
