"""The consent rule itself: git can restore it -> go, git can't -> ask.

Every assertion here is about *which paths* need a human, never about which tool was
used — that asymmetry (`.env` blocked for `write_file` only on overwrite, `copy_file`
not consulted at all) is the hole this policy closes.

Uses a real `git init` repo rather than a fake matcher: the rule delegates to
`git check-ignore`, so a fixture that hand-rolled `.gitignore` parsing would test the
fixture instead of the guard.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.context.safety_guard import SafetyGuard

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is the rule's oracle")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,  # never hand a child our stdin (bridge rule)
    )


@pytest.fixture
def repo(tmp_path):
    """A committed repo whose .gitignore declares `.env`, `out/` and `*.pem`."""
    root = tmp_path / "proj"
    root.mkdir()
    assert _git(root, "init", "-q", "--initial-branch=main").returncode == 0
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text(".env\nout/\n*.pem\n", encoding="utf-8", newline="\n")
    (root / "app.tsx").write_text("old\n", encoding="utf-8", newline="\n")
    assert _git(root, "add", "-A").returncode == 0
    assert _git(root, "commit", "-qm", "init").returncode == 0
    return root


# --- the freedom half: tracked means recoverable means no prompt -----------------


def test_overwriting_a_tracked_file_needs_no_consent(repo):
    """The D9 deadlock, deleted: no `AUTO_APPROVE_WRITES` flag, no nag, no batch loss."""
    ok, warning = SafetyGuard(str(repo)).check_tool_call(
        "write_file", {"path": "app.tsx", "content": "new"}
    )
    assert ok is True, "a tracked file is git-restorable, so prompting buys nothing"
    assert "overwrite" not in warning.lower()


@pytest.mark.parametrize("tool,path", [
    ("write_file", "app.tsx"),
    ("edit_file", "app.tsx"),
    ("copy_file", "app.tsx"),
])
def test_tool_choice_does_not_change_the_verdict_for_tracked_paths(repo, tool, path):
    guard = SafetyGuard(str(repo))
    args = {"src": path, "dst": "copy.txt"} if tool == "copy_file" else {"path": path}
    assert guard.check_tool_call(tool, args)[0] is True


# --- the consent half: git-ignored means nothing will give it back ---------------


def test_git_ignored_path_asks_even_though_no_secret_name_matches(repo, tmp_path):
    """`out/gen.js` is on nobody's basename list. git's own rules are what protect it."""
    ok, warning = SafetyGuard(str(repo)).check_tool_call(
        "write_file", {"path": "out/gen.js", "content": "x"}
    )
    assert ok is False
    assert "git-ignored" in warning


@pytest.mark.parametrize("tool", ["write_file", "edit_file"])
def test_the_same_ignored_path_asks_under_either_tool(repo, tool):
    guard = SafetyGuard(str(repo))
    args = {"path": "out/gen.js"} if tool == "write_file" else {"path": "out/gen.js", "edits": []}
    assert guard.check_tool_call(tool, args)[0] is False, f"{tool} found a way past the rule"


def test_creating_a_fresh_dotenv_asks(repo):
    """The exact hole from the live round: no `exists()` gate in front of the check."""
    assert not (repo / ".env").exists()
    ok, warning = SafetyGuard(str(repo)).check_tool_call(
        "write_file", {"path": ".env", "content": "TOKEN=planted"}
    )
    assert ok is False
    assert "sensitive" in warning.lower()


def test_outside_the_repo_asks(repo, tmp_path):
    """No tracked copy exists anywhere, whatever the ignore rules say."""
    (tmp_path / "sibling.txt").write_text("x", encoding="utf-8")
    ok, _ = SafetyGuard(str(repo)).check_tool_call(
        "write_file", {"path": str(tmp_path / "sibling.txt"), "content": "y"}
    )
    assert ok is False


# --- copy_file is consent-checked on both sides, not neither ---------------------


def test_copy_out_of_a_secret_asks(repo):
    (repo / ".env").write_text("TOKEN=real\n", encoding="utf-8", newline="\n")
    ok, warning = SafetyGuard(str(repo)).check_tool_call(
        "copy_file", {"src": ".env", "dst": "notes.txt"}
    )
    assert ok is False, "copy_file reads; the read side needs consent too"
    assert "read from" in warning


def test_copy_into_an_ignored_tree_asks(repo):
    ok, warning = SafetyGuard(str(repo)).check_tool_call(
        "copy_file", {"src": "app.tsx", "dst": "out/app.js"}
    )
    assert ok is False
    assert "write to" in warning


def test_copy_between_recoverable_paths_is_free(repo):
    ok, _ = SafetyGuard(str(repo)).check_tool_call(
        "copy_file", {"src": "app.tsx", "dst": "app.bak.tsx"}
    )
    assert ok is True, "an untracked-but-not-ignored copy is committable, so it is free"


# --- precedence: the veto runs before git, and outranks autonomous mode ----------


def test_named_secrets_ask_even_under_autonomous_writes(repo, monkeypatch):
    monkeypatch.setenv("PULSEAI_AUTO_APPROVE_WRITES", "1")
    guard = SafetyGuard(str(repo))
    assert guard.check_tool_call("write_file", {"path": ".env", "content": "x"})[0] is False
    # ... while ordinary tracked writes stay allowed, as D11 requires.
    assert guard.check_tool_call("write_file", {"path": "app.tsx", "content": "x"})[0] is True


def test_autonomous_writes_keep_their_historical_freedom_for_ignored_paths(repo, monkeypatch):
    """Eval mode has no human to answer, so `out/` stays writable; the secrets veto
    above it does not relax. This is the compatibility contract for D11."""
    monkeypatch.setenv("PULSEAI_AUTO_APPROVE_WRITES", "1")
    assert SafetyGuard(str(repo)).check_tool_call(
        "write_file", {"path": "out/gen.js", "content": "x"}
    )[0] is True


def test_dotgit_is_not_ignored_by_git_yet_still_blocked(repo):
    """Proves the two checks are complements: `git check-ignore` answers "not
    ignored" for `.git/config`, so the veto has to catch it."""
    probe = _git(repo, "check-ignore", "-q", "--", ".git/config")
    assert probe.returncode == 1, "git considers .git/config not-ignored"
    ok, _ = SafetyGuard(str(repo)).check_tool_call(
        "write_file", {"path": ".git/config", "content": "[core]\n"}
    )
    assert ok is False


# --- when git cannot answer, nothing changes -------------------------------------


def test_no_repo_falls_back_to_the_previous_behaviour(tmp_path):
    """A host without a repo keeps the old verdict exactly: overwrite asks, because
    there is no oracle to say whether git could restore it."""
    (tmp_path / "keep.txt").write_text("old", encoding="utf-8")
    guard = SafetyGuard(str(tmp_path))
    ok, warning = guard.check_tool_call("write_file", {"path": "keep.txt", "content": "new"})
    assert ok is False and "overwrite" in warning.lower()


def test_kill_switch_restores_the_old_lenient_default(repo, monkeypatch):
    monkeypatch.setenv("PULSEAI_SAFETY_GITIGNORE", "0")
    ok, _ = SafetyGuard(str(repo)).check_tool_call(
        "write_file", {"path": "out/gen.js", "content": "x"}
    )
    assert ok is True, "PULSEAI_SAFETY_GITIGNORE=0 must mean 'do not consult git'"
    # The secrets veto survives the kill switch — it is not the gitignore rule.
    assert SafetyGuard(str(repo)).check_tool_call(
        "write_file", {"path": ".env", "content": "x"}
    )[0] is False


# --- scope: this guard is about mutation, not about reading ----------------------


def test_read_only_calls_are_outside_this_rules_scope(repo):
    """Reads are `file_safety`'s job; making consent a write-side rule keeps the two
    layers from disagreeing about who owns what."""
    (repo / ".env").write_text("TOKEN=real\n", encoding="utf-8", newline="\n")
    assert SafetyGuard(str(repo)).check_tool_call("read_file", {"path": "out/gen.js"})[0] is True
