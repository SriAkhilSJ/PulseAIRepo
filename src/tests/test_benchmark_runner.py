"""Deterministic tests for the Pulse Reliability Benchmark runner wiring.

Pure: in-memory manifests + pytest tmp dirs only. No network, no model calls,
no process spawning, no desktop execution, no 20k builds (the large generated
fixture is covered by test_benchmark_fixtures.py).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest

from benchmarks.pulse_reliability_v1.contract import CheckType, load_suite
from benchmarks.pulse_reliability_v1.evaluator import _CHECK_HANDLERS
from benchmarks.pulse_reliability_v1.fixtures import (
    FixtureFile,
    FixtureManifest,
    FixtureSpec,
    load_fixture_manifest,
    resolve_files,
)
from benchmarks.pulse_reliability_v1.runner import (
    check,
    check_suite_and_fixtures,
    ensure_external_target,
    generate,
    grade,
    main,
)

SUITE_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "pulse_reliability_v1"
MANIFEST_PATH = SUITE_DIR / "manifest.json"
FIXTURES_PATH = SUITE_DIR / "fixtures.json"

_EXCLUDED_FROM_GENERATE_TESTS = {"PBR-004"}  # 20k build covered elsewhere

_ROOTS = {
    "PBR-001": "no-folder", "PBR-002": "exact-workspace", "PBR-003": "multi-root",
    "PBR-004": "large-20k", "PBR-005": "context-relevance", "PBR-006": "single-file-bug",
    "PBR-007": "multi-file-rename", "PBR-008": "syntax-gate", "PBR-009": "preexisting-failure",
    "PBR-010": "new-regression", "PBR-011": "process-tree-timeout", "PBR-012": "cancel-context",
}


def _write_full_placeholder_fixtures(tmp_path: Path) -> Path:
    """Temporary manifest with a trivial file for every task (no big builds)."""
    suite = _suite()
    payload = {
        "schema_id": "pulse-benchmark-fixtures/v1",
        "suite_id": "pulse-reliability-v1",
        "version": 1,
        "fixtures": [
            {"task_id": task.id, "root": _ROOTS[task.id], "description": "placeholder",
             "git": False, "line_endings": "lf",
             "files": [{"path": "note.txt", "content": "x\n"}], "generated": None}
            for task in suite.tasks
        ],
    }
    target = tmp_path / "fixtures-full.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target



def _suite():
    return load_suite(MANIFEST_PATH)


def _fixtures() -> FixtureManifest:
    return load_fixture_manifest(FIXTURES_PATH)


def _write_filtered_fixtures(tmp_path: Path) -> Path:
    """A fixtures manifest without the 20k PBR-004 entry (fast, still valid)."""
    payload = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    payload["fixtures"] = [
        f for f in payload["fixtures"] if f["task_id"] not in _EXCLUDED_FROM_GENERATE_TESTS
    ]
    target = tmp_path / "fixtures-lite.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# check gate
# ---------------------------------------------------------------------------

def test_check_passes_on_merged_manifests() -> None:
    assert check(MANIFEST_PATH, FIXTURES_PATH) == []


def test_check_require_complete_passes_with_full_set(tmp_path) -> None:
    full = _write_full_placeholder_fixtures(tmp_path)
    assert check(MANIFEST_PATH, full, require_complete=True) == []


def test_check_require_complete_reports_missing_fixtures(tmp_path) -> None:
    lite = _write_filtered_fixtures(tmp_path)
    issues = check(MANIFEST_PATH, lite, require_complete=True)
    missing = [i for i in issues if i.startswith("missing fixture for PBR-")]
    assert "missing fixture for PBR-004" in missing
    assert len(missing) >= 1


def test_check_unknown_fixture_id_reported(tmp_path) -> None:
    payload = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    payload["fixtures"].append({
        "task_id": "PBR-999", "root": "x", "description": "d", "git": False,
        "line_endings": "lf",
        "files": [{"path": "a.txt", "content": "x"}], "generated": None,
    })
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    issues = check(MANIFEST_PATH, path)
    assert any("PBR-999" in i for i in issues)


def test_check_fixture_root_mismatch_reported(tmp_path) -> None:
    payload = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    payload["fixtures"][1]["root"] = "wrong-root"  # PBR-002
    path = tmp_path / "bad-root.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    issues = check(MANIFEST_PATH, path)
    assert any("PBR-002" in i and "root" in i for i in issues)


def test_every_check_type_in_manifest_is_supported() -> None:
    known = set(get_args(CheckType))
    assert set(_CHECK_HANDLERS) == known


def test_all_twelve_fixtures_in_memory_pass_complete_gate() -> None:
    """Synthesize the full 12-fixture manifest; the complete gate must pass."""
    suite = _suite()
    specs = tuple(
        FixtureSpec(task_id=t.id, root=_ROOTS[t.id], description="placeholder",
                    files=(FixtureFile(path="note.txt", content="x\n"),))
        for t in suite.tasks
    )
    full = FixtureManifest(schema_id="pulse-benchmark-fixtures/v1",
                           suite_id="pulse-reliability-v1", version=1, fixtures=specs)
    assert check_suite_and_fixtures(suite, full, require_complete=True) == []


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def test_generate_builds_lite_fixtures_externally(tmp_path) -> None:
    lite = _write_filtered_fixtures(tmp_path)
    target = tmp_path / "extern" / "fixtures"
    target.mkdir(parents=True)
    lite_manifest = load_fixture_manifest(lite)
    builds = generate(MANIFEST_PATH, lite, target)
    assert len(builds) == len(lite_manifest.fixtures)
    assert {"exact-workspace", "multi-root", "single-file-bug"} <= {Path(b.root).name for b in builds}
    assert (target / "exact-workspace" / "workspace_proof.py").is_file()


def test_generate_deterministic_across_roots(tmp_path) -> None:
    lite = _write_filtered_fixtures(tmp_path)
    a = generate(MANIFEST_PATH, lite, tmp_path / "a")
    b = generate(MANIFEST_PATH, lite, tmp_path / "b")
    assert [x.hashes for x in a] == [x.hashes for x in b]


def test_full_fixture_set_would_include_large_20k() -> None:
    spec = next(f for f in _fixtures().fixtures if f.task_id == "PBR-004")
    assert len(resolve_files(spec)) == 20_001


def test_generate_refuses_relative_target(tmp_path) -> None:
    lite = _write_filtered_fixtures(tmp_path)
    with pytest.raises(ValueError):
        generate(MANIFEST_PATH, lite, "relative/dir")


def test_generate_refuses_repo_checkout(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "benchmarks").mkdir()
    monkeypatch.chdir(repo)
    with pytest.raises(ValueError):
        ensure_external_target(repo / "data")


def test_generate_refuses_current_working_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        ensure_external_target(tmp_path)


# ---------------------------------------------------------------------------
# grade
# ---------------------------------------------------------------------------

def _write_run(tmp_path: Path, task_id: str = "PBR-001", **kw) -> Path:
    payload = {
        "schema_id": "pulse-benchmark-run/v1",
        "run_id": f"runner-{task_id.lower()}-{id(tmp_path)}",
        "task_id": task_id,
        "task_version": 1,
        "pulse_commit": "0" * 40,
    }
    payload.update(kw)
    path = tmp_path / f"{task_id}.run.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_grade_writes_json_and_markdown(tmp_path) -> None:
    run = _write_run(tmp_path, "PBR-001", dom=[
        {"selector": "textarea.pulseai-composer-input", "enabled": False},
        {"selector": ".pulseai-composer-hint",
         "text": "Open a folder to start a Pulse session."},
    ])
    out = tmp_path / "out"
    result, markdown = grade(MANIFEST_PATH, run, out_dir=out)
    assert result.outcome.value == "passed"
    assert (out / f"{result.run_id}.json").is_file()
    assert (out / f"{result.run_id}.md").is_file()
    assert "PBR-001" in markdown and "Outcome" in markdown


def test_grade_is_deterministic(tmp_path) -> None:
    run = _write_run(tmp_path, "PBR-001", dom=[
        {"selector": "textarea.pulseai-composer-input", "enabled": False}])
    a, _ = grade(MANIFEST_PATH, run, out_dir=tmp_path / "o1")
    b, _ = grade(MANIFEST_PATH, run, out_dir=tmp_path / "o2")
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_grade_with_baseline_classifies_preexisting(tmp_path) -> None:
    cmd = {"argv": ["python", "-m", "pytest", "-q", "tests/test_calculator.py"], "exit_code": 1}
    run = _write_run(tmp_path, "PBR-009", commands=[cmd])
    base = _write_run(tmp_path, "PBR-009", commands=[cmd])
    result, _ = grade(MANIFEST_PATH, run, baseline_path=base)
    target = next(c for c in result.checks if c.check_id == "target-test")
    assert target.classification.value == "failed_preexisting"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_check_exit_codes(tmp_path) -> None:
    assert main(["check", "--suite", str(MANIFEST_PATH),
                 "--fixtures", str(FIXTURES_PATH)]) == 0
    full = _write_full_placeholder_fixtures(tmp_path)
    assert main(["check", "--suite", str(MANIFEST_PATH),
                 "--fixtures", str(full), "--require-complete"]) == 0
    lite = _write_filtered_fixtures(tmp_path)
    assert main(["check", "--suite", str(MANIFEST_PATH),
                 "--fixtures", str(lite), "--require-complete"]) == 1


def test_cli_generate_and_grade(tmp_path) -> None:
    lite = _write_filtered_fixtures(tmp_path)
    target = tmp_path / "gen"
    assert main(["generate", "--suite", str(MANIFEST_PATH),
                 "--fixtures", str(lite), "--target-root", str(target)]) == 0
    run = _write_run(tmp_path, "PBR-001", dom=[
        {"selector": "textarea.pulseai-composer-input", "enabled": False}])
    out = tmp_path / "res"
    assert main(["grade", "--suite", str(MANIFEST_PATH),
                 "--run", str(run), "--out-dir", str(out)]) == 0
    assert list(out.glob("*.json"))
