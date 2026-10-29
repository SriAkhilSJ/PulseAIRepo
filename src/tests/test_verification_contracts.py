"""Unit tests for Typed Verification Contracts (Decision C)."""
from __future__ import annotations

import sys
import pytest
from pathlib import Path
from src.runtime.verification_contracts import VerificationContractEngine, CheckSpec


def test_mandatory_check_pass(tmp_path):
    engine = VerificationContractEngine(workspace=tmp_path)
    engine.add_check({
        "id": "python-syntax",
        "kind": "syntax_check",
        "required": True,
        "timeout_seconds": 10,
        "command": f'"{sys.executable}" -c "print(\'syntax ok\')"',
    })

    report = engine.execute_all()
    assert report["passed"] is True
    assert report["mandatory_passed"] is True
    assert len(report["results"]) == 1
    assert report["results"][0]["passed"] is True


def test_mandatory_check_failure_blocks_completion(tmp_path):
    engine = VerificationContractEngine(workspace=tmp_path)
    engine.add_check({
        "id": "broken-test",
        "kind": "unit_tests",
        "required": True,
        "timeout_seconds": 10,
        "command": f'"{sys.executable}" -c "import sys; sys.exit(1)"',
    })

    report = engine.execute_all()
    assert report["passed"] is False
    assert report["mandatory_passed"] is False
    assert report["results"][0]["passed"] is False


def test_optional_diagnostic_failure_does_not_block_mandatory_pass(tmp_path):
    engine = VerificationContractEngine(workspace=tmp_path)
    # Mandatory check passes
    engine.add_check({
        "id": "core-backend",
        "kind": "unit_tests",
        "required": True,
        "timeout_seconds": 10,
        "command": f'"{sys.executable}" -c "print(\'core ok\')"',
    })
    # Optional telemetry check fails (e.g. screenshot or nonessential linter)
    engine.add_check({
        "id": "optional-telemetry",
        "kind": "diagnostics",
        "required": False,
        "timeout_seconds": 10,
        "command": f'"{sys.executable}" -c "import sys; sys.exit(2)"',
    })

    report = engine.execute_all()
    # Overall passed should be True because mandatory passed!
    assert report["passed"] is True
    assert report["mandatory_passed"] is True
    # The failure must be recorded in diagnostics, not lost!
    assert len(report["diagnostics"]) == 1
    assert report["diagnostics"][0]["check_id"] == "optional-telemetry"
    assert report["diagnostics"][0]["category"] == "telemetry"
