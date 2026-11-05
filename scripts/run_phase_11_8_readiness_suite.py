#!/usr/bin/env python3
"""
scripts/run_phase_11_8_readiness_suite.py - Phase 11.8 Adversarial Test Suite Runner.

Executes all 70 deterministic test scenarios in:
  src/tests/test_phase_11_8_production_readiness.py
Validates:
- Environment profile scaling (LOCAL_DEV, INTERNAL_TEST, DEMO, STAGING, SMALL_PROD, STANDARD_PROD, ENTERPRISE_PROD, REGULATED_PROD)
- Security readiness & prompt injection fences
- Configuration & secret scrubbing
- Supply chain & CycloneDX standard SBOM generation
- Deployment architecture & container inspection (USER non-root, HEALTHCHECK)
- CI/CD workflow test enforcement
- Database pooling & destructive migration detection
- Backup configured vs verified restoration drills
- Observability (JSON logging, /health probes, alerts)
- Reliability (timeouts, backoff, graceful shutdown, idempotency)
- Performance startup duration & capacity limits
- Infrastructure cost modeling & FinOps thresholds
- Release planning (10 stages) & automated rollback triggers
- Privacy compliance & copyleft license detection
- Authoritative readiness gate & separation of readiness from deploy authorization
- Real-world demonstrations Scenarios A through H
Saves machine-readable results to:
  bench-results/phase118_production_readiness/PHASE_11_8_ADVERSARIAL_RESULTS.json
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BENCH_DIR = REPO_ROOT / "bench-results" / "phase118_production_readiness"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
REPORT_JSON = BENCH_DIR / "PHASE_11_8_ADVERSARIAL_RESULTS.json"


def main() -> int:
    print("=" * 80)
    print("CRUSOR AI IDE -- PHASE 11.8 PRODUCTION READINESS INTELLIGENCE SUITE")
    print("Repository: SriAkhilSJ/PulseAIRepo | Branch: feat/prompt-cache-stabilization")
    print("Budget: INR 0.00 (Zero paid LLM API calls)")
    print("=" * 80)

    from src.tests.test_phase_11_8_production_readiness import TestPhase118ProductionReadiness

    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase118ProductionReadiness)
    total_tests = suite.countTestCases()

    passed = 0
    failed = 0
    errors = 0
    details = []

    t_all_start = time.time()

    for test in suite:
        test_name = test._testMethodName
        sys.stdout.write(f"Running scenario: {test_name} ... ")
        sys.stdout.flush()

        res = unittest.TestResult()
        t0 = time.time()
        test.run(res)
        duration = round(time.time() - t0, 4)

        if res.wasSuccessful():
            passed += 1
            print(f"[PASS] ({duration:.4f}s)")
            details.append({"name": test_name, "status": "PASS", "duration_seconds": duration})
        elif res.failures:
            failed += 1
            err_msg = res.failures[0][1]
            print(f"[FAIL] ({duration:.4f}s)")
            details.append({"name": test_name, "status": "FAIL", "duration_seconds": duration, "error": err_msg})
        elif res.errors:
            errors += 1
            err_msg = res.errors[0][1]
            print(f"[ERROR] ({duration:.4f}s)")
            details.append({"name": test_name, "status": "ERROR", "duration_seconds": duration, "error": err_msg})

    total_duration = round(time.time() - t_all_start, 4)
    all_passed = (passed == total_tests) and (failed == 0) and (errors == 0)
    verdict = "PRODUCTION READINESS VERIFIED" if all_passed else "PRODUCTION READINESS FAILED"

    print("=" * 80)
    print(f"Results: {passed}/{total_tests} PASSED in {total_duration:.3f}s")
    print(f"Verdict: {verdict}")

    report_payload = {
        "phase": "11.8",
        "phase_name": "Production Readiness Intelligence",
        "timestamp": time.time(),
        "total_scenarios": total_tests,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total_duration_seconds": total_duration,
        "paid_llm_cost_inr": 0.00,
        "verdict": verdict,
        "scenarios": details,
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    print(f"Saved: {REPORT_JSON}")
    print("=" * 80)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

