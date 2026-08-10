"""
Self-curation background loop (D38)
===================================
Hermes runs a post-turn background review thread ("self-improvement review")
that replays a snapshot of the conversation against a combined memory/skill
review prompt on the JANITOR (aux) model, then writes durable facts with the
memory tool (turn_context.py:625, background_review.py:1030).

PulseAI port, adapted to its shape:

  * Runs only after a whole agent run completes (stream_agent / invoke_agent),
    gated on a user-turn countdown (MEMORY_NUDGE_INTERVAL) — hermes'
    turns_since_memory gate.
  * Reviewing memory only. Skill lifecycle is D39's domain.
  * Bounded by construction: one review per trigger per session (in-flight
    markers), at most MEMORY_REVIEW_MAX_PREFS writes, digest capped upstream.
  * The review call bills at aux rates (factory.get_auxiliary_llm) and is a
    short daemon thread — it must never block the response or kill a turn.
  * Never raises into the caller; memory may be disabled (degraded boot).
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

# hermes _COMBINED_REVIEW_PROMPT (background_review.py:307), trimmed to the
# parts PulseAI can act on: durable user facts + preferences written to long-
# term memory. Style-correction lessons feed D39's skill pipeline instead.
_MEMORY_REVIEW_PROMPT = (
    "Review the conversation below and decide what, if anything, is worth "
    "saving to long-term memory.\n\n"
    "Focus on:\n"
    "1. Facts the user revealed about themselves — persona, desires, "
    "preferences, personal or project details worth remembering.\n"
    "2. Expectations about how you should behave — work style, formatting "
    "preferences, or durable ways they want you to operate.\n\n"
    "Rules:\n"
    "- Do NOT save: environment-dependent failures ('command not found', "
    "missing packages, unconfigured keys), negative claims about tools "
    "('X tool is broken'), transient errors that got resolved, or one-off "
    "task narratives.\n"
    "- Keep each memory a single short, self-contained sentence.\n"
    "- If nothing is worth saving, respond with exactly: {\"preferences\": []}\n\n"
    "Respond with ONLY a JSON object of the form: "
    "{\"preferences\": [\"<short preference 1>\", \"<short preference 2>\"]}"
)

_MAX_REVIEW_PREFS = int(os.environ.get("MEMORY_REVIEW_MAX_PREFS", "2"))
_MAX_REVIEW_CHARS = int(os.environ.get("MEMORY_REVIEW_DIGEST_CHARS", "12000"))

# Per-session in-flight guard: two rapid user messages must not start two
# concurrent reviews of the same thread.
_in_flight: dict[str, bool] = {}
_in_flight_lock = threading.Lock()

# Per-session user-turn counters (process-local; the dashboard is a single
# worker, and the counter mutation is lock-guarded for safety).
_turn_counts: dict[str, int] = {}
_turn_counts_lock = threading.Lock()

def _digest(messages: list) -> str:
    """Condense the conversation to what a reviewer needs: user and assistant
    text in order. Tool results and system layers are dropped — they are
    bulky and the reviewer only needs the facts exchanged."""
    parts: list[str] = []
    for msg in messages or []:
        kind = type(msg).__name__
        if kind in ("ToolMessage", "SystemMessage"):
            continue
        try:
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
        except Exception:
            continue
        if kind == "HumanMessage":
            parts.append(f"USER: {content.strip()}")
        elif kind == "AIMessage":
            # Strip thinking scratchpads if the provider stuffed them here.
            text = content.strip()
            if len(text) > 4000:
                text = text[:4000] + " [truncated]"
            parts.append(f"ASSISTANT: {text}")
    joined = "\n".join(parts)
    if len(joined) > _MAX_REVIEW_CHARS:
        joined = joined[-_MAX_REVIEW_CHARS:]
    return joined


def _parse_preferences(raw: str) -> list[str]:
    """Parse the aux model's JSON reply defensively: strip fences, accept a
    bare list or a {"preferences": [...]} object, fall back to bullet lines."""
    if not raw:
        return []
    if not isinstance(raw, str):
        return []
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    out: list[str] = []
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("preferences", [])
        if isinstance(data, list):
            out = [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    if not out:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or not stripped[0] in "-•*0123456789":
                continue
            item = stripped.lstrip("-•*0123456789. ").strip()
            if item and "preferences" not in item:
                out.append(item[:280])
        if len(out) < 2:
            # A single unparseable line is not a preference list.
            out = []
    # De-dup (order-preserving) and bound.
    unique: list[str] = []
    seen = set()
    for p in out:
        key = p.lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    return unique[:_MAX_REVIEW_PREFS]


def _review_snapshot(thread_id: str, messages: list) -> int:
    """Run ONE memory review against the snapshot and write findings.
    Returns how many preferences were written. Never raises."""
    from src.llm.factory import get_auxiliary_llm

    digest = _digest(messages)
    if not digest.strip():
        return 0
    try:
        llm = get_auxiliary_llm()
    except Exception as exc:
        print(f"[SelfReview] aux LLM unavailable ({exc!r}) — skipping")
        return 0

    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        response = llm.invoke([
            SystemMessage(content=_MEMORY_REVIEW_PROMPT),
            HumanMessage(content=digest),
        ])
    except Exception as exc:
        print(f"[SelfReview] aux review call failed ({exc!r})")
        return 0

    prefs = _parse_preferences(str(getattr(response, "content", "")))
    if not prefs:
        return 0

    # The memory write goes outside the lock (durable vector store); the
    # in-flight marker is cleared before writing so the NEXT snapshot can
    # start while slow embedding I/O finishes — why synchronous handoff.
    from src.graphs.chat_graph import memory_manager

    if memory_manager is None:
        print("[SelfReview] memory disabled (degraded boot) — skipping write")
        return 0
    written = 0
    for pref in prefs:
        try:
            memory_manager.store_preference(pref)
            written += 1
        except Exception as exc:
            print(f"[SelfReview] preference write failed ({exc!r})")
    if written:
        print(f"💾 Self-review: saved {written} user preference(s) to memory")
    return written


def _spawn(thread_id: str, messages: list) -> None:
    def _target() -> None:
        try:
            _review_snapshot(thread_id, messages)
        except Exception as exc:  # never leak a background failure
            print(f"[SelfReview] thread failed ({exc!r})")
        finally:
            with _in_flight_lock:
                _in_flight.pop(thread_id, None)

    try:
        t = threading.Thread(target=_target, daemon=True, name=f"self-review-{thread_id}")
        t.start()
    except Exception as exc:
        print(f"[SelfReview] spawn failed ({exc!r})")
        with _in_flight_lock:
            _in_flight.pop(thread_id, None)


def maybe_spawn_memory_review(
    thread_id: str,
    messages: list | None = None,
    *,
    force: bool = False,
) -> None:
    """Post-run hook: spawn a bounded background memory review.

    Gated on MEMORY_NUDGE_INTERVAL (default 8 user turns, 0 = off) and
    per-session in-flight markers. ``force`` bypasses the interval (used by
    tests and explicit /review triggers). Never raises.
    """
    try:
        interval = int(os.environ.get("MEMORY_NUDGE_INTERVAL", "8"))
    except ValueError:
        interval = 8
    if interval <= 0:
        return

    if not force:
# Per-thread turn counter (process-local; coarse but matches the
    # dashboard's single-worker reality).
        key = f"{thread_id}:turns"
        with _turn_counts_lock:
            count = _turn_counts.get(key, 0) + 1
            _turn_counts[key] = count
        if count % interval != 0:
            return

    with _in_flight_lock:
        if _in_flight.get(thread_id):
            return
        _in_flight[thread_id] = True

    if messages is None:
        # Snapshot the conversation from the checkpointer — the graph just
        # finished, so the state is ready to read.
        try:
            from src.graphs.chat_graph import graph
            config = {"configurable": {"thread_id": thread_id}}
            state = graph.get_state(config)
            messages = (state.values or {}).get("messages", []) if state else []
        except Exception:
            messages = []
    if not messages:
        with _in_flight_lock:
            _in_flight.pop(thread_id, None)
        return
    _spawn(thread_id, messages)