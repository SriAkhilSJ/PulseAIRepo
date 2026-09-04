"""Pins for D31 (steal #7, §43): shadow checkpoints — transparent
pre-mutation workspace snapshots with per-project refs in ONE shared git
store, once-per-turn dedup, undo-the-undo restore, cross-project guard.

All pure: temp workspaces + temp stores, git plumbing only, no LLM.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tools import shadow_checkpoints as sc
from src.tools.file_tools import edit_file, write_file
from src.tools.shadow_checkpoints import ShadowCheckpoints

git = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git binary unavailable",
)

pytestmark = git

EDIT = edit_file.func
WRITE = write_file.func

ORIG = "def foo():\n    return 1\n"
BROKEN = "def foo():\n    return 999  # agent oops\n"


def _mgr(tmp_path, **kw) -> ShadowCheckpoints:
    return ShadowCheckpoints(enabled=True, base=tmp_path / "store-home", **kw)


def _ws(tmp_path) -> str:
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    (ws / "target.py").write_text(ORIG)
    return str(ws)


def _hook_env(monkeypatch, tmp_path):
    """Point the process singleton at a throwaway store and reset it."""
    monkeypatch.setenv("PULSEAI_CHECKPOINT_HOME", str(tmp_path / "hook-store"))
    monkeypatch.delenv("PULSEAI_CHECKPOINTS", raising=False)
    sc.reset_shadow_checkpoints_for_tests()


# ---------------------------------------------------------------------------
# hook-level: the real tools snapshot before mutating
# ---------------------------------------------------------------------------

def test_edit_file_snapshots_before_mutating(tmp_path, monkeypatch):
    _hook_env(monkeypatch, tmp_path)
    ws = _ws(tmp_path)
    out = EDIT(path="target.py", old_text="return 1", new_text="return 999",
               config={"configurable": {"workspace": ws}})
    assert out.startswith("✅")
    mgr = sc.get_shadow_checkpoints()
    cps = mgr.list_checkpoints(ws)
    assert len(cps) == 1
    assert "edit_file" in cps[0]["reason"]


def test_write_file_snapshot_preserves_old_content(tmp_path, monkeypatch):
    _hook_env(monkeypatch, tmp_path)
    ws = _ws(tmp_path)
    WRITE(path="target.py", content=BROKEN,
          config={"configurable": {"workspace": ws}})
    assert (Path(ws) / "target.py").read_text() == BROKEN
    mgr = sc.get_shadow_checkpoints()
    cps = mgr.list_checkpoints(ws)
    assert len(cps) == 1
    # And the pre-overwrite content is recoverable:
    res = mgr.restore(ws, cps[0]["hash"], "target.py")
    assert res["success"] is True
    assert (Path(ws) / "target.py").read_text() == ORIG


def test_once_per_turn_then_new_turn_snapshots_again(tmp_path, monkeypatch):
    _hook_env(monkeypatch, tmp_path)
    ws = _ws(tmp_path)
    cfg = {"configurable": {"workspace": ws}}
    EDIT(path="target.py", old_text="return 1", new_text="return 2", config=cfg)
    EDIT(path="target.py", old_text="return 2", new_text="return 3", config=cfg)
    mgr = sc.get_shadow_checkpoints()
    assert len(mgr.list_checkpoints(ws)) == 1  # dedup: second edit same turn
    sc.begin_agent_turn()
    EDIT(path="target.py", old_text="return 3", new_text="return 4", config=cfg)
    assert len(mgr.list_checkpoints(ws)) == 2


def test_kill_switch_makes_hooks_noop(tmp_path, monkeypatch):
    _hook_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PULSEAI_CHECKPOINTS", "off")
    sc.reset_shadow_checkpoints_for_tests()
    ws = _ws(tmp_path)
    EDIT(path="target.py", old_text="return 1", new_text="return 999",
         config={"configurable": {"workspace": ws}})
    assert not (tmp_path / "hook-store").exists()
    assert sc.get_shadow_checkpoints().list_checkpoints(ws) == []


# ---------------------------------------------------------------------------
# manager-level: snapshot / restore semantics
# ---------------------------------------------------------------------------

def test_restore_undo_the_undo_saves_unsnapshot_work(tmp_path):
    mgr = _mgr(tmp_path)
    ws = _ws(tmp_path)
    assert mgr.ensure_checkpoint(ws, "baseline") is True
    baseline = mgr.list_checkpoints(ws)[0]["hash"]

    # Real value of the pre-rollback snapshot: it pins work you NEVER
    # snapshotted before the restore overwrites it.
    (Path(ws) / "target.py").write_text(BROKEN)  # unsaved, never checkpointed

    res = mgr.restore(ws, baseline, "target.py")
    assert res["success"] is True
    assert (Path(ws) / "target.py").read_text() == ORIG

    # Undoing the undo: the pre-rollback snapshot holds the broken content.
    cps = mgr.list_checkpoints(ws)
    assert any("pre-rollback" in c["reason"] for c in cps)
    pre_rollback = next(c for c in cps if "pre-rollback" in c["reason"])
    res2 = mgr.restore(ws, pre_rollback["hash"], "target.py")
    assert res2["success"] is True
    assert (Path(ws) / "target.py").read_text() == BROKEN


def test_full_tree_restore_keeps_files_created_after_checkpoint(tmp_path):
    mgr = _mgr(tmp_path)
    ws = _ws(tmp_path)
    (Path(ws) / "b.py").write_text("B = 1\n")
    assert mgr.ensure_checkpoint(ws, "two good files") is True
    cp = mgr.list_checkpoints(ws)[0]["hash"]

    # Agent wreaks havoc: overwrite, delete, create-new.
    (Path(ws) / "target.py").write_text(BROKEN)
    (Path(ws) / "b.py").unlink()
    (Path(ws) / "c_new.py").write_text("C = 3\n")

    res = mgr.restore(ws, cp)
    assert res["success"] is True
    assert (Path(ws) / "target.py").read_text() == ORIG
    assert (Path(ws) / "b.py").read_text() == "B = 1\n"
    # Overwrite semantics (documented): restore never deletes newer files.
    assert (Path(ws) / "c_new.py").read_text() == "C = 3\n"


def test_no_git_pollution_in_workspace(tmp_path):
    mgr = _mgr(tmp_path)
    ws = _ws(tmp_path)
    mgr.ensure_checkpoint(ws, "baseline")
    assert not (Path(ws) / ".git").exists()
    # Store holds the project's ref instead (rev-parse, not dir listing —
    # lazy gc may pack loose refs, an upstream-documented behavior).
    store = tmp_path / "store-home" / "store"
    assert (store / "HEAD").exists()
    ok, tip, _ = sc._run_git(
        ["rev-parse", "--verify", f"refs/pulseai/{sc._project_hash(ws)}^{{commit}}"],
        store, ws,
    )
    assert ok and tip


def test_no_change_turn_creates_no_commit(tmp_path):
    mgr = _mgr(tmp_path)
    ws = _ws(tmp_path)
    assert mgr.ensure_checkpoint(ws, "baseline") is True
    mgr._done_this_turn.clear()  # simulate new turn, same content
    assert mgr.ensure_checkpoint(ws, "nothing changed") is False
    assert len(mgr.list_checkpoints(ws)) == 1


def test_excludes_keep_junk_out_of_snapshots(tmp_path):
    mgr = _mgr(tmp_path)
    ws = _ws(tmp_path)
    pyc = Path(ws) / "__pycache__"
    pyc.mkdir()
    (pyc / "junk.pyc").write_bytes(b"\x00\x01")
    (Path(ws) / ".git").mkdir()
    (Path(ws) / ".git" / "config").write_text("[core]")
    assert mgr.ensure_checkpoint(ws, "baseline") is True

    store = tmp_path / "store-home" / "store"
    ref = f"refs/pulseai/{sc._project_hash(ws)}"
    ok, tree, _ = sc._run_git(
        ["ls-tree", "-r", "--name-only", ref],
        store, ws,
    )
    assert ok
    names = tree.splitlines()
    assert "target.py" in names
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    assert not any(n.startswith(".git/") for n in names)


def test_history_ring_trim_keeps_latest_state_restorable(tmp_path):
    mgr = _mgr(tmp_path, max_snapshots=3)
    ws = _ws(tmp_path)
    target = Path(ws) / "target.py"
    for i in range(7):
        target.write_text(f"V = {i}\n")
        mgr._done_this_turn.clear()
        assert mgr.ensure_checkpoint(ws, f"v{i}") in (True, False)
    cps = mgr.list_checkpoints(ws)
    # Ring: collapse at 2*max ⇒ bounded history, latest always present.
    assert len(cps) <= 2 * 3
    res = mgr.restore(ws, cps[0]["hash"], "target.py")
    assert res["success"] is True
    assert target.read_text() == "V = 6\n"


def test_cross_project_restore_refused(tmp_path):
    mgr = _mgr(tmp_path)
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    for d in (ws_a, ws_b):
        d.mkdir()
        (d / "same_name.py").write_text(f"# content of {d.name}\n")
    mgr.ensure_checkpoint(str(ws_a), "a baseline")
    mgr.ensure_checkpoint(str(ws_b), "b baseline")
    hash_b = mgr.list_checkpoints(str(ws_b))[0]["hash"]
    # Guard hermes doesn't have: a shared object DB must not let project B's
    # snapshot land in project A.
    res = mgr.restore(str(ws_a), hash_b)
    assert res["success"] is False
    assert "does not belong" in res["error"]
    assert (ws_a / "same_name.py").read_text() == "# content of a\n"


def test_git_missing_is_graceful(tmp_path, monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda _x: None)
    mgr = _mgr(tmp_path)
    ws = _ws(tmp_path)
    assert mgr.ensure_checkpoint(ws, "no git here") is False
    assert mgr.list_checkpoints(ws) == []
    res = mgr.restore(ws, "abc123")
    assert res["success"] is False  # error dict, never an exception


def test_invalid_hash_and_escape_paths_rejected(tmp_path):
    mgr = _mgr(tmp_path)
    ws = _ws(tmp_path)
    mgr.ensure_checkpoint(ws, "baseline")
    assert mgr.restore(ws, "not-a-hash")["success"] is False
    cp = mgr.list_checkpoints(ws)[0]["hash"]
    assert mgr.restore(ws, cp, "../escape.txt")["success"] is False
    assert mgr.restore(ws, cp, "/abs/path.txt")["success"] is False


# ---------------------------------------------------------------------------
# honesty pins (owner field run: 30s/turn burned silently in the snapshot)
# ---------------------------------------------------------------------------

@git
def test_file_cap_skips_with_honest_log(tmp_path, monkeypatch, capsys):
    ws = tmp_path / "ws-cap"
    ws.mkdir()
    for i in range(3):
        (ws / f"f{i}.py").write_text("x = 1\n")
    monkeypatch.setenv("PULSEAI_SHADOW_MAX_FILES", "2")
    mgr = _mgr(tmp_path)

    assert mgr.ensure_checkpoint(str(ws), "cap test") is False
    out = capsys.readouterr().out
    assert "NO undo point taken" in out
    assert "PULSEAI_SHADOW_MAX_FILES" in out


@git
def test_add_giveup_is_named_not_silent(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    monkeypatch.delenv("PULSEAI_SHADOW_MAX_FILES", raising=False)
    real_run_git = sc._run_git

    def fake_run_git(args, *rest, **kwargs):
        if args and args[0] == "add":
            return False, "", "simulated add timeout"
        return real_run_git(args, *rest, **kwargs)

    monkeypatch.setattr(sc, "_run_git", fake_run_git)
    mgr = _mgr(tmp_path)

    assert mgr.ensure_checkpoint(str(ws), "timeout test") is False
    out = capsys.readouterr().out
    assert "gave up after" in out
    assert "PULSEAI_SHADOW_GIT_TIMEOUT_S" in out


@git
def test_success_logs_duration(tmp_path, capsys):
    ws = _ws(tmp_path)
    mgr = _mgr(tmp_path)

    assert mgr.ensure_checkpoint(str(ws), "timing test") is True
    out = capsys.readouterr().out
    assert "snapshot took" in out
