"""Tests for RepoMap — D14 ranking pins (ARCHITECTURE_REVIEW.md §37).

Measured baseline (scripts/d13_d14_rank_measure.py, OLD vs NEW):
- over-budget compression stripped symbol detail from EVERY file at roomier
  budgets and, when forced to truncate, cut from the END OF THE ALPHABET —
  the most important file (z_core_engine.py: highest in-degree, freshest,
  most symbols) was deleted while 12 a_junk_* files survived;
- the import graph was emitted alphabetically with no notion of hubs.

D14 design invariants pinned below:
- compress keeps what matters (importance = in-degree + recency + mass);
- graduated detail: when budget is merely tight — not desperate — symbol
  detail survives ONLY on above-median-importance files;
- the FULL map stays alphabetically ordered and byte-stable (prompt-cache
  prefix doctrine, §32): selection lives in the compress path only;
- the import graph names its hubs and stays deterministic;
- resolver failure degrades to the legacy module-level graph, never to zero.
"""

import os
import time

import pytest

from src.context.repo_map import RepoMap


def _junk_file(i: int) -> str:
    return f'"""Junk constants block {i}."""\n' + "\n".join(
        f"CONST_{i}_{j} = {j}" for j in range(40)
    ) + "\n"


CORE = (
    '"""The core orchestration engine everything depends on."""\n\n'
    "class Engine:\n    pass\n\n"
    "def run_pipeline():\n    return Engine()\n\n"
    "def plan_tasks():\n    return []\n"
)


@pytest.fixture
def ranked_ws(tmp_path):
    """12 stale junk files + 1 fresh hub imported by 4 fresh consumers."""
    stale = time.time() - 30 * 86400
    for i in range(12):
        p = tmp_path / f"a_junk_{i:02d}.py"
        p.write_text(_junk_file(i))
        os.utime(p, (stale, stale))
    (tmp_path / "z_core_engine.py").write_text(CORE)
    for c in range(4):
        (tmp_path / f"m_consumer_{c}.py").write_text(
            f"from z_core_engine import Engine\n\n\ndef consume_{c}():\n"
            f"    return Engine()\n"
        )
    return tmp_path


def _tree_part(text: str) -> str:
    return text.split("=== IMPORT GRAPH ===", 1)[0]


# ---------------------------------------------------------------------
# Compress ranking
# ---------------------------------------------------------------------


def test_d14_roomy_budget_keeps_detail_only_where_it_matters(ranked_ws):
    rm = RepoMap(ranked_ws)
    text = rm.get_map(max_tokens=620)
    assert "z_core_engine.py" in text
    # graduated detail: the hub keeps its symbols...
    assert "run_pipeline" in text or "plan_tasks" in text
    # ...while junk lines lost theirs (they had none to begin with — the pin
    # is that JUNK never kept ` -> ` detail while the budget was tight).
    tree = _tree_part(text)
    junk_lines = [ln for ln in tree.splitlines() if "a_junk_" in ln]
    assert junk_lines and all(" -> " not in ln for ln in junk_lines)
    # the tree portion really fits the stated budget
    assert len(tree) * 0.75 <= 620


def test_d14_tight_budget_drops_least_important_first(ranked_ws):
    rm = RepoMap(ranked_ws)
    text = rm.get_map(max_tokens=240)
    assert "z_core_engine.py" in text, "the hub may never be dropped"
    junk_shown = sum(1 for i in range(12) if f"a_junk_{i:02d}.py" in text)
    assert junk_shown < 12, f"no junk was dropped: {junk_shown}"
    # omission is explicit, never silent
    assert "least-important files omitted" in text or "truncated" in text
    # kept junk stays alphabetical (deterministic, navigable emission)
    shown = [f"a_junk_{i:02d}.py" for i in range(12) if f"a_junk_{i:02d}.py" in text]
    assert shown == sorted(shown)


def test_d14_compress_selection_matches_importance_order(ranked_ws):
    """The stale, never-imported, symbol-less junk files are ALWAYS dropped
    before any fresh consumer or the hub."""
    rm = RepoMap(ranked_ws)
    for budget in (180, 220, 260):
        text = rm.get_map(max_tokens=budget)
        assert "z_core_engine.py" in text
        consumers_shown = sum(
            1 for c in range(4) if f"m_consumer_{c}.py" in text
        )
        junk_shown = sum(1 for i in range(12) if f"a_junk_{i:02d}.py" in text)
        # no junk may outlive a consumer... (junk importance strictly lower)
        if junk_shown:
            assert consumers_shown == 4, (
                f"budget={budget}: junk survived ({junk_shown}) while a "
                f"consumer was dropped ({consumers_shown})"
            )


def test_d14_rebuild_is_deterministic(ranked_ws):
    a = RepoMap(ranked_ws).get_map(max_tokens=240)
    b = RepoMap(ranked_ws).get_map(max_tokens=240)
    assert a == b


# ---------------------------------------------------------------------
# Import graph centrality
# ---------------------------------------------------------------------


def test_d14_graph_names_hubs_and_stays_deterministic(tmp_path):
    (tmp_path / "libbase.py").write_text('"""Base library everyone uses."""\nX = 1\n')
    for leaf in ("a_leaf.py", "b_leaf.py", "c_leaf.py"):
        (tmp_path / leaf).write_text("import libbase\n\n\nleaf = 1\n")
    text = RepoMap(tmp_path).get_map(max_tokens=100_000)
    assert "=== IMPORT GRAPH ===" in text
    assert "Most depended-upon: libbase.py (3)" in text
    assert "a_leaf.py -> libbase.py" in text
    again = RepoMap(tmp_path).get_map(max_tokens=100_000)
    assert text == again


def test_d14_resolver_failure_falls_back_to_legacy_graph(tmp_path, monkeypatch):
    (tmp_path / "libbase.py").write_text("X = 1\n")
    (tmp_path / "a_leaf.py").write_text("import libbase\n")
    rm = RepoMap(tmp_path)
    monkeypatch.setattr(RepoMap, "_resolved_edges", lambda self, files: {})
    text = rm.get_map(max_tokens=100_000)
    assert "=== IMPORT GRAPH ===" in text
    assert "a_leaf.py -> libbase" in text  # legacy module-level style


def test_d14_no_python_files_no_graph_no_crash(tmp_path):
    (tmp_path / "README.md").write_text("# hello\n")
    (tmp_path / "data.json").write_text("{}\n")
    text = RepoMap(tmp_path).get_map(max_tokens=100_000)
    assert "README.md" in text
    assert "=== IMPORT GRAPH ===" not in text


# ---------------------------------------------------------------------
# Full-map stability doctrine (§32 prompt-cache prefix)
# ---------------------------------------------------------------------


def test_d14_full_map_stays_alphabetical_and_byte_stable(ranked_ws):
    rm = RepoMap(ranked_ws)
    first = rm.get_map(max_tokens=100_000)
    tree_lines = [ln.strip() for ln in _tree_part(first).splitlines()
                  if ln.startswith("  ") and ln.strip().endswith(")") or
                  ln.startswith("  ") and " -> " in ln]
    names = [ln.split(" (")[0].strip() for ln in tree_lines]
    assert names == sorted(names), "full map must stay alphabetical"
    # cached repeated call is the same string (no rebuild churn)
    assert rm.get_map(max_tokens=100_000) is first
