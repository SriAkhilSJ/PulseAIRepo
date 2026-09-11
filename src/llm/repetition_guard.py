# src/llm/repetition_guard.py
"""Degenerate-output detection for the truncated-response path.

Ported from hermes `agent/repetition_guard.py` (issue #86581: a model in a
degenerate repetition loop spent its ENTIRE output budget echoing one
fragment; the length continuation stitched it into the final response —
one incident delivered a 60k-char turn as 31 Discord messages). Hermes'
law: detect repetition-dominated fragments BEFORE the continuation nudge
so the turn aborts with a clear error instead. Deliberately conservative:
only LONG verbatim repeats (60+ chars) covering a majority of the fragment
trip the hermes check.

Field 2026-09-10 (owner, build 0a026b11): a `custom/auto/best-chat`
endpoint degenerated mid-task and the salad streamed into the panel at
full length. That slop was sampling collapse with VARYING text — the
hermes verbatim-repeat check alone does not cover it, so Pulse adds ONE
documented extension: word-loop dominance (a single 4+ letter word
dominating a long fragment). Same conservative dominance shape, numeric
thresholds via env read per call (PULSEAI_WORD_LOOP_SHARE, 0 disables;
PULSEAI_WORD_LOOP_MIN_CHARS). No word lists, no lexicons.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter

# ── hermes agent/repetition_guard.py, verbatim constants ────────────────────

# Below this length the check doesn't run: short truncations trivially
# contain repeated tokens and are legitimately continued.
MIN_FRAGMENT_LENGTH = 400
# Exact-repeat window; far beyond ordinary phrasing reuse (citations,
# headings, similar code).
_REPEAT_WINDOW = 60
# A window repeating at least this often is a signal even for short fragments.
_MIN_REPEAT_COUNT = 5
# "Repetition-dominated" = repeated windows cover at least this fraction.
_DOMINANCE_RATIO = 0.5

# ── Pulse word-loop extension (documented above) ────────────────────────────

_WORD_MIN_FRAGMENT = 1500
_WORD_MIN_REPEAT = 12
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def is_repetition_dominated(text: str) -> bool:
    """True when a single 60+ char substring recurs often enough to cover at least half
    of ``text`` — the signature of a repetition loop. Fail-open for non-string/short input.

    hermes agent/repetition_guard.py verbatim (issue #86581): continuing such a
    fragment is pointless — the continuation nudge would just stitch more
    repeated text into the final response.
    """
    if not isinstance(text, str):
        return False
    n = len(text)
    if n < MIN_FRAGMENT_LENGTH:
        return False

    # Fast path: one normalized line duplicated enough to cover half the
    # fragment (the common echo shape).
    if _line_repetition_dominated(text, n):
        return True

    # General path: fixed-size windows sliding one char at a time, catching
    # loops that don't align to line boundaries. A window must appear
    # ``needed`` times to cover >= _DOMINANCE_RATIO (and >= _MIN_REPEAT_COUNT).
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
    """True when a single normalized line covers half the fragment via repeats."""
    counts = Counter(norm for norm in (line.strip() for line in text.splitlines()) if norm)
    return any(c >= _MIN_REPEAT_COUNT and c * len(line) >= n * _DOMINANCE_RATIO for line, c in counts.items())


def _word_loop_share() -> float:
    """Top-word dominance threshold, read per call (standing env rule)."""
    try:
        return float(os.environ.get("PULSEAI_WORD_LOOP_SHARE", "0.25"))
    except (TypeError, ValueError):
        return 0.25


def _word_loop_min_chars() -> int:
    try:
        return int(os.environ.get("PULSEAI_WORD_LOOP_MIN_CHARS", str(_WORD_MIN_FRAGMENT)))
    except (TypeError, ValueError):
        return _WORD_MIN_FRAGMENT


def is_word_looped(text: str) -> bool:
    """Pulse extension: True when one 4+ letter word dominates a long fragment.

    Field 2026-09-10: the owner's degenerate run was WORD-anchored collapse
    ("continue"-family filling thousands of chars) with no long VERBATIM
    window, which hermes' conservative verbatim check deliberately lets
    through. Counting is numeric — lowercase unicode word runs, no lexicon.
    Defaults are conservative: fragment >= 1500 chars and >= 50 words, top
    word (4+ letters) covering >= 25% of all words. Real prose is led by
    short function words; a 4+ letter content word never approaches 25%
    there. PULSEAI_WORD_LOOP_SHARE=0 disables the extension entirely.
    """
    if not isinstance(text, str):
        return False
    share = _word_loop_share()
    if share <= 0:
        return False
    n = len(text)
    if n < _word_loop_min_chars():
        return False
    words = _WORD_RE.findall(text.lower())
    if len(words) < 50:
        return False
    top, count = Counter(words).most_common(1)[0]
    if len(top) < 4:
        return False
    return count >= max(_WORD_MIN_REPEAT, math.ceil(len(words) * share))


def is_degenerate_output(text: str) -> bool:
    """The Pulse predicate: hermes' verbatim check OR the word-loop dominance
    extension. Consulted only where hermes consults its guard — the
    length-truncated continuation path."""
    return is_repetition_dominated(text) or is_word_looped(text)


# hermes turn_truncation.py::_REPETITION_DOMINATED[1], adapted: Pulse has no
# /model slash command, so the advice names the env-config surface instead.
REPETITION_DOMINATED_NOTICE = (
    "⚠️ **Response Stopped — Repetition Detected**\n\n"
    "The model fell into a repetition loop while writing this response, so "
    "continuing would only produce more repeated text. The partial response "
    "was discarded.\n\n"
    "→ Switch to a different model (provider/model in your environment config)\n"
    "→ Or resend your message (your conversation history is preserved)"
)
