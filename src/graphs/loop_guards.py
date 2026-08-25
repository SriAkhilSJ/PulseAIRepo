"""Loop guards ported from hermes-agent's conversation discipline.

Two properties, both behavior-based (they watch WHAT the model did, never
what the user might have meant), both bounded:

1. ``consecutive_no_tool_ai_messages`` — hermes' loop law, expressed for a
   LangGraph router: a model that keeps replying WITHOUT tool calls is
   answering, not working. Hermes ends the turn on the first no-tool reply
   (with 2-3 bounded behavior re-prompts for stall intent / dropped calls).
   PulseAI keeps its bounded finish/verify nudges, but after
   ``NO_TOOL_TURN_LIMIT`` consecutive no-tool assistant replies the turn
   MUST conclude regardless of which loop (plan, replan, classifier
   misroute) produced them — the measured 20-lap turn ($0.12 for one
   question, founder-pbr004-1) must be structurally impossible.

2. ``is_repetition_dominated`` — faithful port of hermes-agent
   ``agent/repetition_guard.py`` (issue #86581: a degenerate model looped
   one fragment into a 60,698-char turn). Deliberately conservative: only
   LONG verbatim repeats (60+ chars, >=5 occurrences) covering a majority
   of the fragment trip the guard, so ordinary truncated responses are
   never blocked. Continuing such content is pointless — the next lap
   would stitch more echo into the answer.
"""
from __future__ import annotations

from typing import Any

# After this many consecutive no-tool assistant replies the turn concludes.
# 3 tolerates the legitimate shapes (answer + one clarification nudge +
# final) while capping the worst case at 3 wasted laps instead of 20.
NO_TOOL_TURN_LIMIT = 3

# --- repetition guard constants (hermes parity) ---------------------------
MIN_FRAGMENT_LENGTH = 400
_REPEAT_WINDOW = 60
_MIN_REPEAT_COUNT = 5
_DOMINANCE_RATIO = 0.5


def consecutive_no_tool_ai_messages(messages: list[Any]) -> int:
    """Count TRAILING assistant replies with no tool calls.

    The streak resets on any tool activity or new user input — only an
    unbroken run of text-only assistant messages counts. Behavior-based:
    it never inspects content or intent.
    """
    streak = 0
    for msg in reversed(messages):
        mtype = getattr(msg, "type", "")
        if mtype == "ai":
            if getattr(msg, "tool_calls", None):
                return 0  # tool activity: not a no-tool streak
            streak += 1
            continue
        # human / tool / system boundaries end the streak
        return streak
    return streak


def is_repetition_dominated(text: str) -> bool:
    """True when ``text`` is dominated by verbatim repeated fragments.

    Ported from hermes-agent repetition_guard.py — same constants, same
    conservative shape: a single 60+ char window appearing >=5 times and
    covering >=50% of a >=400-char fragment. Fail-open for non-strings,
    empty, or short inputs.
    """
    import math

    if not isinstance(text, str):
        return False
    n = len(text)
    if n < MIN_FRAGMENT_LENGTH:
        return False

    if _line_repetition_dominated(text, n):
        return True

    window = _REPEAT_WINDOW
    needed = max(_MIN_REPEAT_COUNT, math.ceil(n * _DOMINANCE_RATIO / window))
    counts: dict[str, int] = {}
    for i in range(n - window + 1):
        key = text[i : i + window]
        c = counts.get(key, 0) + 1
        if c >= needed:
            return True
        counts[key] = c
    return False


def _line_repetition_dominated(text: str, n: int) -> bool:
    counts: dict[str, int] = {}
    for line in text.splitlines():
        norm = line.strip()
        if not norm:
            continue
        counts[norm] = counts.get(norm, 0) + 1
    for line, c in counts.items():
        if c >= _MIN_REPEAT_COUNT and c * len(line) >= n * _DOMINANCE_RATIO:
            return True
    return False
