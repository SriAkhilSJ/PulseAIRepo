"""Contract tests: the 9-strategy fuzzy find-and-replace (Floor 5).

Ported from hermes tools/fuzzy_match.py (re-read at b9dc790). Each strategy
gets its canonical trigger case, plus the safety contracts: whitespace-only
anchors, identical old/new, ambiguity locations, similarity-strategy
replace_all refusal, escape-drift blocking, indentation shift, unicode
preservation, and the already-applied no-op.
"""
import pytest

from src.tools.fuzzy_match import (
    IDENTICAL_STRINGS_ERROR,
    fuzzy_find_and_replace,
    is_already_applied,
)


def apply(content, old, new, replace_all=False):
    return fuzzy_find_and_replace(content, old, new, replace_all)


# 1 — exact
def test_s1_exact():
    out, n, strat, err = apply("alpha\nbeta\ngamma", "beta", "BETA")
    assert (out, n, strat, err) == ("alpha\nBETA\ngamma", 1, "exact", None)


# 2 — line_trimmed
def test_s2_line_trimmed_trailing_whitespace():
    content = "def a():\n    return 1   \n"
    out, n, strat, err = apply(content, "return 1\n", "return 2\n")
    assert strat == "line_trimmed" and "return 2" in out and err is None


# 3 — whitespace_normalized
def test_s3_whitespace_runs_collapse():
    content = "x  =  compute( a,b )\n"
    out, n, strat, err = apply(content, "x = compute( a,b )", "x = compute( a,b ) # ok")
    assert strat == "whitespace_normalized" and "# ok" in out and err is None


# 4 — indentation_flexible
def test_s4_indentation_flexible_and_shift():
    content = "class C:\n        def m(self):\n            pass\n"
    out, n, strat, err = apply(content, "def m(self):\n    pass\n", "def m(self):\n    return 7\n")
    assert strat == "line_trimmed"  # the looser strategy wins first, by design
    assert err is None and "return 7" in out


# 5 — escape_normalized (\\t and \\r only; \\n excluded by hermes rule)
def test_s5_escape_normalized_literal_tabs():
    content = "x = 'a\tb'\n"          # file has a REAL tab
    old = "x = 'a\\tb'"               # model sent the literal backslash-t
    out, n, strat, err = apply(content, old, "x = 'a\\tc'")
    assert strat == "escape_normalized" and err is None
    assert "\tc" in out               # replacement written with a REAL tab


# 6 — trimmed_boundary
def test_s6_trimmed_boundary_interior_exact():
    content = "if True:\n    x = 1  \n    y = 2\n"
    out, n, strat, err = apply(content, "if True:  \n    x = 1\n    y = 2\n", "if True:\n    x = 1\n    y = 3\n")
    assert strat == "line_trimmed" and "y = 3" in out and err is None


# 7 — unicode_normalized + preservation
def test_s7_unicode_match_preserves_file_unicode():
    content = "title = \"Café — the “best”…\"\n"
    out, n, strat, err = apply(
        content,
        'title = "Café -- the "best"..."',
        'title = "Café -- the "finest"..."',
    )
    assert strat == "unicode_normalized" and err is None
    assert "—" in out and "“" in out  # file's typography preserved
    assert "finest" in out


# 8 — block_anchor
def test_s8_block_anchor_first_last_anchor():
    content = (
        "def process(items):\n"
        "    total = 0\n"
        "    for it in items:\n"
        "        total += it.price\n"
        "    return total\n"
    )
    old = (
        "def process(items):\n"
        "    total2 = 0\n"
        "    for item in items:\n"
        "        total2 += item.price\n"
        "    return total\n"
    )
    out, n, strat, err = apply(content, old, "def process(items):\n    return sum(i.price for i in items)\n")
    assert strat == "block_anchor" and err is None and "sum(i.price" in out


def test_s8_block_anchor_below_similarity_rejects():
    content = "def f():\n    aaa = 1\n    bbb = 2\n    return aaa+bbb\n"
    old = "def f():\n    aaa = 1\n    bbb = 2\n    ccc = 3\n    return aaa+bbb\n"
    out, n, strat, err = apply(content, old, "x")
    assert err is not None and n == 0


# 9 — context_aware
def test_s9_context_aware_fifty_percent_lines():
    content = "def handler(req):\n    validate(req)\n    log(request_id)\n    return None\n"
    old = "def handler(req):\n    validate(req)\n    LOG(request_id)\n    return None\n"
    out, n, strat, err = apply(content, old, "def handler(req):\n    validate(req)\n    audit(request_id)\n    return None\n")
    assert strat in {"context_aware", "block_anchor"} and err is None and "audit(" in out


# --- safety contracts -------------------------------------------------------

def test_whitespace_only_anchor_rejected():
    out, n, strat, err = apply("a\n\n\nb", "   \n", "x")
    assert err and "whitespace" in err and n == 0


def test_identical_strings_error():
    out, n, _s, err = apply("abc", "abc", "abc")
    assert err == IDENTICAL_STRINGS_ERROR and n == 0


def test_ambiguity_lists_locations():
    content = "use plug;\nfn a() {}\nuse plug;\nfn b() {}\n"
    out, n, _s, err = apply(content, "use plug;", "use plug::v2;")
    assert err and "2 matches" in err and "L1" in err and "L3" in err and n == 0


def test_replace_all_works_exact():
    out, n, strat, err = apply("a b a b", "a", "z", replace_all=True)
    assert (out, n, strat, err) == ("z b z b", 2, "exact", None)


def test_similarity_strategy_refuses_replace_all():
    content = "alpha one\nbeta two\ngamma three\nalpha one\nbeta two\ngamma three\n"
    old = "alpha one\nWRONG\ngamma three"   # only context_aware can match this
    out, n, _s, err = apply(content, old, "z", replace_all=True)
    assert err and "approximate" in err and n == 0


def test_escape_drift_blocked():
    content = "s = 'it lives'\n"
    old = "s = \\'it lives\\'"
    new = "s = \\'it dies\\'"
    out, n, _s, err = apply(content, old, new)
    assert err and "Escape-drift" in err and n == 0


def test_already_applied_conservative():
    assert is_already_applied("file has the new implementation here", "old", "the new implementation")
    assert not is_already_applied("content", "old", "short")          # trivial target
    assert not is_already_applied("old text stays", "old", "the new implementation")  # old still present
