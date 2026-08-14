"""Pins for D32 (steal #8, §45): the file-state guard — one agent can
never silently overwrite another in-process agent's fresh work.

All pure: temp workspaces, real file tools, no LLM.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.tools import file_state
from src.tools.file_tools import read_file, write_file, edit_file

READ = read_file.func
WRITE = write_file.func
EDIT = edit_file.func

TARGET = "shared.py"
A = "agent-A-thread"
B = "agent-B-thread"


def _ws(tmp_path) -> str:
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    (ws / TARGET).write_text("X = 'original'\n")
    return str(ws)


def _cfg(ws: str, tid: str) -> dict:
    return {"configurable": {"workspace": ws, "thread_id": tid}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("PULSEAI_FILE_STATE_GUARD", raising=False)
    file_state.reset_for_tests()
    yield
    file_state.reset_for_tests()


def test_stale_clobber_refused_and_file_intact(tmp_path):
    ws = _ws(tmp_path)
    READ(path=TARGET, config=_cfg(ws, A))            # A learns the file
    WRITE(path=TARGET, content="X = 'B fresh'\n",    # B improves it
          config=_cfg(ws, B))
    out = WRITE(path=TARGET, content="X = 'A stale'\n",  # A blindly overwrites
                config=_cfg(ws, A))
    assert "Refusing to clobber" in out
    assert (Path(ws) / TARGET).read_text() == "X = 'B fresh'\n"


def test_reread_clears_staleness_and_retry_succeeds(tmp_path):
    ws = _ws(tmp_path)
    READ(path=TARGET, config=_cfg(ws, A))
    WRITE(path=TARGET, content="X = 'B fresh'\n", config=_cfg(ws, B))
    assert "Refusing" in WRITE(path=TARGET, content="X = 'a'\n",
                               config=_cfg(ws, A))
    READ(path=TARGET, config=_cfg(ws, A))            # A catches up
    out = WRITE(path=TARGET, content="X = 'A current'\n", config=_cfg(ws, A))
    assert out.startswith("File written")
    assert (Path(ws) / TARGET).read_text() == "X = 'A current'\n"


def test_self_write_chain_never_self_stales(tmp_path):
    ws = _ws(tmp_path)
    cfg = _cfg(ws, A)
    assert WRITE(path=TARGET, content="X = 1\n", config=cfg).startswith("File written")
    assert WRITE(path=TARGET, content="X = 2\n", config=cfg).startswith("File written")
    # A never "read" but only ever wrote: still fine (a writer knows its
    # own writes — pinned via note_write stamping).
    assert WRITE(path=TARGET, content="X = 3\n", config=cfg).startswith("File written")


def test_writer_stamp_does_not_leak_to_other_agent(tmp_path):
    ws = _ws(tmp_path)
    WRITE(path=TARGET, content="X = 'A'\n", config=_cfg(ws, A))
    # B must READ before it's allowed to write at all (blind-overwrite
    # guard); after that, B is current and its write lands:
    READ(path=TARGET, config=_cfg(ws, B))
    WRITE(path=TARGET, content="X = 'B'\n", config=_cfg(ws, B))
    # A's own-write stamp is older than B's write — A is stale and refused:
    assert "Refusing to clobber" in WRITE(path=TARGET, content="X = 'A2'\n",
                                        config=_cfg(ws, A))


def test_blind_overwrite_refused(tmp_path):
    """B creates a file; A (who never read it) must not blindly overwrite."""
    ws = _ws(tmp_path)
    target = Path(ws) / "b_made.py"
    WRITE(path="b_made.py", content="B = 1\n", config=_cfg(ws, B))
    assert target.read_text() == "B = 1\n"
    out = WRITE(path="b_made.py", content="A = 0\n", config=_cfg(ws, A))
    assert "Refusing to clobber" in out
    assert target.read_text() == "B = 1\n"


def test_kill_switch_restores_legacy_behavior(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    READ(path=TARGET, config=_cfg(ws, A))
    WRITE(path=TARGET, content="X = 'B'\n", config=_cfg(ws, B))
    monkeypatch.setenv("PULSEAI_FILE_STATE_GUARD", "off")
    out = WRITE(path=TARGET, content="X = 'A stale'\n", config=_cfg(ws, A))
    assert out.startswith("File written")  # pre-D32 behavior: last wins


def test_edit_file_notes_writes_and_needs_no_refusal(tmp_path):
    """edit_file is span-safe (reads fresh, replaces the matched span):
    it must keep working across agents — A's surgical edit PRESERVES B's
    changes outside the span, and both writes get stamped."""
    ws = _ws(tmp_path)
    Path(ws, TARGET).write_text("A_section = 1\nB_section = 2\n")
    EDIT(path=TARGET, old_text="A_section = 1", new_text="A_section = 10",
         config=_cfg(ws, A))
    out = EDIT(path=TARGET, old_text="B_section = 2", new_text="B_section = 20",
               config=_cfg(ws, B))
    assert out.startswith("✅"), out
    assert (Path(ws) / TARGET).read_text() == "A_section = 10\nB_section = 20\n"
    # and B's edit stamped B as latest writer:
    assert "Refusing" in WRITE(path=TARGET, content="nope\n", config=_cfg(ws, A))


def test_lock_path_mutual_exclusion():
    lock_key = "/tmp/d32-lock-test"
    active = {"now": 0, "max": 0}
    guard = threading.Lock()

    def worker():
        for _ in range(5):
            with file_state.lock_path(lock_key):
                with guard:
                    active["now"] += 1
                    active["max"] = max(active["max"], active["now"])
                time.sleep(0.001)
                with guard:
                    active["now"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert active["max"] == 1


def test_config_without_thread_id_falls_back_to_main(tmp_path):
    ws = _ws(tmp_path)
    out = READ(path=TARGET, config={"configurable": {"workspace": ws}})
    assert out == "X = 'original'\n"  # no crash; identity 'main'
    assert file_state.task_id_from_config({}) == "main"


def test_programmatic_api_independent_of_tools(tmp_path):
    ws = _ws(tmp_path)
    f = Path(ws) / TARGET
    file_state.record_read(A, f)
    file_state.note_write(B, f)
    assert file_state.check_stale(A, f) is not None
    assert file_state.check_stale(B, f) is None  # writer checks self
    file_state.record_read(A, f)
    assert file_state.check_stale(A, f) is None  # caught up
