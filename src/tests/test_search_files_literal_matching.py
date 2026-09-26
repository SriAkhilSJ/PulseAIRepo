"""CrusorAI — ``search_files`` must report and repair what it searched for.

A field run of the Crusor Preview batch harness (third live session) showed the failure this file
pins. The agent, told to locate `btn btn-primary`, sent three reordered searches with regex escapes:

    search_files(path=., pattern=\\.btn-primary)   ->  No results found for '' in '.'
    search_files(path=., pattern=btn-primary|\\.btn) ->  No results found for '' in '.'
    search_files(path=., pattern=\\.btn)            ->  No results found for '' in '.'

and then invented a class that exists nowhere (`btn-lg`) and spent the rest of the turn in the
terminal. Two defects, both here, both now pinned:

* **the message named the wrong variable.** ``search_files`` reports ``query`` — the legacy alias,
  empty whenever the caller sends ``pattern`` — so every miss read as *empty pattern*. It looked like
  the tool had dropped the argument; the real pattern was never shown and the model's only recovery
  was to guess.
* **the miss taught nothing.** ``pattern`` is a literal substring match, so ``\\.btn`` searches for a
  backslash that is not in the file. Nothing said so. The miss now names a pattern that *does* match,
  with a real example line, whenever a de-escaped form of the needle hits.

Reordering was the first theory for this and it is false: ``tool.invoke`` receives a dict, so key
order cannot matter, and the log's "reversed order" calls were simply the regex ones. That is pinned
here too, so nobody re-introduces positional argument handling on the strength of that log.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.tools.file_tools import search_code, search_files

FIXTURE = Path(__file__).resolve().parents[2] / "preview-lab" / "demo-app"


@pytest.fixture()
def config():
    assert FIXTURE.is_dir(), f"the lab fixture moved: {FIXTURE}"
    return {"configurable": {"workspace": str(FIXTURE), "task_id": "search-files-test"}}


def search(pattern: str, config, path: str = ".") -> str:
    return search_files.invoke({"pattern": pattern, "path": path}, config=config)


# ── the miss must name the pattern that was actually used ────────────────────────────────

def test_a_miss_names_the_pattern_the_caller_sent(config) -> None:
    message = search("hero-titel", config)  # a typo, not regex
    assert "hero-titel" in message, message
    assert "for '' in" not in message, "an empty pattern was reported instead of the real one"
    assert message.startswith("No results found for 'hero-titel' in '.'"), message


def test_the_legacy_alias_reports_the_same_way(config) -> None:
    """`search_code` forwards its `query` into `pattern`; the message must still name it."""
    message = search_code.invoke({"query": "nope-not-here", "path": "."}, config=config)
    assert "nope-not-here" in message, message
    assert "for '' in" not in message


# ── the miss must teach the repair, but only when the repair is provable ─────────────────

@pytest.mark.parametrize("pattern, expected", [
    (r"\.btn-primary", ".btn-primary"),
    (r"btn-primary|\.btn", "btn-primary"),
    (r"\.btn", ".btn"),
])
def test_a_regex_escaped_pattern_points_at_the_literal_one(config, pattern: str, expected: str) -> None:
    """Exactly the three searches the field run sent. Each has a literal form that does match."""
    message = search(pattern, config)
    assert pattern in message, f"the pattern actually used must be shown: {message}"
    assert expected in message, f"the literal form must be named: {message}"
    assert "literal text" in message and "Retry with the un-escaped pattern" in message, message
    # The teaching is only worth anything if it carries evidence: a real line from a real file.
    assert any(marker in message for marker in ("styles.css:", "index.html:", "app.js:")), message


def test_the_hint_is_not_claimed_when_the_literal_form_does_not_match_either(config) -> None:
    """Honesty over helpfulness: a de-escaped form that finds nothing must not be suggested."""
    message = search(r"\d{4}-\d{2}-\d{2}", config)
    assert "Retry with the un-escaped pattern" not in message, message
    assert message.startswith(r"No results found for '\d{4}-\d{2}-\d{2}'"), message


def test_a_plain_miss_stays_short(config) -> None:
    """No noise on the ordinary path: a literal search that simply found nothing says only that."""
    message = search("nothing-like-this-exists", config)
    assert "Note:" not in message, message
    assert "literal text" not in message, message
    assert message.endswith("in '.'."), message


# ── hits are untouched ──────────────────────────────────────────────────────────────────

def test_a_literal_pattern_still_returns_matches(config) -> None:
    output = search("hero-title", config)
    assert "index.html:45" in output and "hero-title" in output, output


def test_the_escaped_form_of_a_working_search_is_still_a_miss(config) -> None:
    """The point of the bug: the same intent, escaped, is a different (empty) search."""
    # `.btn-primary` (with the dot, as it appears in the stylesheet) matches…
    assert "styles.css:74" in search(".btn-primary", config)
    # …and escaping the dot — the same intent the model had — finds nothing at all.
    assert "No results found" in search(r"\.btn-primary", config)


# ── the refuted theory, pinned so it cannot come back ───────────────────────────────────

def test_argument_order_is_irrelevant(config) -> None:
    """The log looked like arg reordering dropped the pattern. It did not.

    `_run_one` invokes `tool.invoke(args_dict)`, so key order is irrelevant; the calls that
    returned nothing were the regex-escaped ones, which is a different bug with a different fix.
    """
    pattern_first = search_files.invoke({"pattern": "hero-title", "path": "."}, config=config)
    path_first = search_files.invoke({"path": ".", "pattern": "hero-title"}, config=config)
    assert pattern_first == path_first

    miss_pattern_first = search_files.invoke({"pattern": r"\.btn", "path": "."}, config=config)
    miss_path_first = search_files.invoke({"path": ".", "pattern": r"\.btn"}, config=config)
    assert miss_pattern_first == miss_path_first
    assert "No results found" in miss_pattern_first
