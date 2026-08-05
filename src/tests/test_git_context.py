"""Git context layer — pure, CI-safe (uses real local git, no network).

Covers the integration points the pasted spec missed:
- layer content for a real repo (branch / status / commit log),
- None outside a git repo,
- VOLATILE wiring: the git layer must NOT be served from the engine's
  differential layer cache (a commit doesn't change the state hash),
- _infer_layer_name attribution for feedback.
"""

import shutil
import subprocess

import pytest

from src.context.git_context import build_git_context_layer, get_git_context
from src.context.context_engine import ContextEngine

git = shutil.which("git")
pytestmark = pytest.mark.skipif(git is None, reason="git not installed")


def _git(cwd, *args):
    subprocess.run(
        [git, *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


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
        # Dirty the tree so status/diffstat have something to report.
        (repo / "app.py").write_text("def f():\n    return 2\n")
        msg = build_git_context_layer({"workspace": str(repo)})
        assert msg is not None
        assert msg.content.startswith("=== GIT CONTEXT ===")
        assert "Branch:" in msg.content
        assert "app.py" in msg.content               # modified file listed
        assert "initial commit" in msg.content       # recent history shown

    def test_staged_section_appears_after_add(self, repo):
        (repo / "new.py").write_text("x = 1\n")
        _git(repo, "add", "new.py")
        git_ctx = get_git_context(repo)
        assert "new.py" in git_ctx["staged_diff"]

    def test_not_a_repo_returns_none(self, tmp_path):
        assert get_git_context(tmp_path) == {}
        assert build_git_context_layer({"workspace": str(tmp_path)}) is None

    def test_missing_workspace_returns_none(self, tmp_path):
        gone = tmp_path / "does-not-exist"
        assert build_git_context_layer({"workspace": str(gone)}) is None


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
