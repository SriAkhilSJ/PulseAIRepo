"""Nine-strategy fuzzy find-and-replace — hermes-agent parity (Floor 5).

Ported from hermes-agent ``tools/fuzzy_match.py`` (re-read at upstream
``b9dc790``, 2026-09; the design credits OpenCode's original chain). The
single most common real-world failure of a coding agent is a *patch that
didn't apply*: the model's old_string drifts from the file by whitespace,
indentation, escaping, or Unicode typography. This module makes the edit
land when the intent is unambiguous — and REFUSE with model-actionable
guidance when it isn't.

The chain, tried in order (first strategy with matches wins):
  1. exact                 — literal substring
  2. line_trimmed          — per-line strip
  3. whitespace_normalized — runs of whitespace collapse to one space
  4. indentation_flexible  — leading indentation ignored entirely
  5. escape_normalized     — literal ``\\n``/``\\t`` sequences vs real chars
  6. trimmed_boundary      — only first/last lines trimmed
  7. unicode_normalized    — smart quotes/dashes/NBSP family → ASCII
  8. block_anchor          — first+last lines anchor, similarity middle
  9. context_aware         — 50% per-line similarity threshold

Safety contracts carried over verbatim:
  * whitespace-only old_string is never an anchor;
  * identical old/new is an error, not a no-op;
  * ambiguity (multiple matches without replace_all) returns the MATCH
    LOCATIONS so the model can disambiguate in ONE follow-up;
  * similarity-based strategies (8, 9) are NEVER safe under replace_all;
  * escape-drift guard: ``\\'``/``\\"`` present in old+new but absent from
    the file region is tool-call serialization drift — block, don't write;
  * non-exact matches shift new_string's indentation to the file's actual
    indentation, and unescape ``\\t``/``\\r`` only when the matched region
    really contains the control characters;
  * unicode_normalized matches preserve the file's Unicode in the
    replacement (only the intended change is applied).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable, List, Optional, Tuple

Match = Tuple[int, int]  # (start_char, end_char) into the ORIGINAL content

IDENTICAL_STRINGS_ERROR = (
    "No edit was applied because old_string and new_string are identical. "
    "Provide the existing text to replace in old_string and the changed "
    "replacement text in new_string."
)

UNICODE_MAP = {
    "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
    "\u2014": "--", "\u2013": "-", "\u2026": "...", "\u00a0": " ",
    "\u2212": "-",
    "\u2000": " ", "\u2001": " ", "\u2002": " ", "\u2003": " ",
    "\u2004": " ", "\u2005": " ", "\u2006": " ", "\u2007": " ",
    "\u2008": " ", "\u2009": " ", "\u200a": " ", "\u202f": " ",
    "\u205f": " ", "\u3000": " ",
}

_SIMILARITY_STRATEGIES = {"block_anchor", "context_aware"}

_BACKSLASH_RUN_RE = re.compile(r"\\+")
_INDENT_RE = re.compile(r"^[ \t]*")


def _unicode_normalize(text: str) -> str:
    for char, repl in UNICODE_MAP.items():
        text = text.replace(char, repl)
    return text


def is_already_applied(content: str, old_string: str, new_string: str) -> bool:
    """True when the requested edit already landed (hermes parity).

    Conservative by design: new_string must be non-trivial (>= 8 stripped
    chars), present EXACTLY, and — when it differs from old_string — the
    old text must be GONE. Turns the most common patch failure (re-sending
    a landed edit) into a success-shaped no-op.
    """
    if not new_string or len(new_string.strip()) < 8:
        return False
    if new_string not in content:
        return False
    if old_string == new_string:
        return True
    return old_string not in content


def _format_match_locations(content: str, matches: list[Match], cap: int = 5) -> str:
    rows = []
    for start, _end in matches[:cap]:
        line_no = content.count("\n", 0, start) + 1
        line_start = content.rfind("\n", 0, start) + 1
        line_end = content.find("\n", line_start)
        if line_end == -1:
            line_end = len(content)
        snippet = content[line_start:line_end].strip()
        if len(snippet) > 80:
            snippet = snippet[:77] + "..."
        rows.append(f"  L{line_no}: {snippet}")
    if len(matches) > cap:
        rows.append(f"  ... and {len(matches) - cap} more")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Strategy 1 — exact
# ---------------------------------------------------------------------------

def _strategy_exact(content: str, pattern: str) -> list[Match]:
    matches: list[Match] = []
    start = 0
    while True:
        idx = content.find(pattern, start)
        if idx == -1:
            return matches
        matches.append((idx, idx + len(pattern)))
        start = idx + len(pattern)


# ---------------------------------------------------------------------------
# Shared: normalized-line matching with a mapping back to original offsets.
# ``transform`` maps a raw line to its comparison form.
# ---------------------------------------------------------------------------

def _find_line_matches(
    content: str, pattern: str, transform: Callable[[str], str]
) -> list[Match]:
    pattern_lines = pattern.split("\n")
    pattern_norm = "\n".join(transform(line) for line in pattern_lines)
    content_lines = content.split("\n")
    content_norm = [transform(line) for line in content_lines]

    needle = pattern_norm
    matches: list[Match] = []
    start_line = 0
    while start_line <= len(content_norm) - len(pattern_norm.split("\n")):
        window = "\n".join(content_norm[start_line:start_line + len(pattern_lines)])
        if window == needle:
            # Map back to ORIGINAL char offsets: the window starts at the
            # first line's start and ends at the last line's end.
            start_off = len("\n".join(content_lines[:start_line]))
            if start_line:
                start_off += 1  # the joining newline
            end_line = start_line + len(pattern_lines) - 1
            end_off = start_off + len("\n".join(content_lines[start_line:end_line + 1]))
            matches.append((start_off, end_off))
            start_line += len(pattern_lines)  # non-overlapping, like upstream
        else:
            start_line += 1
    return matches


def _strategy_line_trimmed(content: str, pattern: str) -> list[Match]:
    return _find_line_matches(content, pattern, lambda line: line.strip())


def _strategy_whitespace_normalized(content: str, pattern: str) -> list[Match]:
    def collapse(line: str) -> str:
        return re.sub(r"[ \t]+", " ", line.strip())
    return _find_line_matches(content, pattern, collapse)


def _strategy_indentation_flexible(content: str, pattern: str) -> list[Match]:
    return _find_line_matches(content, pattern, lambda line: line.strip())


def _strategy_escape_normalized(content: str, pattern: str) -> list[Match]:
    # ``\\n`` is intentionally excluded (hermes rule): newlines serialize
    # correctly through JSON, and rewriting backslash-n mangles source-code
    # escape sequences far more often than it helps. \\t and \\r only.
    def unescape(line: str) -> str:
        return line.replace("\\t", "\t").replace("\\r", "\r").strip()
    return _find_line_matches(content, pattern, unescape)


def _strategy_trimmed_boundary(content: str, pattern: str) -> list[Match]:
    """Only the FIRST and LAST lines of the pattern are trimmed — interior
    lines must match exactly. Catches the 'model included the block but
    typo'd the boundary whitespace' case without loosening the middle."""
    pattern_lines = pattern.split("\n")
    if len(pattern_lines) < 2:
        return []
    first = pattern_lines[0].strip()
    last = pattern_lines[-1].strip()
    interior = pattern_lines[1:-1]

    content_lines = content.split("\n")
    matches: list[Match] = []
    for i in range(len(content_lines) - len(pattern_lines) + 1):
        if content_lines[i].strip() != first:
            continue
        if content_lines[i + len(pattern_lines) - 1].strip() != last:
            continue
        if content_lines[i + 1:i + 1 + len(interior)] != interior:
            continue
        start_off = len("\n".join(content_lines[:i]))
        if i:
            start_off += 1
        end_line = i + len(pattern_lines) - 1
        end_off = start_off + len("\n".join(content_lines[i:end_line + 1]))
        matches.append((start_off, end_off))
    return matches


def _strategy_unicode_normalized(content: str, pattern: str) -> list[Match]:
    return _find_line_matches(
        _unicode_normalize(content), _unicode_normalize(pattern),
        lambda line: line.strip(),
    ) if _unicode_normalize(pattern) != pattern or _unicode_normalize(content) != content else []


def _strategy_block_anchor(content: str, pattern: str) -> list[Match]:
    """First+last lines anchor exactly (unicode-normalized); the middle only
    needs ~similar lines. One candidate → accept; multiple → highest mean
    similarity wins; below 0.6 mean → reject."""
    norm_pattern = _unicode_normalize(pattern)
    norm_content = _unicode_normalize(content)
    pattern_lines = [line.strip() for line in norm_pattern.split("\n")]
    if len(pattern_lines) < 2:
        return []
    first, last = pattern_lines[0], pattern_lines[-1]
    middle = pattern_lines[1:-1]

    norm_lines = norm_content.split("\n")
    orig_lines = content.split("\n")
    n = len(pattern_lines)

    candidates: list[int] = []
    for i in range(len(norm_lines) - n + 1):
        if norm_lines[i].strip() == first and norm_lines[i + n - 1].strip() == last:
            candidates.append(i)
    if not candidates:
        return []

    def middle_score(idx: int) -> float:
        if not middle:
            return 1.0
        ratios = [
            SequenceMatcher(None, m, norm_lines[idx + 1 + j].strip()).ratio()
            for j, m in enumerate(middle)
        ]
        return sum(ratios) / len(ratios)

    scored = [(middle_score(i), i) for i in candidates]
    best_score, best_idx = max(scored)
    if best_score < 0.6:
        return []

    start_off = len("\n".join(orig_lines[:best_idx]))
    if best_idx:
        start_off += 1
    end_line = best_idx + n - 1
    end_off = start_off + len("\n".join(orig_lines[best_idx:end_line + 1]))
    return [(start_off, end_off)]


def _strategy_context_aware(content: str, pattern: str) -> list[Match]:
    """Sliding window; a window matches when >=50% of its lines are similar
    (ratio >= 0.5) to the pattern's lines. Last-resort: picks a region, so
    it is similarity-class and never eligible for replace_all."""
    pattern_lines = [line.strip() for line in pattern.split("\n")]
    if not pattern_lines or not any(line.strip() for line in pattern_lines):
        return []
    content_lines = content.split("\n")
    n = len(pattern_lines)
    if len(content_lines) < n:
        return []

    def window_score(idx: int) -> float:
        ratios = [
            SequenceMatcher(None, p, content_lines[idx + j].strip()).ratio()
            for j, p in enumerate(pattern_lines)
            if p  # blank pattern lines are structural, not evidence
        ]
        if not ratios:
            return 0.0
        good = sum(1 for r in ratios if r >= 0.5)
        return good / len(ratios)

    matches: list[Match] = []
    i = 0
    while i <= len(content_lines) - n:
        if window_score(i) >= 0.5:
            start_off = len("\n".join(content_lines[:i]))
            if i:
                start_off += 1
            end_line = i + n - 1
            end_off = start_off + len("\n".join(content_lines[i:end_line + 1]))
            matches.append((start_off, end_off))
            i += n  # non-overlapping
        else:
            i += 1
    return matches


# ---------------------------------------------------------------------------
# Replacement with indentation shift + escape hygiene
# ---------------------------------------------------------------------------

def _indent_of(line: str) -> str:
    return _INDENT_RE.match(line).group(0)  # type: ignore[union-attr]


def _apply_replacements(
    content: str,
    matches: list[Match],
    new_string: str,
    old_string: Optional[str] = None,
) -> str:
    """Apply replacements right-to-left so offsets stay valid. With an
    ``old_string`` (non-exact strategies), shift new_string's indentation
    per-line to match the replaced region's first-line indentation delta."""
    result = content
    for start, end in reversed(matches):
        replacement = new_string
        if old_string is not None:
            old_first = _indent_of(old_string.split("\n", 1)[0]) or None
            new_first = _indent_of(new_string.split("\n", 1)[0])
            region = result[start:end]
            region_first = _indent_of(region.split("\n", 1)[0])
            if old_first is not None and region_first != old_first:
                delta = region_first[len(old_first):] if region_first.startswith(old_first) else region_first
                if new_first + "" == _indent_of(new_string.split("\n", 1)[0]):
                    shifted_lines = [
                        (delta + line if line.strip() else line)
                        for line in new_string.split("\n")
                    ]
                    replacement = "\n".join(shifted_lines)
        result = result[:start] + replacement + result[end:]
    return result


def _maybe_unescape_new_string(
    new_string: str, content: str, matches: list[Match]
) -> str:
    """Unescape ``\\t``/``\\r`` ONLY when the matched region really contains
    the control character (hermes region-based heuristic; ``\\n`` excluded —
    newlines serialize correctly and rewriting them mangles source)."""
    region = "".join(content[s:e] for s, e in matches)
    out = new_string
    if "\t" in region and "\\t" in out:
        out = out.replace("\\t", "\t")
    if "\r" in region and "\\r" in out:
        out = out.replace("\\r", "\r")
    return out


def _norm_to_raw_index_map(raw: str) -> tuple[list[str], list[int]]:
    """Per-normalized-char raw indexes: norm_chars[k] came from raw[map[k]].
    One raw char may expand to several normalized chars (-- from —)."""
    norm_chars: list[str] = []
    raw_idx: list[int] = []
    for i, ch in enumerate(raw):
        repl = _unicode_normalize(ch)
        for c in repl:
            norm_chars.append(c)
            raw_idx.append(i)
    return norm_chars, raw_idx


def _preserve_unicode_in_replacement(
    region: str, old_string: str, new_string: str
) -> str:
    """Unicode-preservation guard (hermes parity, strategy 7 companion).

    The file has typography (— “ ” …); the model typed ASCII (-- " " ...).
    Writing new_string verbatim would silently corrupt the file's Unicode.
    The UNCHANGED portion of new_string (blocks where it equals old_string)
    inherits the region's actual characters; only the intended edit is new.
    """
    sm = SequenceMatcher(None, old_string, new_string)
    out = new_string
    # Walk equal blocks right-to-left so substitutions keep offsets valid.
    blocks = [op for op in sm.get_opcodes() if op[0] == "equal"]
    norm_region_chars, raw_idx = _norm_to_raw_index_map(region)
    norm_region = "".join(norm_region_chars)
    for _tag, a1, a2, b1, b2 in reversed(blocks):
        segment = old_string[a1:a2]
        if not segment:
            continue
        pos = norm_region.find(_unicode_normalize(segment))
        if pos == -1:
            continue
        raw_start = raw_idx[pos]
        raw_end = raw_idx[pos + len(_unicode_normalize(segment)) - 1] + 1
        out = out[:b1] + region[raw_start:raw_end] + out[b2:]
    return out


def _detect_escape_drift(
    content: str, matches: list[Match], old_string: str, new_string: str
) -> Optional[str]:
    """Block tool-call serialization artifacts before they hit the file:
    ``\\'``/``\\"`` in old+new but absent from the matched region means a
    transport added spurious backslashes — writing would corrupt source."""
    has_quote_suspects = "\\'" in new_string or '\\"' in new_string
    if not has_quote_suspects:
        return None
    region = "".join(content[s:e] for s, e in matches)
    for suspect in ("\\'", '\\"'):
        if suspect in new_string and suspect in old_string and suspect not in region:
            plain = suspect[1]
            return (
                f"Escape-drift detected: old_string and new_string contain "
                f"the literal sequence {suspect!r} but the matched region of "
                f"the file does not. Re-read the file and pass old_string/"
                f"new_string without backslash-escaping {plain!r} characters."
            )
    return None


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------

def fuzzy_find_and_replace(
    content: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> Tuple[str, int, Optional[str], Optional[str]]:
    """The 9-strategy chain. Returns ``(new_content, count, strategy, error)``;
    on failure the original content and a model-actionable error come back."""
    if not old_string:
        return content, 0, None, "old_string cannot be empty"
    if not old_string.strip():
        return content, 0, None, (
            "old_string is only whitespace — provide non-blank text to match"
        )
    if old_string == new_string:
        return content, 0, None, IDENTICAL_STRINGS_ERROR

    strategies: list[tuple[str, Callable[[str, str], list[Match]]]] = [
        ("exact", _strategy_exact),
        ("line_trimmed", _strategy_line_trimmed),
        ("whitespace_normalized", _strategy_whitespace_normalized),
        ("indentation_flexible", _strategy_indentation_flexible),
        ("escape_normalized", _strategy_escape_normalized),
        ("trimmed_boundary", _strategy_trimmed_boundary),
        ("unicode_normalized", _strategy_unicode_normalized),
        ("block_anchor", _strategy_block_anchor),
        ("context_aware", _strategy_context_aware),
    ]

    for name, fn in strategies:
        matches = fn(content, old_string)
        if not matches:
            continue
        if len(matches) > 1 and not replace_all:
            return content, 0, None, (
                f"Found {len(matches)} matches for old_string. Provide more "
                f"context to make it unique, or use replace_all=True. "
                f"Matches:\n{_format_match_locations(content, matches)}"
            )
        if replace_all and len(matches) > 1 and name in _SIMILARITY_STRATEGIES:
            return content, 0, None, (
                f"Found {len(matches)} approximate matches via the '{name}' "
                f"strategy; replace_all only applies to exact matches. "
                f"Provide the precise text so an exact strategy can match."
            )
        if name != "exact":
            drift = _detect_escape_drift(content, matches, old_string, new_string)
            if drift:
                return content, 0, None, drift
        effective_new = _maybe_unescape_new_string(new_string, content, matches)
        if name == "unicode_normalized":
            region = content[matches[0][0]:matches[0][1]]
            effective_new = _preserve_unicode_in_replacement(
                region, old_string, effective_new
            )
        updated = _apply_replacements(
            content, matches, effective_new,
            old_string=old_string if name != "exact" else None,
        )
        return updated, len(matches), name, None

    return content, 0, None, "Could not find a match for old_string in the file"
