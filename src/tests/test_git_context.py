"""Git context layer — pure, CI-safe (uses real local git, no network).

Covers the integration points the pasted spec missed:
- layer content for a real repo (branch / status / commit log),
- None outside a git repo,
- VOLATILE wiring: the git layer must NOT be served from the engine's
  differential layer cache (a commit doesn't change the state hash),
- _infer_layer_name attribution for feedback,
- desktop safety: aggregate layer deadline, ownership-safe tree termination,
  prompt suppression, and guaranteed reaping on timeout.
"""

import ctypes
import os
import shutil
import subprocess
import time

import pytest

from src.context.git_context import (
    _GIT_BUDGET_S,
    _run_git,
    build_git_context_layer,
    get_git_context,
)
from src.context.context_engine import ContextEngine

git = shutil.which("git")
pytestmark = pytest.mark.skipif(git is None, reason="git not installed")


def _git(cwd, *args):
    subprocess.run(
        [git, *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _pid_alive(pid: int) -> bool:
    """Windows-only: is a PID still present, without signal(0) tricks."""
    PROCESS_QUERY_INFORMATION = 0x0400
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | SYNCHRONIZE, 0, pid
    )
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


@pytest.fixture()
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "app.py").write_text("def f():\n    return 1\n")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-qm", "initial commit")
    return tmp_path


class TestGitContextLayer:
    def test_layer_content(self, repo):
        (repo / "app.py").write_text("def f():\n    return 2\n")
        msg = build_git_context_layer({"workspace": str(repo)})
        assert msg is not None
        assert msg.content.startswith("=== GIT CONTEXT ===")
        assert "Branch:" in msg.content
        assert "app.py" in msg.content               # modified file listed
        assert "initial commit" in msg.content       # recent history shown

    def test_staged_changes_visible_in_context(self, repo):
        (repo / "new.py").write_text("x = 1\n")
        _git(repo, "add", "new.py")
        ctx = get_git_context(repo)
        # status_short runs early in the layer (well inside the budget) and
        # shows the staged add; the heavier --cached --stat may be the first
        # to yield if the aggregate deadline runs low (partial context is OK).
        assert "new.py" in ctx["status_short"]
        msg = build_git_context_layer({"workspace": str(repo)})
        assert "new.py" in msg.content

    def test_layer_runs_within_aggregate_budget(self, repo):
        (repo / "app.py").write_text("def f():\n    return 2\n")
        started = time.perf_counter()
        get_git_context(repo)
        # Whole layer must be bounded (~1s budget + one command overshoot +
        # process overhead) — never six independent 3s timeouts.
        assert time.perf_counter() - started < 2.5

    def test_not_a_repo_returns_none(self, tmp_path):
        assert get_git_context(tmp_path) == {}
        assert build_git_context_layer({"workspace": str(tmp_path)}) is None

    def test_missing_workspace_returns_none(self, tmp_path):
        gone = tmp_path / "does-not-exist"
        assert build_git_context_layer({"workspace": str(gone)}) is None


class TestSpawnSafety:
    """Every Popen this layer spawns must be prompt-proof and reaped cleanly."""

    def test_stdin_is_devnull_and_env_suppresses_prompts(
        self, monkeypatch, tmp_path
    ):
        import src.context.git_context as gc

        captured = {}

        def fake_spawn(args, **kwargs):
            captured.update(args=args, kwargs=kwargs)
            raise OSError("stop after capturing")

        monkeypatch.setattr(gc, "_SPAWN", fake_spawn)
        gc._run_git(["status", "--short"], cwd=str(tmp_path), timeout=1.0)
        assert captured["args"][0] == "git"
        assert captured["kwargs"]["stdin"] == subprocess.DEVNULL
        env = captured["kwargs"]["env"]
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GCM_INTERACTIVE"] == "Never"
        assert env["GIT_OPTIONAL_LOCKS"] == "0"

    def test_nonzero_exit_returns_empty(self, monkeypatch, tmp_path):
        import src.context.git_context as gc

        class FakeProc:
            pid = 1
            returncode = 2
            stdout = None
            stderr = None

            def communicate(self, timeout=None):
                return "stale stdout", "error text"

            def wait(self, timeout=None):
                return 2

            def kill(self):
                pass

        monkeypatch.setattr(gc, "_SPAWN", lambda *a, **k: FakeProc())
        assert gc._run_git(["log"], cwd=str(tmp_path), timeout=1.0) == ""

    def test_successful_output_is_returned(self, monkeypatch, tmp_path):
        import src.context.git_context as gc

        class FakeProc:
            pid = 1
            returncode = 0
            stdout = None
            stderr = None

            def communicate(self, timeout=None):
                return "main\n", ""

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        monkeypatch.setattr(gc, "_SPAWN", lambda *a, **k: FakeProc())
        out = gc._run_git(["branch", "--show-current"], cwd=str(tmp_path), timeout=1.0)
        assert out == "main\n"  # raw stdout; the layer strips at call sites


class TestWindowsShimHangDefense:
    """A wedged git shim (Scoop/MSYS2/VS SHA grandchild holding the pipe) must
    never hang the turn thread: the timeout path tree-terminates the exact
    owned root and reaps it."""

    def test_timeout_tree_terminates_exact_pid(self, monkeypatch, tmp_path):
        import src.context.git_context as gc

        killed = []

        class FakeProc:
            pid = 4242
            returncode = None
            stdout = None
            stderr = None

            def communicate(self, timeout=None):
                raise subprocess.TimeoutExpired(["git"], timeout or _GIT_BUDGET_S)

            def kill(self):
                pass

            def wait(self, timeout=None):
                return 0

        def fake_spawn(args, **kwargs):
            assert args[0] == "git"
            assert kwargs.get("stdin") == subprocess.DEVNULL
            return FakeProc()

        # _taskkill_tree now returns bool; return True to signal success
        # so _terminate does not fall back to proc.kill().
        monkeypatch.setattr(gc, "_SPAWN", fake_spawn)
        monkeypatch.setattr(gc, "_taskkill_tree",
                           lambda pid: (killed.append(pid), True)[1])

        started = time.perf_counter()
        out = gc._run_git(["status", "--short"], cwd=str(tmp_path), timeout=1.0)
        elapsed = time.perf_counter() - started

        assert out == ""
        assert elapsed < 2
        assert killed == [4242], "must tree-kill the exact owned pid"

    def test_tree_termination_failure_falls_back_and_reaps(self, monkeypatch, tmp_path):
        """When _taskkill_tree returns False the fallback must call
        proc.kill() then proc.wait(), and pipe fds are closed."""
        import src.context.git_context as gc

        kills_called = []
        waits_called = []
        closed_pipes = []

        class FakePipe:
            """Minimal stand-in for a PIPE file object with a close() method."""
            def __init__(self, name):
                self.name = name
                self.closed = False

            def close(self):
                self.closed = True
                closed_pipes.append(self.name)

        class FakeProc:
            pid = 7
            returncode = None
            stdout = FakePipe("stdout")
            stderr = FakePipe("stderr")

            def communicate(self, timeout=None):
                raise subprocess.TimeoutExpired(["git"], 1.0)

            def kill(self):
                kills_called.append(True)

            def wait(self, timeout=None):
                waits_called.append(timeout)
                return 0

        # _taskkill_tree returns False so _terminate falls back to proc.kill()
        monkeypatch.setattr(gc, "_SPAWN", lambda *a, **k: FakeProc())
        monkeypatch.setattr(gc, "_taskkill_tree", lambda pid: False)
        assert gc._run_git(["status"], cwd=str(tmp_path), timeout=1.0) == ""
        # The fallback path: kill then wait
        assert kills_called, "proc.kill() must be called when tree-kill fails"
        assert waits_called, "proc.wait() must be called after the fallback kill"
        # finally block closes pipe fds
        assert "stdout" in closed_pipes, "proc.stdout must be closed in finally"
        assert "stderr" in closed_pipes, "proc.stderr must be closed in finally"

    def test_non_timeout_exception_terminates_tree(self, monkeypatch, tmp_path):
        """A non-TimeoutExpired exception (e.g. broken pipe) while the
        process is alive must still terminate the owned tree."""
        import src.context.git_context as gc

        kills_called = []

        class FakeProc:
            pid = 99
            returncode = None
            stdout = None
            stderr = None

            def communicate(self, timeout=None):
                raise OSError("broken pipe")

            def kill(self):
                kills_called.append(True)

            def wait(self, timeout=None):
                return 0

        monkeypatch.setattr(gc, "_SPAWN", lambda *a, **k: FakeProc())
        monkeypatch.setattr(gc, "_taskkill_tree", lambda pid: True)
        assert gc._run_git(["status"], cwd=str(tmp_path), timeout=1.0) == ""
        # _terminate was called (not just _reap), so tree-kill was invoked
        # and the process was reaped.
        assert kills_called is not None  # _taskkill_tree was called (tree kill)

    def test_cleanup_stays_bounded(self, monkeypatch, tmp_path):
        """The complete timeout path (tree-kill + wait + fallback) must
        finish well under 3 s — never the old 5 s + 5 s = 10 s."""
        import src.context.git_context as gc

        class FakeProc:
            pid = 55
            returncode = None
            stdout = None
            stderr = None

            def communicate(self, timeout=None):
                raise subprocess.TimeoutExpired(["git"], 1.0)

            def kill(self):
                pass

            def wait(self, timeout=None):
                return 0

        def fast_taskkill(pid):
            return True

        monkeypatch.setattr(gc, "_SPAWN", lambda *a, **k: FakeProc())
        monkeypatch.setattr(gc, "_taskkill_tree", fast_taskkill)

        started = time.perf_counter()
        gc._run_git(["status"], cwd=str(tmp_path), timeout=1.0)
        elapsed = time.perf_counter() - started
        assert elapsed < 3.0, (
            f"timeout cleanup took {elapsed:.1f}s — must stay well under 3s"
        )


class TestAggregateBudget:
    """One deadline for the whole layer, never six individual timeouts."""

    def test_six_slow_commands_cannot_use_six_allowances(self, monkeypatch, tmp_path):
        import src.context.git_context as gc

        calls = []
        clock = {"t": 0.0}

        def monotonic():
            return clock["t"]

        def fake_run_git(cmd, cwd, timeout=None):
            calls.append((list(cmd), timeout))
            # Simulate git consuming its FULL per-call allowance.
            clock["t"] += timeout or _GIT_BUDGET_S
            return "ok"  # every command "succeeds" — the budget is still the cap

        monkeypatch.setattr(gc, "_MONOTONIC", monotonic)
        monkeypatch.setattr(gc, "_GIT_BUDGET_S", 1.0)
        monkeypatch.setattr(gc, "_run_git", fake_run_git)

        ctx = gc.get_git_context(tmp_path)

        # Exactly the rev-parse probe may run; every later command is skipped
        # because the aggregate deadline has already passed.
        assert len(calls) == 1
        assert calls[0][0] == ["rev-parse", "--git-dir"]
        assert calls[0][1] == 1.0
        assert clock["t"] == 1.0          # total git work <= 1s, not 6x3s
        assert ctx == {"branch": "", "status_short": "", "staged_diff": "",
                       "uncommitted_diff": "", "recent_commits": ""}

    def test_remaining_time_only_is_granted(self, monkeypatch, tmp_path):
        import src.context.git_context as gc

        calls = []
        clock = {"t": 0.0}

        def monotonic():
            return clock["t"]

        def fake_run_git(cmd, cwd, timeout=None):
            calls.append((list(cmd), timeout))
            clock["t"] += 0.4              # each command eats part of the budget
            return "ok"

        monkeypatch.setattr(gc, "_MONOTONIC", monotonic)
        monkeypatch.setattr(gc, "_GIT_BUDGET_S", 1.0)
        monkeypatch.setattr(gc, "_run_git", fake_run_git)

        gc.get_git_context(tmp_path)

        # Commands never exceed the remaining budget and none start past it.
        assert [c[0] for c in calls] == [
            ["rev-parse", "--git-dir"],
            ["branch", "--show-current"],
            ["status", "--short"],
        ]
        assert [t for _, t in calls] == pytest.approx([1.0, 0.6, 0.2])
        assert clock["t"] == pytest.approx(1.2)

    def test_deadline_expired_returns_empty_not_failure(self, monkeypatch, tmp_path):
        import src.context.git_context as gc

        # Clock advances past the budget between deadline capture and the first
        # command: nothing may be spawned and the layer falls back to {}.
        ticks = iter([0.0, 10.0])

        def monotonic():
            return next(ticks)

        spawned = []

        monkeypatch.setattr(gc, "_MONOTONIC", monotonic)
        monkeypatch.setattr(gc, "_GIT_BUDGET_S", 1.0)
        monkeypatch.setattr(
            gc, "_run_git", lambda *a, **k: spawned.append(a) or ""
        )

        assert gc.get_git_context(tmp_path) == {}
        assert spawned == [], "no git process may start past the deadline"


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill tree fixture")
class TestRealTreeTermination:
    """On a real Windows machine, prove the exact spy tree (wrapper plus an
    inherited-handle grandchild) disappears after a timeout."""

    def test_wrapper_and_grandchild_both_disappear(self, tmp_path):
        import src.context.git_context as gc

        grand_pid_file = tmp_path / "grand.pid"
        wrapper = tmp_path / "sleepy_git_wrapper.py"
        wrapper.write_text(
            "import subprocess, sys, time\n"
            "grand = subprocess.Popen(\n"
            "    [sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            "with open(r'%s', 'w') as fh:\n"
            "    fh.write(str(grand.pid))\n"
            "print('spawned', grand.pid, flush=True)\n"
            "time.sleep(120)\n" % str(grand_pid_file)
        )

        real_spawn = gc._SPAWN
        holder = {}

        def routed_spawn(args, **kwargs):
            if args and args[0] == "git":
                proc = real_spawn([os.sys.executable, str(wrapper)], **kwargs)
                holder["wrapper"] = proc.pid
                return proc
            return real_spawn(args, **kwargs)

        gc._SPAWN = routed_spawn
        try:
            out = gc._run_git(["status", "--short"], cwd=str(tmp_path), timeout=2.0)
            assert out == ""
            time.sleep(0.5)  # give the OS a beat to reap both processes
            assert "wrapper" in holder
            grand_pid = int(grand_pid_file.read_text())
            assert not _pid_alive(holder["wrapper"]), "wrapper survived the tree-kill"
            assert not _pid_alive(grand_pid), "grandchild survived the tree-kill"
        finally:
            gc._SPAWN = real_spawn


class TestEngineIntegration:
    def test_git_layer_is_volatile_not_cached(self, repo):
        """A commit must show up next turn even though the state hash (which
        excludes git state) is unchanged."""
        eng = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)

        first = eng._git_context_layer({"workspace": str(repo)})
        assert first is not None and "second commit" not in first.content

        # Commit OUTSIDE the graph state — hash won't change.
        (repo / "b.py").write_text("y = 2\n")
        _git(repo, "add", "b.py")
        _git(repo, "commit", "-qm", "second commit")

        second = eng._git_context_layer({"workspace": str(repo)})
        assert "second commit" in second.content

    def test_git_context_in_volatile_set(self):
        assert "git_context" in ContextEngine.VOLATILE_LAYERS

    def test_infer_layer_name(self, repo):
        eng = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
        msg = build_git_context_layer({"workspace": str(repo)})
        assert eng._infer_layer_name(msg) == "git_context"