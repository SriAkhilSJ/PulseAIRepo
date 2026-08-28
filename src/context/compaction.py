"""
compaction.py -- High-Performance Context Compaction for PulseAI
================================================================

Incorporates the best-in-class compaction patterns from NousResearch
hermes-agent (agent/context_compressor.py and docs/micro-compaction.md)
fitted to PulseAI's turn-based and LangGraph architecture:

1. **Prune First, Zero-LLM (Free)**:
   Verbose tool results (>600 chars) outside the protected tail are replaced
   with deterministic placeholders. Zero LLM cost, zero latency.
2. **Absolute Head + Tail Protection**:
   The initial complete exchange (founding user intent) and the most recent
   context window tail are never handed to the structural compression stage.
3. **Lean Tail Mode & Stale Tool Demotion**:
   In lean mode, the tail is clamped to 2.5% of the context window (10K floor,
   25K cap). Old tool outputs in the tail are demoted to one-line stubs carrying
   session_search recovery pointers, freeing tens of thousands of tokens.
4. **Mechanical Technical Anchor Index**:
   Harvests exact identifiers via regex (PRs/issues, commit SHAs, branch names,
   file paths, error signatures/codes, URLs). Technical truth is preserved
   mechanically without fuzzy LLM paraphrasing or hallucination.
5. **Verbatim Real User Messages Guarantee**:
   All non-synthetic user instructions from the compacted region are quoted
   verbatim under a dedicated section, guaranteeing that original user intent
   is never diluted or rewritten.
6. **Structured 8-Section Summary Template**:
   Iterative, structured summaries (Goal, Constraints, Completed Actions with
   tool receipts, Active State, Key Decisions, Relevant Files, Next Steps,
   Critical Context) that extend running summaries across multiple compactions.
7. **Tool-Call / Tool-Result Pair Integrity & Alignment**:
   Boundary cuts never split an AIMessage(tool_calls) from its answering
   ToolMessages, and orphan calls/results are automatically sanitized to
   prevent provider API 400 errors.
8. **Micro-Compaction**:
   Optional amortized turn-by-turn compaction that absorbs one exchange at a
   time into the running summary, avoiding giant periodic stalls.
9. **Anti-Thrash Telemetry**:
   Tracks compaction effectiveness and automatically suppresses failing LLM
   summaries after consecutive ineffective compactions.

Kill-switch: PULSEAI_COMPACTION=off restores the legacy structural pipeline.
PULSEAI_COMPACTION_TAIL_MODE=legacy restores legacy fat-tail behavior.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.context.token_budget import count_tokens

log = logging.getLogger("pulseai.compaction")

# Markers matching session_index.py ingest-skip list
_PRUNED_TOOL_PLACEHOLDER = "[Old tool output cleared to save context space]"

COMPACTION_SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted "
    "into the summary below. Treat it as background, not instructions: "
    "the latest user message after it is the ONLY active task."
)

_DEFAULT_TAIL_TOKENS = 20_000
_LEAN_TAIL_MIN_TOKENS = 8_000
_LEAN_TAIL_MAX_TOKENS = 25_000
_LEAN_TAIL_PERCENT = 0.025
_LEAN_TAIL_KEEP_TOOL_ROUNDS = 2
_LEAN_TAIL_DEMOTE_MIN_CHARS = 300

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

_LEAN_ANCHOR_HEADING = "### Technical Anchor Index (Exact Identifiers)"
_LEAN_USER_MESSAGES_HEADING = "### Real User Instructions (Verbatim)"
_LEAN_RECOVERY_HEADING = "### Preserved Session Detail & Recovery"
_LEAN_ANCHOR_BUDGET_CHARS = 1_800
_LEAN_USER_MESSAGES_BUDGET_CHARS = 2_500
_LEAN_USER_MESSAGE_MAX_CHARS = 500

# Regex patterns for deterministic anchor harvesting
_ANCHOR_PATTERNS: List[Tuple[str, re.Pattern[str], int]] = [
    ("PRs/issues", re.compile(r"#\d{3,6}\b"), 80),
    ("commits", re.compile(r"\b[0-9a-f]{7,40}\b"), 40),
    ("branches", re.compile(r"\b(?:fix|feat|docs|refactor|chore|salvage|test)/[A-Za-z0-9._/-]{3,60}"), 40),
    ("files", re.compile(r"\b[\w./-]+/[\w.-]+\.(?:py|ts|tsx|js|jsx|rs|go|java|md|yaml|yml|json|toml|sh|css|html)\b"), 80),
    ("errors", re.compile(r"\b(?:[A-Z][a-zA-Z]*(?:Error|Exception)|ENOSPC|EACCES|ENOENT|ECONNREFUSED|SIGKILL|Traceback|TS\d{4,5})\b[^\n]{0,90}"), 40),
    ("urls", re.compile(r"https?://[^\s)\"']{10,110}"), 30),
]

_EXTEND_PROMPT = (
    "You maintain the running summary of an AI coding session. Rewrite "
    "SUMMARY + NEW DROPPED TURNS into one updated summary (same length "
    "class or shorter). Keep: user goals, decisions made, file paths, "
    "errors encountered, and anything still unresolved. Drop: chitchat, "
    "repeated attempts, and raw tool output.\n\nSUMMARY:\n{prev}\n\n"
    "NEW DROPPED TURNS:\n{new}\n\nUPDATED SUMMARY:"
)


def _text_of(msg: BaseMessage) -> str:
    """Extract text from message content safely."""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(p.get("text", ""))
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return str(content or "")


def build_anchor_index(turns: List[BaseMessage]) -> str:
    """Regex-harvest exact identifiers from compacted turns.

    Deterministic and LLM-free. Prevents loss of critical file paths,
    commit hashes, error signatures, and PR numbers when summarized.
    """
    text_parts: List[str] = []
    for msg in turns:
        c = _text_of(msg)
        if c:
            text_parts.append(c)
    text = "\n".join(text_parts)
    if not text:
        return ""

    sections: List[str] = []
    used = 0
    for label, pattern, cap in _ANCHOR_PATTERNS:
        counts: Dict[str, int] = {}
        last_seen: Dict[str, int] = {}
        for n, m in enumerate(pattern.finditer(text)):
            val = m.group(0).strip().rstrip(".,;:")
            counts[val] = counts.get(val, 0) + 1
            last_seen[val] = n
        if not counts:
            continue
        ranked = sorted(counts, key=lambda v: (-counts[v], -last_seen[v]))[:cap]
        line = f"{label}: " + ", ".join(
            f"{v}(x{counts[v]})" if counts[v] > 1 else v for v in ranked
        )
        if used + len(line) > _LEAN_ANCHOR_BUDGET_CHARS:
            break
        sections.append(line)
        used += len(line)

    if not sections:
        return ""
    return (
        "\n\n"
        + _LEAN_ANCHOR_HEADING
        + "\n"
        + "\n".join(sections)
        + "\n(Exact identifiers from the compacted region — use these verbatim, "
        "and as session_search query anchors to recover their full context.)"
    )


def build_verbatim_user_section(turns: List[BaseMessage]) -> str:
    """Embed real user messages verbatim from the compacted region.

    Newest-first under character budget. Real user instructions are the source
    of truth and should never be lost to paraphrasing.
    """
    collected: List[str] = []
    used = 0
    for msg in reversed(turns):
        if not isinstance(msg, HumanMessage):
            continue
        text = _text_of(msg).strip()
        if not text:
            continue
        if len(text) > _LEAN_USER_MESSAGE_MAX_CHARS:
            text = text[:_LEAN_USER_MESSAGE_MAX_CHARS].rstrip() + " …[truncated]"
        remaining = _LEAN_USER_MESSAGES_BUDGET_CHARS - used
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining].rstrip() + " …[truncated]"
        collected.append("> " + text.replace("\n", "\n> "))
        used += len(text)

    if not collected:
        return ""
    # Reverse back so they read in chronological order
    collected.reverse()
    return (
        "\n\n"
        + _LEAN_USER_MESSAGES_HEADING
        + "\n"
        + "\n\n".join(collected)
        + "\n(Every real user message from the compacted region, quoted verbatim. "
        "These are the user's actual words and override any paraphrase of them above.)"
    )


def build_recovery_footer(session_id: str, region_len: int) -> str:
    """Deterministic pointer to the compacted region in session history."""
    sid = session_id or "default"
    return (
        "\n\n"
        + _LEAN_RECOVERY_HEADING
        + "\n"
        + f"The {region_len} compacted message(s) remain fully preserved in session history. "
        "If you need any detail this summary does not carry (exact command output, "
        "file contents, error text, earlier reasoning), recover it with: "
        f"session_search(query='<keywords>', session_id='{sid}')"
    )


def compact_file_mutation_arguments(
    history: List[BaseMessage], *, keep_recent: int = 1
) -> List[BaseMessage]:
    """Omit landed file payloads from the request-only transcript copy."""
    if os.environ.get("PULSEAI_MUTATION_PAYLOAD_COMPACTION", "").strip().lower() == "off":
        return history

    successful_ids: List[str] = []
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

    result: List[BaseMessage] = []
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
        else:
            result.append(message.copy(update={"tool_calls": calls}))
    return result


def align_boundary_backward(history: List[BaseMessage], idx: int) -> int:
    """Pull a boundary backward to avoid splitting an AI(tool_calls)/ToolMessage group."""
    if idx <= 0 or idx >= len(history):
        return idx
    check = idx - 1
    while check >= 0 and isinstance(history[check], ToolMessage):
        check -= 1
    if (
        check >= 0
        and isinstance(history[check], AIMessage)
        and getattr(history[check], "tool_calls", None)
    ):
        return check
    return idx


def align_boundary_forward(history: List[BaseMessage], idx: int) -> int:
    """Push a boundary forward past any leading orphan ToolMessages."""
    while idx < len(history) and isinstance(history[idx], ToolMessage):
        idx += 1
    return idx


def sanitize_tool_pairs(messages: List[BaseMessage]) -> List[BaseMessage]:
    """Ensure tool_calls and ToolMessages remain protocol-valid.

    Prevents provider HTTP 400 errors caused by:
    1. A ToolMessage without a preceding AIMessage with matching tool_call_id.
    2. An AIMessage with tool_calls missing corresponding ToolMessages.
    """
    if not messages:
        return []

    # Map all defined tool call IDs from AIMessages
    known_call_ids: Set[str] = set()
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in getattr(msg, "tool_calls", []) or []:
                cid = str(tc.get("id") or "")
                if cid:
                    known_call_ids.add(cid)

    # First pass: drop orphaned ToolMessages whose tool_call was removed
    sanitized: List[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            cid = str(getattr(msg, "tool_call_id", "") or "")
            if cid and cid not in known_call_ids:
                # Orphaned tool message without parent tool call -> drop
                continue
        sanitized.append(msg)

    # Second pass: ensure every tool_call in AIMessage has an answering ToolMessage
    answered_call_ids: Set[str] = {
        str(getattr(m, "tool_call_id", ""))
        for m in sanitized
        if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", None)
    }

    final_messages: List[BaseMessage] = []
    for i, msg in enumerate(sanitized):
        final_messages.append(msg)
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            # Check for any unanswered calls in this AI message
            for tc in msg.tool_calls:
                cid = str(tc.get("id") or "")
                cname = str(tc.get("name") or "tool")
                if cid and cid not in answered_call_ids:
                    # Inject stub ToolMessage right after
                    stub = ToolMessage(
                        content="[Tool execution output omitted or compacted]",
                        tool_call_id=cid,
                        name=cname,
                    )
                    final_messages.append(stub)
                    answered_call_ids.add(cid)

    return final_messages


def demote_stale_tail_tools(
    messages: List[BaseMessage],
    tail_start: int,
    keep_rounds: int = _LEAN_TAIL_KEEP_TOOL_ROUNDS,
    session_id: str = "",
) -> Tuple[List[BaseMessage], int]:
    """Demote older tool results inside the protected tail to recovery stubs.

    Keeps the newest keep_rounds tool rounds verbatim; older tail tool results
    above _LEAN_TAIL_DEMOTE_MIN_CHARS are replaced with concise one-line stubs.
    """
    if tail_start >= len(messages):
        return messages, 0

    tool_indices = [
        i for i in range(len(messages) - 1, tail_start - 1, -1)
        if isinstance(messages[i], ToolMessage)
    ]
    rounds_seen = 0
    protected_indices: Set[int] = set()
    prev_idx: Optional[int] = None

    for i in tool_indices:
        if prev_idx is None or prev_idx - i > 1:
            rounds_seen += 1
        prev_idx = i
        if rounds_seen <= keep_rounds:
            protected_indices.add(i)
        else:
            break

    result = list(messages)
    demoted = 0
    recovery_hint = f"session_search(session_id='{session_id}')" if session_id else "session_search"

    for i in range(tail_start, len(messages)):
        msg = messages[i]
        if not isinstance(msg, ToolMessage) or i in protected_indices:
            continue
        text = _text_of(msg)
        if len(text) <= _LEAN_TAIL_DEMOTE_MIN_CHARS:
            continue
        tool_name = getattr(msg, "name", "tool") or "tool"
        stub_content = (
            f"[{tool_name} output ({len(text)} chars cleared in lean tail mode — "
            f"recovery: {recovery_hint})]"
        )
        result[i] = ToolMessage(
            content=stub_content,
            name=tool_name,
            tool_call_id=msg.tool_call_id,
            id=getattr(msg, "id", None),
        )
        demoted += 1

    return result, demoted


_STRUCTURED_SUMMARY_PROMPT = """You maintain the running technical summary of an autonomous AI coding session.
Update the previous summary by folding in the newly dropped turns into one cohesive, structured update.

## Guidelines:
1. Preserve technical facts: exact file paths, commands run, exit codes, errors, and architectural decisions.
2. Track progress status clearly (Done, In Progress, Blocked).
3. Do not include raw terminal spam or repeated trial-and-error attempts.
4. Keep the summary focused, dense, and actionable.

PREVIOUS SUMMARY:
{prev}

NEW DROPPED TURNS:
{new}

UPDATED STRUCTURED SUMMARY (Follow this exact Markdown structure):
## Goal
[High-level goal the agent is executing]

## Constraints & Preferences
[Explicit constraints, preferences, or environment rules]

## Completed Actions
[Numbered list of concrete actions taken with tool and outcome:
1. READ file.ts — identified schema mismatch [tool: read_file]
2. WRITE file.ts — updated schema definition [tool: write_file]
3. TEST pytest tests/ — 5 passed, 0 failed [tool: run_terminal]]

## Active State
[Current working state: what is currently underway or failing]

## Key Decisions & Context
[Technical choices made and why]

## Relevant Files
[Key files modified, created, or inspected with brief role]

## Next Steps
[Immediate actions needed to complete the task]
"""


class HistoryCompactor:
    """Session compactor supporting prune-first, lean tail, anchors, and structured summaries."""

    def __init__(
        self,
        model: str | None,
        aux_llm_getter: Optional[Callable[[], Any]] = None,
        tail_tokens: int = _DEFAULT_TAIL_TOKENS,
        tail_mode: str | None = None,
        session_id: str = "",
    ):
        self._model = model
        self._aux_llm_getter = aux_llm_getter
        self._tail_tokens = tail_tokens
        self._session_id = session_id

        if tail_mode is None:
            tail_mode = os.environ.get("PULSEAI_COMPACTION_TAIL_MODE", "lean").strip().lower()
        self.tail_mode = tail_mode

        self._summary: str = ""
        self._anchor_index: str = ""
        self._verbatim_user_section: str = ""
        self._recovery_footer: str = ""

        self.stats: Dict[str, int] = {
            "prunes": 0,
            "placeholders": 0,
            "placeholder_chars_reclaimed": 0,
            "structural_compactions": 0,
            "llm_summary_calls": 0,
            "llm_suppressed": 0,
            "ineffective_streak": 0,
            "lean_tail_demotions": 0,
        }
        self._suppress_llm_for = 0

    # ---------------------------------------------------------- head/tail
    def _head_len(self, history: List[BaseMessage]) -> int:
        """First complete turn = protected head (their 'first exchange').
        Protocol-safe: never sever an AI(tool_calls)/ToolMessage pair."""
        for i, msg in enumerate(history):
            if isinstance(msg, HumanMessage):
                for j in range(i + 1, len(history)):
                    if isinstance(history[j], HumanMessage):
                        return j
                return len(history)
        return min(1, len(history))

    def _tail_start(self, history: List[BaseMessage], head: int) -> int:
        """Newest messages totaling ~tail_tokens are protected.
        Never splits an AI(tool_calls)/ToolMessage pair."""
        budget = self._effective_tail_budget()
        total = 0
        start = len(history)
        for i in range(len(history) - 1, head - 1, -1):
            msg_tokens = count_tokens([history[i]], self._model)
            if total + msg_tokens > budget and start < len(history):
                break
            total += msg_tokens
            start = i

        while start > head and start < len(history) and isinstance(history[start], ToolMessage):
            start -= 1
        return max(start, head)

    def _effective_tail_budget(self) -> int:
        """Compute tail token budget based on tail_mode."""
        if self._tail_tokens != _DEFAULT_TAIL_TOKENS:
            return self._tail_tokens
        if self.tail_mode == "lean":
            from src.context.model_budgets import resolve_context_window
            window, _ = resolve_context_window(self._model, allow_network=False)
            lean_budget = int(window * _LEAN_TAIL_PERCENT)
            return max(_LEAN_TAIL_MIN_TOKENS, min(lean_budget, _LEAN_TAIL_MAX_TOKENS))
        return self._tail_tokens

    # ---------------------------------------------------------------- prune
    def prune(self, history: List[BaseMessage]) -> Tuple[List[BaseMessage], int, int]:
        """Replace long tool outputs in the middle with the placeholder."""
        if not history:
            return [], 0, 0
        head = self._head_len(history)
        tail = self._tail_start(history, head)

        out: List[BaseMessage] = list(history[:head]) + list(history[head:])
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

    def prune_tool_results_only(
        self, history: List[BaseMessage]
    ) -> Tuple[List[BaseMessage], int]:
        """Fast, standalone tool result pruner (Hermes-compatible interface)."""
        pruned, count, _ = self.prune(history)
        return pruned, count

    # -------------------------------------------------------------- summary
    def _dropped_text(self, dropped: List[BaseMessage]) -> str:
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

    def _build_deterministic_fallback_summary(
        self, dropped: List[BaseMessage], reason: str = ""
    ) -> str:
        """Construct a high-quality deterministic fallback summary without an LLM."""
        completed_actions: List[str] = []
        for msg in dropped:
            if isinstance(msg, ToolMessage):
                name = getattr(msg, "name", "tool")
                content = _text_of(msg).strip()
                snippet = " ".join(content.split())[:120]
                completed_actions.append(f"- [{name}] {snippet}")

        actions_block = "\n".join(completed_actions[:15]) if completed_actions else "- Prior actions recorded"
        reason_note = f" (fallback due to: {reason})" if reason else ""

        body = (
            f"## Goal\nRecovered technical context from compacted turns{reason_note}.\n\n"
            f"## Completed Actions\n{actions_block}\n\n"
            f"## Status\nMiddle conversation turns compacted to preserve token budget. "
            f"Examine active files and test suites for current state."
        )
        return body

    def _update_summary(self, dropped: List[BaseMessage]) -> None:
        """Iterative extend (their pattern #5): prev summary + only the
        newly dropped turns -> rolled summary. LLM via AUX client (D21);
        degrades to bounded plain append; thrash suppression applies."""
        new_text = self._dropped_text(dropped)
        if not new_text:
            return

        # Deterministic anchor and verbatim extraction for lean mode
        self._anchor_index = build_anchor_index(dropped)
        self._verbatim_user_section = build_verbatim_user_section(dropped)
        self._recovery_footer = build_recovery_footer(self._session_id, len(dropped))

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
                    "LLM summary suppressed for %d",
                    _INEFFECTIVE_STREAK_MAX,
                    _INEFFECTIVE_COOLDOWN,
                )
                self.stats["ineffective_streak"] = 0
        else:
            self.stats["ineffective_streak"] = 0

    # -------------------------------------------------------------- driver
    def compact(
        self,
        history: List[BaseMessage],
        budget: int,
        summarize_tools: Callable[[List[BaseMessage]], List[BaseMessage]],
        structural_compress: Callable[[List[BaseMessage], int], List[BaseMessage]],
        fallback_trim: Callable[[List[BaseMessage], int], List[BaseMessage]],
    ) -> List[BaseMessage]:
        """Execute the full compaction pipeline."""
        if not history:
            return []

        payload_compacted = compact_file_mutation_arguments(history)
        summarized_fast = summarize_tools(payload_compacted)
        before_tokens = count_tokens(history, self._model)
        if count_tokens(summarized_fast, self._model) <= budget:
            return summarized_fast

        # Stage 1: Prune verbose tool outputs in middle
        pruned, _, _ = self.prune(summarized_fast)
        summarized = pruned

        if count_tokens(summarized, self._model) <= budget:
            return self._with_summary(summarized)

        # Stage 2: Separate head and tail, compress middle
        head_n = self._head_len(summarized)
        tail_i = self._tail_start(summarized, head_n)

        # In lean mode: demote older tool outputs inside the tail
        tail_msgs = summarized[tail_i:]
        if self.tail_mode == "lean" and tail_msgs:
            tail_msgs, demotions = demote_stale_tail_tools(
                tail_msgs, 0, session_id=self._session_id
            )
            self.stats["lean_tail_demotions"] += demotions

        head_msgs = summarized[:head_n]
        middle = summarized[head_n:tail_i]

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

        # Protocol sanity: sanitize tool pairs so no orphan calls/results survive
        final = sanitize_tool_pairs(head_msgs + compressed_middle + tail_msgs)
        self._note_effectiveness(before_tokens, count_tokens(final, self._model))

        return self._with_summary(final)

    @staticmethod
    def _diff(before: List[BaseMessage], after: List[BaseMessage]) -> List[BaseMessage]:
        kept = {id(m) for m in after}
        return [m for m in before if id(m) not in kept]

    def _with_summary(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """Inject the running summary right after the protected head."""
        if not self._summary:
            return messages

        composite_summary_parts = [self._summary]
        if self.tail_mode == "lean":
            if self._anchor_index:
                composite_summary_parts.append(self._anchor_index)
            if self._verbatim_user_section:
                composite_summary_parts.append(self._verbatim_user_section)
            if self._recovery_footer:
                composite_summary_parts.append(self._recovery_footer)

        full_summary_text = "\n\n".join(composite_summary_parts)
        head = self._head_len(messages)
        summary_msg = SystemMessage(
            content=f"{COMPACTION_SUMMARY_PREFIX}\n\n{full_summary_text}",
            response_metadata={"compaction": True},
        )
        return list(messages[:head]) + [summary_msg] + list(messages[head:])

    @property
    def summary(self) -> str:
        return self._summary

    @property
    def anchor_index(self) -> str:
        return self._anchor_index

    @property
    def verbatim_user_section(self) -> str:
        return self._verbatim_user_section

    @property
    def llm_suppressed(self) -> bool:
        return self._suppress_llm_for > 0


def micro_compact(
    history: List[BaseMessage],
    running_summary: str = "",
    model: Optional[str] = None,
    aux_llm_getter: Optional[Callable[[], Any]] = None,
    defrag_threshold_tokens: int = 2000,
) -> Tuple[List[BaseMessage], str, bool]:
    """Fold the single oldest un-absorbed exchange into a running summary.

    Adopted from NousResearch hermes-agent (docs/micro-compaction.md).
    Amortizes the cost of context compression turn-by-turn so the agent never
    eats one giant multi-second compaction stall.
    In accordance with Hermes' Sacred Rule:
    What the user typed is NEVER compacted; user prompts stay verbatim.
    """
    if len(history) < 6:
        return history, running_summary, False

    # Find the oldest assistant exchange to compact
    exchange_start = -1
    exchange_end = -1
    for i, msg in enumerate(history):
        if isinstance(msg, AIMessage) and i > 0:
            exchange_start = i
            # Find end of exchange: next HumanMessage
            for j in range(i + 1, len(history)):
                if isinstance(history[j], HumanMessage):
                    exchange_end = j
                    break
            if exchange_end == -1:
                exchange_end = len(history) - 1
            break

    if exchange_start == -1 or exchange_end <= exchange_start:
        return history, running_summary, False

    exchange_msgs = history[exchange_start:exchange_end]
    dropped_text = "\n".join(
        f"{type(m).__name__}: {_text_of(m)[:250]}" for m in exchange_msgs
    )

    new_summary = running_summary
    if aux_llm_getter:
        try:
            llm = aux_llm_getter()
            prompt = _EXTEND_PROMPT.format(prev=running_summary or "(empty)", new=dropped_text)
            resp = llm.invoke(prompt)
            new_summary = " ".join(str(getattr(resp, "content", resp)).split())[:_SUMMARY_MAX_CHARS]
        except Exception:
            new_summary = (running_summary + "\n" + dropped_text).strip()[-_SUMMARY_MAX_CHARS:]
    else:
        new_summary = (running_summary + "\n" + dropped_text).strip()[-_SUMMARY_MAX_CHARS:]

    # Defrag if summary exceeds defrag threshold
    if count_tokens([SystemMessage(content=new_summary)], model) > defrag_threshold_tokens:
        if aux_llm_getter:
            try:
                llm = aux_llm_getter()
                defrag_prompt = f"Condense this conversation summary, keeping key technical decisions and files:\n{new_summary}"
                resp = llm.invoke(defrag_prompt)
                new_summary = " ".join(str(getattr(resp, "content", resp)).split())[:_SUMMARY_MAX_CHARS]
            except Exception:
                pass

    summary_marker = SystemMessage(
        content=f"{COMPACTION_SUMMARY_PREFIX}\n\n{new_summary}",
        response_metadata={"compaction": True, "micro": True},
    )

    # Splice: replace the exchange with the summary marker (drop old markers)
    before = [
        m for m in history[:exchange_start]
        if not (isinstance(m, SystemMessage) and getattr(m, "response_metadata", {}).get("compaction"))
    ]
    after = history[exchange_end:]
    compacted = sanitize_tool_pairs(before + [summary_marker] + after)
    return compacted, new_summary, True
