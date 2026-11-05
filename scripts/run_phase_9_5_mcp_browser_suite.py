#!/usr/bin/env python3
"""
scripts/run_phase_9_5_mcp_browser_suite.py - Phase 9.5 Adversarial Test Runner & Artifact Generator.

Executes the 38 deterministic adversarial test cases covering all 8 Phase 9.5 security requirements:
1. Protocol Version Governance & Negotiation
2. Local MCP Server Isolation & ExecutionBroker
3. Remote MCP Security & SSRF Protection
4. MCP Authorization, OAuth 2.1 & Credential Isolation
5. Centralized Tool Authorization & Replay Defense
6. Untrusted MCP Output & Prompt Injection Defense
7. Browser Agent Isolation & SSRF
8. Secure File Download Quarantine & Upload Protection

Outputs:
  bench-results/phase95_mcp_browser_security/PHASE_9_5_ADVERSARIAL_RESULTS.json
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path

# Add PulseAIRepo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.tests.test_phase_9_5_mcp_browser_security import TestPhase95MCPBrowserSecurity


def main():
    print("=" * 80)
    print("CRUSOR AI IDE - PHASE 9.5 MCP ECOSYSTEM & BROWSER AGENT SECURITY SUITE")
    print("=" * 80)
    print("Repository: SriAkhilSJ/PulseAIRepo")
    print("Branch: feat/prompt-cache-stabilization")
    print("Target: 38 Deterministic Adversarial Scenarios across 8 Security Requirements")
    print("Paid API Calls: Prohibited (Budget: INR 0.00)")
    print("-" * 80)

    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase95MCPBrowserSecurity)
    all_tests = [test._testMethodName for test in suite if test is not None and hasattr(test, "_testMethodName")]
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    duration_s = time.time() - start_time

    # Categorize tests by requirement
    categories = {
        "R1_PROTOCOL_GOVERNANCE": {
            "title": "Protocol Version Governance & Negotiation",
            "passed": 0, "failed": 0, "errors": 0, "tests": []
        },
        "R2_LOCAL_MCP_ISOLATION": {
            "title": "Local MCP Server Isolation & Process Control",
            "passed": 0, "failed": 0, "errors": 0, "tests": []
        },
        "R3_REMOTE_MCP_SSRF": {
            "title": "Remote MCP Security & SSRF Protection",
            "passed": 0, "failed": 0, "errors": 0, "tests": []
        },
        "R4_OAUTH21_CREDENTIALS": {
            "title": "OAuth 2.1, PKCE & Credential Isolation",
            "passed": 0, "failed": 0, "errors": 0, "tests": []
        },
        "R5_TOOL_AUTHORIZATION": {
            "title": "Centralized Tool Authorization & Replay Resistance",
            "passed": 0, "failed": 0, "errors": 0, "tests": []
        },
        "R6_PROMPT_INJECTION": {
            "title": "Untrusted Output & Prompt Injection Defense",
            "passed": 0, "failed": 0, "errors": 0, "tests": []
        },
        "R7_BROWSER_ISOLATION": {
            "title": "Browser Agent Isolation & SSRF Protection",
            "passed": 0, "failed": 0, "errors": 0, "tests": []
        },
        "R8_FILE_TRANSFER": {
            "title": "Secure File Download & Upload Protection",
            "passed": 0, "failed": 0, "errors": 0, "tests": []
        },
    }

    def assign_category(test_id: str) -> str:
        tid = test_id.lower()
        if "test_01" in tid or "test_02" in tid or "test_03" in tid or "test_04" in tid or "test_05" in tid or "test_06" in tid:
            return "R1_PROTOCOL_GOVERNANCE"
        elif "test_07" in tid or "test_08" in tid or "test_09" in tid or "test_10" in tid or "test_11" in tid:
            return "R2_LOCAL_MCP_ISOLATION"
        elif "test_12" in tid or "test_13" in tid or "test_14" in tid or "test_15" in tid or "test_16" in tid or "test_17" in tid:
            return "R3_REMOTE_MCP_SSRF"
        elif "test_18" in tid or "test_19" in tid or "test_20" in tid or "test_21" in tid or "test_22" in tid:
            return "R4_OAUTH21_CREDENTIALS"
        elif "test_23" in tid or "test_24" in tid or "test_25" in tid or "test_26" in tid or "test_27" in tid or "test_28" in tid:
            return "R5_TOOL_AUTHORIZATION"
        elif "test_29" in tid or "test_30" in tid or "test_31" in tid or "test_32" in tid:
            return "R6_PROMPT_INJECTION"
        elif "test_33" in tid or "test_34" in tid or "test_35" in tid:
            return "R7_BROWSER_ISOLATION"
        elif "test_36" in tid or "test_37" in tid or "test_38" in tid:
            return "R8_FILE_TRANSFER"
        return "R1_PROTOCOL_GOVERNANCE"


    failed_names = {test._testMethodName: err for test, err in result.failures}
    error_names = {test._testMethodName: err for test, err in result.errors}

    for tname in all_tests:
        cat = assign_category(tname)
        status = "PASSED"
        err_msg = None
        if tname in failed_names:
            status = "FAILED"
            err_msg = failed_names[tname]
            categories[cat]["failed"] += 1
        elif tname in error_names:
            status = "ERROR"
            err_msg = error_names[tname]
            categories[cat]["errors"] += 1
        else:
            categories[cat]["passed"] += 1

        categories[cat]["tests"].append({
            "test_name": tname,
            "status": status,
            "error": err_msg,
        })

    out_dir = REPO_ROOT / "bench-results" / "phase95_mcp_browser_security"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "PHASE_9_5_ADVERSARIAL_RESULTS.json"

    benchmark_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase": "9.5",
        "title": "MCP Ecosystem & Browser Agent Security Adversarial Suite",
        "repository": "SriAkhilSJ/PulseAIRepo",
        "branch": "feat/prompt-cache-stabilization",
        "verdict": "MCP AND BROWSER AGENT SECURITY VERIFIED" if result.wasSuccessful() else "VERIFICATION FAILED",
        "total_tests": result.testsRun,
        "passed_tests": result.testsRun - len(result.failures) - len(result.errors),
        "failed_tests": len(result.failures),
        "error_tests": len(result.errors),
        "success_rate_pct": round(((result.testsRun - len(result.failures) - len(result.errors)) / max(1, result.testsRun)) * 100, 2),
        "duration_seconds": round(duration_s, 4),
        "paid_api_calls": 0,
        "paid_api_cost_inr": 0.0,
        "categories": categories,
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(benchmark_data, f, indent=2)

    print("-" * 80)
    print(f"Total Tests Run: {result.testsRun}")
    print(f"Passed: {benchmark_data['passed_tests']}")
    print(f"Failures: {benchmark_data['failed_tests']}")
    print(f"Errors: {benchmark_data['error_tests']}")
    print(f"Success Rate: {benchmark_data['success_rate_pct']}%")
    print(f"Total Duration: {duration_s:.4f}s")
    print(f"Verdict: {benchmark_data['verdict']}")
    print(f"Results Written To: {out_file}")
    print("=" * 80)

    if not result.wasSuccessful():
        sys.exit(1)


if __name__ == "__main__":
    main()
