"""Deterministic tests for the P1 bounded workspace scan.

The initial context build used three unbounded tree walks (repo map, chunk
index sync, convention scan) that could visit every node of a huge tree —
the desktop fork is 40k+ files. These tests pin BoundedScan's budgets so a
cold start is always bounded, deterministic, and able to report WHY it
truncated (``runtime.degraded`` receipt contract).

No-credit, no-agent-required: they exercise ``src.context.bounded_scan``
directly against synthetic trees.
"""

import time

import pytest

from src.context.bounded_scan import (
    BoundedScan,
    ScanLimits,
    ScanReport,
    SCAN_SKIP_DIRS,
    scan_files,
)


def _write_tree(root, spec, size_of=None):
    """Build a tree from {relpath: content}; ``!!``-prefixed dirs are realsize."""
    for rel, content in spec.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        elif content == "!!":
            p.write_bytes(b"\0" * (size_of or 1000))
        else:
            p.write_text(content)


def _sample_py(tmp_path, size_of):
    base = "def f():\n    pass\n"
    pad = "#" * max(0, size_of - len(base))
    return base + pad + "\n"


# ---------------------------------------------------------------------------
# COUNT BUDGET
# ---------------------------------------------------------------------------


def test_file_cap_stops_walk(tmp_path):
    _write_tree(tmp_path, {f"f{i:03d}.py": "x = 1\n" for i in range(50)})
    got = list(scan_files(tmp_path, limits=ScanLimits(max_files=10))[0])
    assert len(got) == 10


def test_file_cap_truncation_report(tmp_path):
    _write_tree(tmp_path, {f"f{i:03d}.py": "x = 1\n" for i in range(50)})
    it, report = scan_files(tmp_path, limits=ScanLimits(max_files=10))
    list(it)
    assert report.truncated is True
    assert report.reason == "files"
    assert report.files == 10
    assert report.summarize() and "truncated" in report.summarize()


# ---------------------------------------------------------------------------
# BYTES BUDGET
# ---------------------------------------------------------------------------


def test_byte_cap_stops_walk_before_file_read(tmp_path):
    # 12 files x 1KiB each; budget 3KiB -> only 3 files consumed.
    _write_tree(
        tmp_path, {f"f{i:03d}.py": "##" * 512 for i in range(12)}  # 1KiB each
    )
    got = list(scan_files(tmp_path, limits=ScanLimits(max_bytes=3 * 1024))[0])
    assert len(got) == 3
    assert sum(p.stat().st_size for p in got) <= 3 * 1024


def test_byte_cap_truncation_report(tmp_path):
    _write_tree(
        tmp_path, {f"f{i:03d}.py": "##" * 512 for i in range(12)}
    )
    it, report = scan_files(tmp_path, limits=ScanLimits(max_bytes=3 * 1024))
    list(it)
    assert report.truncated is True
    assert report.reason == "bytes"


# ---------------------------------------------------------------------------
# PER-FILE SIZE CAP
# ---------------------------------------------------------------------------


def test_oversize_files_skipped_not_counted(tmp_path):
    big = _sample_py(tmp_path, 2000)
    _write_tree(tmp_path, {
        "big.py": big,  # >1KiB cap
        "small_a.py": "x = 1\n",
        "small_b.py": "x = 2\n",
    })
    it, report = scan_files(
        tmp_path, limits=ScanLimits(max_file_bytes=1024, max_bytes=0)
    )
    got = list(it)
    assert [p.name for p in got] == ["small_a.py", "small_b.py"]
    assert report.skipped_oversize == 1
    assert report.truncated is False


# ---------------------------------------------------------------------------
# ELAPSED BUDGET
# ---------------------------------------------------------------------------


def test_elapsed_cap_truncates(tmp_path, monkeypatch):
    _write_tree(tmp_path, {f"f{i:03d}.py": "x = 1\n" for i in range(100)})
    real = time.perf_counter
    calls = {"n": 0}

    def slow_perf_counter():
        calls["n"] += 1
        return calls["n"] * 0.1  # 100ms per call -> cap 0.05s fires instantly

    monkeypatch.setattr(time, "perf_counter", slow_perf_counter)
    it, report = scan_files(tmp_path, limits=ScanLimits(max_elapsed=0.05))
    got = list(it)
    assert report.truncated is True
    assert report.reason == "elapsed"
    assert len(got) < 100


# ---------------------------------------------------------------------------
# SYMLINKS
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not hasattr(__import__("os"), "symlink"), reason="symlink unsupported"
)
def test_symlink_files_and_dirs_skipped(tmp_path):
    import os

    (tmp_path / "real.py").write_text("x = 1\n")
    (tmp_path / "target").write_text("y = 2\n")
    try:
        os.symlink(tmp_path / "target", tmp_path / "link_target.txt")
        os.symlink(tmp_path / "real.py", tmp_path / "link.py")
        os.symlink(tmp_path / "real.py", tmp_path / "sub")
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks on this filesystem")

    it, report = scan_files(
        tmp_path, limits=ScanLimits(skip_symlinks=True, max_bytes=0)
    )
    got = [p.name for p in it]
    assert sorted(got) == ["real.py", "target"]
    assert report.skipped_symlinks >= 2


# ---------------------------------------------------------------------------
# EXCLUSIONS + HIDDEN
# ---------------------------------------------------------------------------


def test_hidden_and_skip_dirs_pruned(tmp_path):
    _write_tree(tmp_path, {
        "keep_a.py": "x = 1\n",
        ".hidden.py": "x = 2\n",
        ".hdir/secret.py": "x = 3\n",
        "node_modules/dep/deep.js": "let a = 1;\n",
        "__pycache__/mod.pyc": b"",
    })
    it, report = scan_files(tmp_path)
    got = [p.relative_to(tmp_path).as_posix() for p in it]
    assert got == ["keep_a.py"]
    assert report.skipped_hidden_files >= 1
    assert report.skipped_dirs >= 1


def test_skip_dirs_override_defaults(tmp_path):
    _write_tree(tmp_path, {
        "a/keep_one.py": "x = 1\n",
        "generated/out.py": "x = 2\n",
    })
    it, report = scan_files(tmp_path, skip_dirs=set())
    got = sorted(p.relative_to(tmp_path).as_posix() for p in it)
    assert "generated/out.py" in got  # default skip list bypassed
    assert report.skipped_dirs == 0


def test_canonical_skip_set_is_superset(tmp_path):
    assert "node_modules" in SCAN_SKIP_DIRS
    assert "__pycache__" in SCAN_SKIP_DIRS


# ---------------------------------------------------------------------------
# EXTENSION FILTER
# ---------------------------------------------------------------------------


def test_extension_filter(tmp_path):
    _write_tree(tmp_path, {
        "a.py": "x = 1\n",
        "b.js": "let x = 1;\n",
        "c.txt": "hello\n",
    })
    got = [
        p.name
        for p in scan_files(tmp_path, extensions={".py"})[0]
    ]
    assert got == ["a.py"]


# ---------------------------------------------------------------------------
# STOP PREDICATE (turn cancellation polling)
# ---------------------------------------------------------------------------


def test_stop_predicate_stops_walk(tmp_path):
    _write_tree(tmp_path, {f"f{i:03d}.py": "x = 1\n" for i in range(50)})
    it, report = scan_files(
        tmp_path, should_stop=lambda: True, limits=ScanLimits(max_files=100)
    )
    got = list(it)
    assert report.truncated is True
    assert report.reason == "stopped"
    assert len(got) == 0


# ---------------------------------------------------------------------------
# PRIORITY ORDER (deterministic, shallow-first, larger-first)
# ---------------------------------------------------------------------------


def test_priority_order_shallow_first(tmp_path):
    _write_tree(tmp_path, {
        "deep/a.py": "x = 1\n",
        "middle/b.py": "x = 2\n",
        # shallow root-level file must come before the nested ones
        "root_thing.py": "x = 0\n",
    })
    got = [p.relative_to(tmp_path).as_posix() for p in scan_files(
        tmp_path, priority=True, limits=ScanLimits(max_files=100)
    )[0]]
    # deepest-first would return deep/a.py first; priority must NOT.
    assert got[0] == "root_thing.py"
    assert got.index("root_thing.py") < got.index("deep/a.py")


def test_priority_larger_file_first(tmp_path):
    big = _sample_py(tmp_path, 2000)
    _write_tree(tmp_path, {
        "small.py": "x = 1\n",
        "big.py": big + "\nx = 2\n",
    })
    got = [
        p.name
        for p in scan_files(tmp_path, priority=True, limits=ScanLimits(max_files=100))[0]
    ]
    assert got[0] == "big.py"


def test_priority_truncation_still_yields_best_prefix(tmp_path):
    small = "def g():\n    pass\n"
    _write_tree(tmp_path, {
        "a_aaa.py": small,
        "b_bbb.py": small,
        "c_ccc.py": small,
        "d_ddd.py": small,
        "e_eee.py": small,
        "f_fff.py": small,
    })
    it, report = scan_files(tmp_path, priority=True, limits=ScanLimits(max_files=3))
    got = [p.name for p in it]
    assert len(got) == 3
    assert report.truncated is True
    assert report.reason == "files"


# ---------------------------------------------------------------------------
# REPORT SHAPE
# ---------------------------------------------------------------------------


def test_report_fields_populated(tmp_path):
    _write_tree(tmp_path, {"a.py": "x = 1\n", "b.py": "y = 2\n"})
    it, report = scan_files(tmp_path, limits=ScanLimits(max_bytes=0))
    list(it)
    assert isinstance(report, ScanReport)
    assert report.files == 2
    assert report.visited >= 1
    assert report.bytes > 0
    assert report.elapsed > 0
    assert report.truncated is False
    assert report.reason is None


def test_scan_is_single_use(tmp_path):
    _write_tree(tmp_path, {"a.py": "x = 1\n"})
    it, _ = scan_files(tmp_path)
    assert len(list(it)) == 1
    assert len(list(it)) == 0  # second pass yields nothing


# ---------------------------------------------------------------------------
# BINARY / GENERATED / OUT-* EXCLUSIONS + GITIGNORE (P1 additions)
# ---------------------------------------------------------------------------


def test_binary_media_and_database_files_skipped(tmp_path):
    _write_tree(tmp_path, {
        "keep.py": "x = 1\n",
        "pic.png": b"\x89PNG\r\n",
        "video.mp4": b"\0" * 64,
        "db.sqlite": b"SQLite format 3\0",
        "archive.zip": b"PK\x03\x04",
    })
    it, report = scan_files(tmp_path)
    got = [p.name for p in it]
    assert got == ["keep.py"]
    assert report.skipped_binary >= 4


def test_generated_bundles_and_artifacts_skipped(tmp_path):
    _write_tree(tmp_path, {
        "keep.py": "x = 1\n",
        "mod.pyc": b"\0",
        "app.min.js": "x=1;",
        "style.min.css": "a{}",
        "bundle.js.map": "{}",
    })
    it, report = scan_files(tmp_path)
    got = [p.name for p in it]
    assert got == ["keep.py"]
    assert report.skipped_generated >= 4


def test_out_prefix_and_coverage_dirs_pruned(tmp_path):
    _write_tree(tmp_path, {
        "keep.py": "x = 1\n",
        "out-vscode-min/bundle.js": "x=1;",
        "out-build/bundle.js": "x=1;",
        "coverage/lcov.info": "SF:x",
    })
    got = [p.relative_to(tmp_path).as_posix() for p in scan_files(tmp_path)[0]]
    assert got == ["keep.py"]


def test_gitignore_patterns_respected(tmp_path):
    _write_tree(tmp_path, {
        "keep.py": "x = 1\n",
        "ignored/x.py": "x = 2\n",
        "trace.log": "log\n",
        "keep.log": "keep\n",
        "deep/nested/cache.bin": b"\0",
    })
    (tmp_path / ".gitignore").write_text(
        "ignored/\n*.log\n!keep.log\n**/cache.bin\n"
    )
    it, report = scan_files(tmp_path)
    got = sorted(p.relative_to(tmp_path).as_posix() for p in it)
    assert got == ["keep.log", "keep.py"]
    assert report.skipped_gitignore >= 1


def test_gitignore_read_goes_through_ledger(tmp_path):
    from src.context.bounded_scan import ContextBudget

    _write_tree(tmp_path, {"keep.py": "x = 1\n"})
    (tmp_path / ".gitignore").write_text("secret/\n*.log\n")
    budget = ContextBudget(max_elapsed=0, max_bytes=10**6)
    it, report = scan_files(
        tmp_path, limits=budget.to_limits(), budget=budget
    )
    assert list(it) == [tmp_path / "keep.py"]
    # The ignore content bytes were metered through the shared ledger.
    assert budget.read_bytes >= len("secret/\n*.log\n")
    assert budget.read_files == 1


def test_oversized_gitignore_skipped_safely(tmp_path):
    from src.context.bounded_scan import ContextBudget

    _write_tree(tmp_path, {"keep.py": "x = 1\n"})
    (tmp_path / ".gitignore").write_text("#" * 2000 + "\n")
    budget = ContextBudget(
        max_elapsed=0, max_file_bytes=100, max_bytes=10**6
    )
    it, report = scan_files(
        tmp_path, limits=budget.to_limits(), budget=budget
    )
    assert list(it) == [tmp_path / "keep.py"]  # oversized ignore skipped
    assert budget.read_bytes == 0  # nothing was read past the per-file cap


def test_disappearing_gitignore_skipped_safely(tmp_path):
    from src.context.bounded_scan import ContextBudget

    _write_tree(tmp_path, {"keep.py": "x = 1\n"})
    # A .gitignore that is not a regular file (or vanishes) is skipped safely.
    (tmp_path / ".gitignore").mkdir()
    budget = ContextBudget(max_elapsed=0)
    it, report = scan_files(
        tmp_path, limits=budget.to_limits(), budget=budget
    )
    assert list(it) == [tmp_path / "keep.py"]
    assert budget.read_bytes == 0


def test_considered_counts_every_file_examined(tmp_path):
    _write_tree(tmp_path, {
        "a.py": "x = 1\n",
        "b.py": "x = 2\n",
        "c.txt": "no\n",
        "d.png": b"\0",
    })
    it, report = scan_files(tmp_path, extensions={".py"})
    list(it)
    assert report.considered == 4
    assert report.files == 2
    assert report.skipped_total == 2


# ---------------------------------------------------------------------------
# CONTEXT BUDGET (shared deadline across the whole pipeline)
# ---------------------------------------------------------------------------


def test_context_budget_expires_and_stops_scan(tmp_path):
    from src.context.bounded_scan import ContextBudget

    _write_tree(tmp_path, {f"f{i:03d}.py": "x = 1\n" for i in range(50)})
    budget = ContextBudget(max_elapsed=0.0, max_files=100)
    budget.cancelled = True
    it, report = scan_files(
        tmp_path, should_stop=budget.should_stop, limits=budget.to_limits()
    )
    got = list(it)
    assert report.truncated is True
    assert report.reason == "stopped"
    assert len(got) == 0


def test_context_budget_emits_degraded_receipt_once(tmp_path):
    from src.context.bounded_scan import ContextBudget
    from src.dashboard.event_bus import event_bus

    _write_tree(tmp_path, {f"f{i:03d}.py": "x = 1\n" for i in range(50)})
    budget = ContextBudget(max_files=5, max_elapsed=0.0)
    it, report = scan_files(
        tmp_path, should_stop=budget.should_stop, limits=budget.to_limits()
    )
    list(it)
    assert report.truncated is True
    q = event_bus.subscribe(thread_id=None)
    first = budget.emit_degraded({
        "reason": "context scan bounded", "files_considered": report.considered,
    })
    second = budget.emit_degraded({"reason": "again"})
    assert first is True and second is False, "receipt must be emitted once per budget"
    evt = q.get_nowait()
    assert evt["type"] == "runtime.degraded"
    assert evt["payload"]["reason"] == "context scan bounded"
    event_bus.unsubscribe(q)