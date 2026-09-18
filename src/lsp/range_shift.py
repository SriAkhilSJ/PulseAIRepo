"""Diff-aware line-shift map for cross-edit LSP delta filtering.

When an edit deletes or inserts lines in the middle of a file, every
diagnostic below the edit point shifts to a new line number.  The
delta filter builds a piecewise-linear map from pre-edit line numbers
to post-edit line numbers, then applies that map to baseline
diagnostics before the set-difference.
"""
from __future__ import annotations

import difflib
from typing import Any, Callable, Dict, List, Optional


def build_line_shift(pre_text: str, post_text: str) -> Callable[[int], Optional[int]]:
    """Build a function mapping pre-edit line numbers to post-edit line numbers.

    Lines are 0-indexed to match the LSP wire format.
    """
    pre_lines = pre_text.splitlines() if pre_text else []
    post_lines = post_text.splitlines() if post_text else []

    if pre_lines == post_lines:
        return lambda line: line

    sm = difflib.SequenceMatcher(a=pre_lines, b=post_lines, autojunk=False)
    opcodes = sm.get_opcodes()

    def shift(line: int) -> Optional[int]:
        for tag, i1, i2, j1, j2 in opcodes:
            if i1 <= line < i2:
                if tag == "equal":
                    return line - i1 + j1
                if tag == "delete":
                    return None
                if tag == "replace":
                    return None
            if line < i1:
                break
        return max(0, len(post_lines) - 1) if post_lines else None

    return shift


def shift_diagnostic_range(diag: Dict[str, Any],
                           shift: Callable[[int], Optional[int]]) -> Optional[Dict[str, Any]]:
    """Return a copy of ``diag`` with its line range remapped through ``shift``.

    Returns ``None`` if the diagnostic's start line maps to ``None``.
    """
    rng = diag.get("range") or {}
    start = rng.get("start") or {}
    end = rng.get("end") or {}

    pre_start_line = int(start.get("line", 0))
    pre_end_line = int(end.get("line", pre_start_line))

    new_start_line = shift(pre_start_line)
    if new_start_line is None:
        return None

    new_end_line = shift(pre_end_line)
    if new_end_line is None:
        new_end_line = new_start_line

    shifted = dict(diag)
    shifted["range"] = {
        "start": {
            "line": new_start_line,
            "character": int(start.get("character", 0)),
        },
        "end": {
            "line": new_end_line,
            "character": int(end.get("character", 0)),
        },
    }
    return shifted


def shift_baseline(baseline: List[Dict[str, Any]],
                   shift: Callable[[int], Optional[int]]) -> List[Dict[str, Any]]:
    """Apply ``shift`` to every diagnostic in ``baseline``, dropping deleted entries."""
    out: List[Dict[str, Any]] = []
    for d in baseline:
        if not isinstance(d, dict):
            continue
        shifted = shift_diagnostic_range(d, shift)
        if shifted is not None:
            out.append(shifted)
    return out


__all__ = ["build_line_shift", "shift_diagnostic_range", "shift_baseline"]
