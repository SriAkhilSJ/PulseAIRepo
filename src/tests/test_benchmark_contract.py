"""Contract tests for the Pulse Reliability Benchmark v1 suite manifest.

Pure validation tests:

- No network access.
- No model calls.
- No fixture workspaces, no process spawning, no desktop execution.
- Execution is intentionally out of scope for PR 1A (evaluator arrives in PR 1B).

Run: python -m pytest src/tests/test_benchmark_contract.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from benchmarks.pulse_reliability_v1.contract import (
    BenchmarkResult,
    CheckType,
    HardFailure,
    Outcome,
    SuiteManifest,
    TaskManifest,
    load_suite,
)

# File layout: <repo>/src/tests/test_benchmark_contract.py -> repo root is parents[2]
BENCHMARK_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "pulse_reliability_v1"
MANIFEST_PATH = BENCHMARK_DIR / "manifest.json"

SUITE_ID = "pulse-reliability-v1"
SCHEMA_ID = "pulse-benchmark-manifest/v1"
EXPECTED_TASK_COUNT = 12


def _load() -> SuiteManifest:
    return load_suite(MANIFEST_PATH)


def test_manifest_exists_and_loads() -> None:
    assert MANIFEST_PATH.is_file()
    suite = _load()
    assert len(suite.tasks) == EXPECTED_TASK_COUNT


def test_suite_identity() -> None:
    suite = _load()
    assert suite.schema_id == SCHEMA_ID
    assert suite.suite_id == SUITE_ID
    assert suite.version == 1


def test_task_ids_are_strictly_ordered_pbr_range() -> None:
    suite = _load()
    expected = [f"PBR-{i:03d}" for i in range(1, EXPECTED_TASK_COUNT + 1)]
    assert [task.id for task in suite.tasks] == expected
    assert all(task.version == 1 for task in suite.tasks)


def test_every_task_has_metadata_and_evaluator_owned_checks() -> None:
    suite = _load()
    for task in suite.tasks:
        assert task.title.strip(), task.id
        assert task.prompt.strip(), task.id
        assert 0 < task.timeout_seconds <= 3600, task.id
        assert task.workspace.fixture, task.id
        assert len(task.checks) >= 1, task.id
        assert len(task.hard_failures) >= 1, task.id


def test_check_ids_are_unique_within_task_and_kebab_case() -> None:
    suite = _load()
    for task in suite.tasks:
        ids = [check.id for check in task.checks]
        assert len(ids) == len(set(ids)), f"duplicate check ids in {task.id}"
        for check_id in ids:
            assert check_id == check_id.lower() and "-" in check_id, f"bad check id {check_id!r} in {task.id}"


def test_check_types_are_known() -> None:
    known = set(get_args(CheckType))
    suite = _load()
    for task in suite.tasks:
        for check in task.checks:
            assert check.type in known, f"unknown check type {check.type!r} in {task.id}/{check.id}"


def test_hard_failures_are_known() -> None:
    known = set(get_args(HardFailure))
    suite = _load()
    for task in suite.tasks:
        for hard in task.hard_failures:
            assert hard in known, f"unknown hard failure {hard!r} in {task.id}"


def test_no_capability_is_both_allowed_and_forbidden() -> None:
    suite = _load()
    for task in suite.tasks:
        overlap = set(task.allowed_capabilities) & set(task.forbidden_capabilities)
        assert not overlap, f"{task.id} declares overlap {overlap}"


def test_duplicate_task_ids_are_rejected() -> None:
    suite = _load()
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["tasks"].append(payload["tasks"][0])
    with pytest.raises(ValidationError):
        SuiteManifest.model_validate(payload)
    assert suite  # original suite unchanged


def test_unsafe_fixture_path_is_rejected() -> None:
    suite = _load()
    base = suite.tasks[0].model_dump()
    for bad in ("../escape", "/abs/path", ""):
        mutated = {**base, "workspace": {**base["workspace"], "fixture": bad}}
        with pytest.raises(ValidationError):
            TaskManifest.model_validate(mutated)


def test_passed_outcome_cannot_carry_hard_failure() -> None:
    with pytest.raises(ValidationError):
        BenchmarkResult.model_validate(
            {
                "schema_id": "pulse-benchmark-result/v1",
                "run_id": "r1",
                "task_id": "PBR-001",
                "task_version": 1,
                "pulse_commit": "0" * 40,
                "outcome": Outcome.PASSED,
                "hard_failure": "workspace_escape",
            }
        )


def test_supported_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        BenchmarkResult.model_validate(
            {
                "schema_id": "pulse-benchmark-result/v1",
                "run_id": "r1",
                "task_id": "PBR-001",
                "task_version": 1,
                "pulse_commit": "0" * 40,
                "outcome": Outcome.PASSED,
                "claims": [{"claim": "x", "status": "supported", "evidence_ids": []}],
            }
        )


def test_manifest_is_deterministic_json() -> None:
    # Stable output: keys present once, tasks ordered by id (contract enforces).
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert list(payload.keys()) == ["schema_id", "suite_id", "version", "tasks"]
    assert [t["id"] for t in payload["tasks"]] == sorted(t["id"] for t in payload["tasks"])
