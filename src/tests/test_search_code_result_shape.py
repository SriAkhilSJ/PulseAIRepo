"""search_code result-shape pins.

hermes tools/file_operations_search.py caps EACH match's content at 500
chars (:234/:241, SearchMatch(content=...[:500])). The field run on
7a7111b9 (2026-09-09) reproduced why: `search_code '*'` matched a line of
a ~1.9MB single-line minified bundle — the whole line rode the result and
the bridge dropped the 1,719,559-byte PulseAI frame, leaving the UI step
empty. The per-match cap is the hermes-verbatim fix.

All pure: temp workspace, no LLM, no provider keys.
"""

from src.tools.file_tools import search_code

SEARCH = search_code.func  # call the underlying function, bypassing @tool


def _call(ws, query, path="."):
    return SEARCH(
        query=query,
        path=path,
        config={"configurable": {"workspace": ws}},
    )


def test_search_code_match_line_capped_at_500_chars(tmp_path):
    # A minified-style single-line file well under the 2MB per-file filter,
    # whose one line is ~1.9MB. One match must not carry the whole line.
    big_line = "x" * 200 + "NEEDLE" + "y" * 1_900_000
    (tmp_path / "bundle.min.js").write_text(big_line)

    out = _call(str(tmp_path), "needle", path=".")

    assert "bundle.min.js:1:" in out
    for line in out.splitlines():
        assert len(line) <= len("bundle.min.js") + len(":1: ") + 500, (
            "match line exceeds the hermes 500-char content cap"
        )


def test_search_code_still_returns_short_matches_verbatim(tmp_path):
    (tmp_path / "app.py").write_text("def run_pulse():\n    return 42\n")

    out = _call(str(tmp_path), "run_pulse", path=".")

    assert "app.py:1: def run_pulse():" in out


def test_search_code_multiple_matches_each_capped(tmp_path):
    rows = ["NEEDLE" + "z" * 900 for _ in range(3)]
    (tmp_path / "rows.txt").write_text("\n".join(rows))

    out = _call(str(tmp_path), "needle", path=".")

    lines = out.splitlines()
    assert len(lines) == 3
    assert all(len(ln) <= 12 + 500 for ln in lines)
