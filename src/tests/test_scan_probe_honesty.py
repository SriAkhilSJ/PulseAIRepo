"""By-design bounding probe must count CANDIDATES, not junk (owner report).

The desktop fork drew the amber "workspace exceeds scan budget" note on every
session because the probe walked the RAW tree -- counting the .git object
store and node_modules, trees the bounded scan itself never considers. The
probe now prunes the same directories the scanner skips: a vendored monorepo
whose REAL candidate set fits the budget no longer cries wolf.
"""
from __future__ import annotations


def _make_tree(tmp_path, real: int, junk: int) -> None:
    for i in range(real):
        (tmp_path / f"mod_{i}.py").write_text("x = 1\n")
    junk_dir = tmp_path / "node_modules" / "pkg"
    junk_dir.mkdir(parents=True)
    for i in range(junk):
        (junk_dir / f"dep_{i}.js").write_text("// dep\n")
    git_dir = tmp_path / ".git" / "objects"
    git_dir.mkdir(parents=True)
    for i in range(junk):
        (git_dir / f"obj{i:02d}").write_text("git")


def test_probe_ignores_vendor_and_git_trees(tmp_path):
    from src.context.context_engine import ContextEngine

    _make_tree(tmp_path, real=5, junk=500)
    # Old probe: 1005+ junk entries > cap 10 -> True (false alarm).
    # Honest probe: only 5 real candidates + a few dirs -> False.
    assert ContextEngine._workspace_exceeds_budget(str(tmp_path), 10) is False


def test_probe_still_fires_when_real_candidates_exceed(tmp_path):
    from src.context.context_engine import ContextEngine

    _make_tree(tmp_path, real=50, junk=0)
    assert ContextEngine._workspace_exceeds_budget(str(tmp_path), 10) is True


def test_probe_missing_workspace_is_false(tmp_path):
    from src.context.context_engine import ContextEngine

    assert ContextEngine._workspace_exceeds_budget(str(tmp_path / "nope"), 10) is False
