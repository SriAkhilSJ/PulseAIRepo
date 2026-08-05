"""Tests for the upgraded edit_file — exact match, block-span fuzzy
fallback, atomic write (no torn files, perms preserved), diff emission.

All pure: temp workspaces, no LLM, no provider keys.
"""

import os
import queue
import stat

import pytest

from src.tools.file_tools import edit_file, _fuzzy_find_block
from src.dashboard.event_bus import event_bus

EDIT = edit_file.func  # call the underlying function, bypassing @tool wiring

BASE = 'def foo():\n    return 1\n'


def _ws(tmp_path, content=BASE):
    (tmp_path / "target.py").write_text(content)
    return str(tmp_path), "target.py"


def _call(ws, path, old, new):
    return EDIT(
        path=path,
        old_text=old,
        new_text=new,
        config={"configurable": {"workspace": ws}},
    )


# ---------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------


def test_exact_match_replaces_and_returns_diff(tmp_path):
    ws, f = _ws(tmp_path)
    out = _call(ws, f, "    return 1", "    return 2")
    assert "✅ Edited" in out
    assert "-    return 1" in out
    assert "+    return 2" in out
    assert (tmp_path / f).read_text() == "def foo():\n    return 2\n"


def test_text_not_found_leaves_file_untouched(tmp_path):
    ws, f = _ws(tmp_path)
    before = (tmp_path / f).read_bytes()
    mtime = os.path.getmtime(tmp_path / f)
    out = _call(ws, f, "def bar():", "def baz():")
    assert "not found" in out.lower()
    assert (tmp_path / f).read_bytes() == before
    assert os.path.getmtime(tmp_path / f) == mtime, "file was written on failure!"


def test_no_change_is_a_no_op(tmp_path):
    ws, f = _ws(tmp_path)
    mtime = os.path.getmtime(tmp_path / f)
    out = _call(ws, f, "    return 1", "    return 1")
    assert "No change" in out
    assert os.path.getmtime(tmp_path / f) == mtime


def test_missing_file_reports(tmp_path):
    out = _call(str(tmp_path), "ghost.py", "a", "b")
    assert "not found" in out.lower()


# ---------------------------------------------------------------------
# Fuzzy block replacement (the part the 2nd review's code got wrong:
# it replaced one LINE; a real fix must replace the whole BLOCK)
# ---------------------------------------------------------------------


def test_fuzzy_replaces_whole_block_with_whitespace_drift(tmp_path):
    ws, f = _ws(tmp_path, 'def foo():\n    return 1\n\n\ndef bar():\n    pass\n')
    # old_text with 2-space indent vs file's 4-space -> fuzzy match on strip
    new_block = "def foo():\n    return 2"
    out = _call(ws, f, "def foo():\n  return 1", new_block)
    assert "✅ Edited" in out and "fuzzy" in out
    content = (tmp_path / f).read_text()
    assert "return 2" in content
    assert "def bar():\n    pass" in content, "fuzzy span clobbered neighboring code"
    assert "return 1" not in content


def test_fuzzy_rejects_when_too_different(tmp_path):
    ws, f = _ws(tmp_path)
    out = _call(ws, f, "classTotallyDifferent:\n    x = 1\n    y = 2", "z = 3")
    assert "not found" in out.lower()


def test_fuzzy_find_block_locates_span():
    original = "a = 1\n\n    def foo():\n        return 9\nz = 26\n"
    old = "def foo():\n    return 9"  # stripped match inside indented code
    span = _fuzzy_find_block(original, old)
    assert span == (2, 4)


# ---------------------------------------------------------------------
# Atomic write guarantees
# ---------------------------------------------------------------------


def test_atomic_write_preserves_file_mode(tmp_path):
    ws, f = _ws(tmp_path)
    target = tmp_path / f
    os.chmod(target, 0o640)
    _call(ws, f, "return 1", "return 2")
    assert stat.S_IMODE(target.stat().st_mode) == 0o640, "file mode changed after edit"


def test_no_temp_files_left_behind(tmp_path):
    ws, f = _ws(tmp_path)
    _call(ws, f, "return 1", "return 2")
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert not leftovers, f"temp files leaked: {leftovers}"


# ---------------------------------------------------------------------
# Dashboard event (same flat shape write_file uses)
# ---------------------------------------------------------------------


def test_diff_show_event_emitted_for_dashboard(tmp_path):
    event_bus.clear()
    q = event_bus.subscribe()
    ws, f = _ws(tmp_path)
    _call(ws, f, "return 1", "return 2")

    seen = []
    try:
        while True:
            seen.append(q.get_nowait())
    except queue.Empty:
        pass
    finally:
        event_bus.unsubscribe(q)

    diffs = [e for e in seen if e["type"] == "diff.show"]
    assert diffs, f"no diff.show event; saw: {[e['type'] for e in seen]}"
    payload = diffs[-1]["payload"]
    assert payload["file"] == f
    assert any(line.startswith("+") and "return 2" in line for line in payload["lines"])
    assert all(isinstance(line, str) for line in payload["lines"])
