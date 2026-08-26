"""One-shot, provider-free Windows validation for the Attempt-11 delivery repair.

This script is intentionally fail-fast. It never retries a failed stage and never
overwrites an evidence directory. It runs only the checked-in deterministic
allowlist and emits a complete, hash-addressed evidence bundle on PASS or FAIL.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPAIR = "0370515cce811dd4d86d14379dd2729a94e640b1"
PRIOR_FAILED_EVIDENCE = "b90cb579eb72b363491f53e2a014fd073e795552"
BRANCH = "arena/01a03741-pulseairepo"
EXPECTED_ROOTS = {"d:/pulseaiagent/pulseairepo"}
EVIDENCE_REL = Path("bench-results/test5-11-product-delivery-repair-validation-windows-r3")
FOCUSED_TESTS = [
    "src/tests/test_attempt11_product_delivery_boundary.py",
    "src/tests/test_attempt11_completion_integrity.py",
    "src/tests/test_retry_proxy_stream_cleanup.py",
    "src/tests/test_run_bridge_turn.py",
    "src/tests/test_bridge_transport.py",
    "src/tests/test_bridge.py",
    "src/tests/test_lab_fixes.py",
    "src/tests/test_hermes_runtime_values.py",
    "src/tests/test_autonomous_runtime_contract.py",
    "src/tests/test_output_limit_recovery.py",
    "src/tests/test_model_budgets.py",
    "src/tests/test_iteration_budget.py",
    "src/tests/test_execution_phases.py",
    "src/tests/test_compaction.py",
]
COMPILE_MODULES = [
    "src/llm/factory.py",
    "src/tools/terminal_tools.py",
    "src/bridge/__main__.py",
    "src/graphs/chat_graph.py",
    "src/graphs/gates.py",
    "src/graphs/budget.py",
    "src/context/compaction.py",
    "src/context/context_engine.py",
    "src/context/workspace_integrity.py",
]
PROVIDER_ENV_KEYS = [
    "GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY",
    "OPENAI_API_KEY", "CUSTOM_API_KEY", "SARVAM_API_KEY", "OPENROUTER_API_KEY",
]
EVIDENCE_FILES = [
    "checkout.txt", "python-version.log", "monitor.log", "focused-tests.log",
    "fixture-detection.log", "protocol-tests.log", "protocol-generation.log",
    "compile-outcome.json", "git-diff-check.log", "validation_summary.json",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def ensure_repo_import_path(root: Path) -> None:
    """Make ``src`` importable when this file is launched from ``scripts``."""
    root_import_path = str(root)
    if root_import_path not in sys.path:
        sys.path.insert(0, root_import_path)


def run_logged(command: list[str], log_path: Path, env: dict[str, str]) -> int:
    with log_path.open("wb") as output:
        process = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, env=env)
    return int(process.returncode)


def parse_count(path: Path, pattern: str) -> int:
    text = path.read_bytes().decode("utf-8", errors="replace")
    match = re.search(pattern, text)
    return int(match.group(1)) if match else -1


def main() -> int:
    if os.name != "nt":
        print("FAIL: this validation must run on Windows", file=sys.stderr)
        return 2

    root_result = git("rev-parse", "--show-toplevel")
    root_text = root_result.stdout.strip()
    root_key = root_text.replace("\\", "/").rstrip("/").lower()
    if root_result.returncode or root_key not in EXPECTED_ROOTS:
        print(f"FAIL: wrong repository root: {root_text!r}", file=sys.stderr)
        return 2
    root = Path(root_text)
    os.chdir(root)
    # Running ``python scripts/<file>.py`` sets sys.path[0] to ``scripts``, not
    # the repository root. Pytest repairs its own import path, which let the
    # focused stage pass while the direct fixture import failed in R2. Make the
    # source package importable explicitly before any in-process source check.
    ensure_repo_import_path(root)

    branch = git("branch", "--show-current").stdout.strip()
    remote = git("remote", "get-url", "origin").stdout.strip()
    status_before = git("status", "--porcelain=v1").stdout.strip()
    head = git("rev-parse", "HEAD").stdout.strip()
    if branch != BRANCH:
        print(f"FAIL: wrong branch: {branch}", file=sys.stderr)
        return 2
    if "SriAkhilSJ/PulseAIRepo" not in remote:
        print(f"FAIL: wrong remote: {remote}", file=sys.stderr)
        return 2
    if status_before:
        print("FAIL: checkout is not clean; do not reset or clean it", file=sys.stderr)
        return 2
    if git("merge-base", "--is-ancestor", REPAIR, "HEAD").returncode:
        print(f"FAIL: repair {REPAIR} is not an ancestor of {head}", file=sys.stderr)
        return 2

    evidence = root / EVIDENCE_REL
    if evidence.exists():
        print(f"FAIL: evidence already exists: {evidence}", file=sys.stderr)
        return 2
    evidence.mkdir(parents=True)
    started = utc_now()
    monitor = evidence / "monitor.log"
    monitor_lock = threading.Lock()

    def note(message: str) -> None:
        with monitor_lock, monitor.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"{utc_now()} {message}\n")

    write_text(
        evidence / "checkout.txt",
        f"Repository root: {root_text}\nRemote: {remote}\nBranch: {branch}\n"
        f"HEAD (before validation): {head}\nStatus (before validation): clean\n",
    )
    python_version = subprocess.run(
        [sys.executable, "--version"], text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    write_text(evidence / "python-version.log", python_version.stdout)
    note("VALIDATION_START")

    child_env = dict(os.environ)
    for key in PROVIDER_ENV_KEYS:
        child_env.pop(key, None)

    first_failure: str | None = None
    focused_exit = fixture_exit = protocol_exit = generation_exit = compile_exit = diff_exit = None
    focused_collected = focused_passed = focused_failed = focused_skipped = 0
    protocol_collected = protocol_passed = 0
    fixture_findings: list[dict[str, str]] = []
    expected_fixture = [
        {"kind": "missing-local-import", "reference": "../vendor/three/three.module.min.js"},
        {"kind": "missing-local-import", "reference": "../vendor/three/controls/OrbitControls.js"},
        {"kind": "undefined-shader-constant", "reference": "MAX_STEPS_LOOP"},
    ]

    stop_heartbeat = threading.Event()
    def heartbeat() -> None:
        while not stop_heartbeat.wait(30):
            note("FOCUSED_HEARTBEAT")

    note("FOCUSED_START")
    worker = threading.Thread(target=heartbeat, name="validation-heartbeat", daemon=True)
    worker.start()
    focused_started = time.monotonic()
    focused_exit = run_logged(
        [sys.executable, "-m", "pytest", "-q", *FOCUSED_TESTS],
        evidence / "focused-tests.log", child_env,
    )
    stop_heartbeat.set()
    worker.join(timeout=5)
    note(f"FOCUSED_END exit={focused_exit} seconds={time.monotonic() - focused_started:.2f}")
    focused_collected = parse_count(evidence / "focused-tests.log", r"collected\s+(\d+)\s+items")
    focused_passed = parse_count(evidence / "focused-tests.log", r"(\d+)\s+passed")
    focused_skipped = max(0, parse_count(evidence / "focused-tests.log", r"(\d+)\s+skipped"))
    focused_failed = 0 if focused_exit == 0 else max(1, focused_collected - max(0, focused_passed) - focused_skipped)
    if focused_exit != 0 or focused_collected != 183 or focused_passed != 183:
        first_failure = "focused_tests"

    if first_failure is None:
        note("FIXTURE_START")
        try:
            from src.context.workspace_integrity import audit_workspace
            issues = audit_workspace(root / "bench-results/test5-11-desktop/workspace")
            fixture_findings = [
                {"kind": issue.kind, "path": issue.path, "reference": issue.reference,
                 "description": issue.describe()}
                for issue in issues
            ]
            missing = [
                item for item in expected_fixture
                if not any(
                    finding["kind"] == item["kind"]
                    and finding["reference"] == item["reference"]
                    for finding in fixture_findings
                )
            ]
            fixture_exit = 1 if missing or len(fixture_findings) != 3 else 0
            write_text(evidence / "fixture-detection.log", json.dumps({
                "finding_count": len(fixture_findings), "findings": fixture_findings,
                "expected": expected_fixture, "missing": missing,
            }, indent=2) + "\n")
        except Exception as exc:
            fixture_exit = 1
            write_text(evidence / "fixture-detection.log", f"FAIL: {type(exc).__name__}: {exc}\n")
        note(f"FIXTURE_END exit={fixture_exit}")
        if fixture_exit != 0:
            first_failure = "fixture_detection"
    else:
        write_text(evidence / "fixture-detection.log", f"SKIPPED after {first_failure}\n")

    if first_failure is None:
        note("PROTOCOL_START")
        protocol_exit = run_logged(
            [sys.executable, "-m", "pytest", "-q", "src/tests/test_bridge_protocol_v2.py"],
            evidence / "protocol-tests.log", child_env,
        )
        protocol_collected = parse_count(evidence / "protocol-tests.log", r"collected\s+(\d+)\s+items")
        protocol_passed = parse_count(evidence / "protocol-tests.log", r"(\d+)\s+passed")
        note(f"PROTOCOL_END exit={protocol_exit}")
        if protocol_exit != 0 or protocol_collected != 7 or protocol_passed != 7:
            first_failure = "protocol_tests"
    else:
        write_text(evidence / "protocol-tests.log", f"SKIPPED after {first_failure}\n")

    if first_failure is None:
        generation_exit = run_logged(
            [sys.executable, "scripts/generate_bridge_protocol.py", "--check"],
            evidence / "protocol-generation.log", child_env,
        )
        note(f"GENERATION_END exit={generation_exit}")
        if generation_exit != 0:
            first_failure = "protocol_generation"
    else:
        write_text(evidence / "protocol-generation.log", f"SKIPPED after {first_failure}\n")

    if first_failure is None:
        compile_exit = run_logged(
            [sys.executable, "-m", "compileall", "-q", *COMPILE_MODULES],
            evidence / "compile-command.log", child_env,
        )
        note(f"COMPILE_END exit={compile_exit}")
        if compile_exit != 0:
            first_failure = "compilation"
    compile_record = {"exit_code": compile_exit, "modules": COMPILE_MODULES}
    write_text(evidence / "compile-outcome.json", json.dumps(compile_record, indent=2) + "\n")
    # The command log is folded into the JSON evidence class; compileall is
    # silent on success. Preserve diagnostics in the JSON on failure.
    compile_command_log = evidence / "compile-command.log"
    if compile_command_log.exists():
        diagnostics = compile_command_log.read_bytes().decode("utf-8", errors="replace").strip()
        compile_record["diagnostics"] = diagnostics
        write_text(evidence / "compile-outcome.json", json.dumps(compile_record, indent=2) + "\n")
        compile_command_log.unlink()

    if first_failure is None:
        diff_result = git("diff", "--check")
        diff_exit = diff_result.returncode
        write_text(
            evidence / "git-diff-check.log",
            diff_result.stdout or "git diff --check: clean (exit 0)\n",
        )
        note(f"DIFF_END exit={diff_exit}")
        if diff_exit != 0:
            first_failure = "git_diff_check"
    else:
        write_text(evidence / "git-diff-check.log", f"SKIPPED after {first_failure}\n")

    ended = utc_now()
    passed = first_failure is None
    summary = {
        "utc_start": started, "utc_end": ended,
        "repository_root": str(root), "repository_remote": remote,
        "branch": branch, "validation_head": head, "repair_commit": REPAIR,
        "prior_failed_evidence_commit": PRIOR_FAILED_EVIDENCE,
        "repair_is_ancestor": True, "checkout_clean_before": True,
        "os": "Windows", "python_version": python_version.stdout.strip(),
        "focused_test_files": FOCUSED_TESTS,
        "focused_collected": focused_collected, "focused_passed": focused_passed,
        "focused_failed": focused_failed, "focused_skipped": focused_skipped,
        "focused_exit": focused_exit,
        "fixture_detection": {
            "exit_code": fixture_exit, "finding_count": len(fixture_findings),
            "expected": expected_fixture,
        },
        "protocol_collected": protocol_collected, "protocol_passed": protocol_passed,
        "protocol_exit": protocol_exit, "generation_exit": generation_exit,
        "compile_modules": COMPILE_MODULES, "compile_exit": compile_exit,
        "diff_exit": diff_exit, "provider_probes": 0, "provider_requests": 0,
        "first_failed_boundary": first_failure,
        "deterministic_verdict": "DETERMINISTIC_PASS" if passed else "DETERMINISTIC_FAIL",
        "note": "This is not live runtime/product PASS evidence.",
    }
    write_text(evidence / "validation_summary.json", json.dumps(summary, indent=2) + "\n")
    note(f"VALIDATION_END verdict={summary['deterministic_verdict']}")

    missing_files = [name for name in EVIDENCE_FILES if not (evidence / name).is_file()]
    if missing_files:
        print(f"FAIL: evidence files missing: {missing_files}", file=sys.stderr)
        return 2
    hash_lines = []
    for name in EVIDENCE_FILES:
        digest = hashlib.sha256((evidence / name).read_bytes()).hexdigest()
        hash_lines.append(f"{digest}  {name}")
    write_text(evidence / "sha256sums.txt", "\n".join(hash_lines) + "\n")

    print(json.dumps(summary, indent=2))
    print(f"Evidence: {EVIDENCE_REL}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
