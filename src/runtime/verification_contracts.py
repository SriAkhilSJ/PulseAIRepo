"""Typed Verification Contracts and Enforcement Engine.

Implements Decision C of CrusorAI 2.0 Architecture:
1. Structured check definitions (syntax, unit tests, integration, browser, health, diagnostics).
2. Runtime-governed execution with bounded timeouts.
3. Mandatory checks block completion; optional diagnostics record telemetry without failing verified tasks.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal
from typing_extensions import TypedDict


CheckKind = Literal[
    "unit_tests",
    "integration_tests",
    "browser_tests",
    "server_health",
    "syntax_check",
    "diagnostics",
]


class CheckSpec(TypedDict, total=False):
    id: str
    kind: CheckKind
    required: bool
    timeout_seconds: int
    command: str
    target_path: str


class CheckResult(TypedDict):
    id: str
    kind: CheckKind
    required: bool
    passed: bool
    exit_code: int
    output: str
    duration_s: float
    error: str | None


class ContractExecutionReport(TypedDict):
    passed: bool
    mandatory_passed: bool
    results: list[CheckResult]
    diagnostics: list[dict[str, Any]]


class VerificationContractEngine:
    """Executes structured checks deterministically without relying on model-composed shell strings."""

    def __init__(self, workspace: str | Path, checks: list[CheckSpec] | None = None) -> None:
        self.workspace = Path(workspace).resolve()
        self.checks: list[CheckSpec] = checks or []

    def add_check(self, spec: CheckSpec) -> None:
        self.checks.append(spec)

    def execute_all(self) -> ContractExecutionReport:
        results: list[CheckResult] = []
        diagnostics: list[dict[str, Any]] = []
        mandatory_passed = True

        for check in self.checks:
            cid = check.get("id", "unnamed")
            kind = check.get("kind", "unit_tests")
            required = check.get("required", True)
            timeout = check.get("timeout_seconds", 60)
            command = check.get("command", "")

            t0 = time.time()
            passed = False
            exit_code = -1
            output = ""
            err_msg: str | None = None

            try:
                # Runtime drives command safely from workspace root
                proc = subprocess.run(
                    command,
                    shell=True,
                    cwd=str(self.workspace),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                exit_code = proc.returncode
                output = (proc.stdout + "\n" + proc.stderr).strip()
                passed = exit_code == 0
            except subprocess.TimeoutExpired:
                exit_code = 124
                err_msg = f"Check timed out after {timeout}s"
            except Exception as exc:
                exit_code = 1
                err_msg = f"Execution exception: {type(exc).__name__}: {exc}"

            duration = round(time.time() - t0, 3)
            result: CheckResult = {
                "id": cid,
                "kind": kind,
                "required": required,
                "passed": passed,
                "exit_code": exit_code,
                "output": output,
                "duration_s": duration,
                "error": err_msg,
            }
            results.append(result)

            if required and not passed:
                mandatory_passed = False

            if not required and not passed:
                diagnostics.append({
                    "check_id": cid,
                    "kind": kind,
                    "category": "telemetry",
                    "error": err_msg or f"Optional diagnostic check returned exit code {exit_code}",
                })

        return {
            "passed": mandatory_passed,
            "mandatory_passed": mandatory_passed,
            "results": results,
            "diagnostics": diagnostics,
        }
