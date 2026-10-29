#!/usr/bin/env python3
"""Agent Core Minute Diagnostics & Continuous Health Runner.

As an Agent Developer, this script tests and verifies every granular (minute)
aspect of Agent Core:
1. Core Graph compilation and routing sanity (chat_graph, gates)
2. State schema and contract synthesis (AgentState, StatusContract)
3. 4-state verification receipt calculation
4. Workspace controller monotonic revision tracking
5. Toolset & MCP client integration (including mcptest)
6. Focused pytest lane execution for all Agent Core test suites
"""
import sys
import time
import subprocess
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def log(msg: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [Agent Core Monitor] {msg}")


def test_core_imports_and_contracts():
    log("Checking Agent Core modules and contract integrity...")
    from src.graphs.state import AgentState
    from src.graphs.chat_graph import graph, finalize_node
    from src.graphs.gates import derive_4state_verification_receipt, _verification_receipt_status
    from src.runtime.status_contract import synthesize_status_contract, StatusContract
    from src.runtime.workspace_controller import WorkspaceController
    from src.tools.mcp_client import discover_mcp_tools, call_mcp_tool

    # Verify graph can compile
    assert graph is not None, "Failed to compile chat graph"
    log("  [PASS] Chat graph compilation verified")

    # Verify status contract synthesis
    dummy_state = {
        "current_task": "test task",
        "messages": [],
        "steps_completed": [],
        "failed_steps": [],
        "task_completed": True,
        "task_status": "completed",
    }
    sc = synthesize_status_contract(
        run_outcome="completed",
        verification_status="verified",
        specification_status="satisfied",
    )
    assert sc is not None
    assert sc["run_outcome"] == "completed"
    log("  [PASS] Status contract synthesis verified")

    # Verify 4-state receipt
    r = derive_4state_verification_receipt(dummy_state)
    assert "state" in r
    log("  [PASS] 4-state verification receipt engine verified")

    # Verify workspace controller
    wc = WorkspaceController()
    rev1 = wc.revision
    assert isinstance(rev1, int)
    log(f"  [PASS] Workspace controller verified (active revision: {rev1})")

    # Verify mcptest tools discovery
    tools = discover_mcp_tools(".")
    mcptest_tools = [t["name"] for t in tools if "mcptest" in t["name"]]
    assert len(mcptest_tools) >= 1, "mcptest server not discovered"
    log(f"  [PASS] MCP client & mcptest discovered: {mcptest_tools}")


def run_focused_pytest_suite():
    log("Running Agent Core focused pytest regression and contract lane...")
    pytest_bin = Path(sys.executable).parent / "pytest.exe"
    if not pytest_bin.exists():
        pytest_cmd = [sys.executable, "-m", "pytest"]
    else:
        pytest_cmd = [str(pytest_bin)]

    test_targets = [
        "src/tests/test_agent_core_evals.py",
        "src/tests/test_mcptest_server.py",
        "src/tests/test_verification_contracts.py",
        "src/tests/test_status_contract.py",
        "src/tests/test_workspace_controller.py",
        "src/tests/test_hardening_checkup.py",
        "src/tests/test_agent_lifecycle_scenarios.py",
        "src/tests/test_mcp_client.py"
    ]

    cmd = [*pytest_cmd, "-q", "--tb=short", *test_targets]
    start = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.time() - start

    if res.returncode == 0:
        log(f"  [PASS] All core test targets passed in {duration:.2f}s!")
        print(res.stdout.strip())
    else:
        log(f"  [FAIL] Test failure detected (exit code {res.returncode}):")
        print(res.stdout)
        print(res.stderr)
        return False
    return True


def run_diagnostics_cycle():
    log("=== Commencing Agent Core Diagnostic Cycle ===")
    test_core_imports_and_contracts()
    success = run_focused_pytest_suite()
    if success:
        log("=== Cycle Result: ALL AGENT CORE SYSTEMS HEALTHY ===")
    else:
        log("=== Cycle Result: ISSUES DETECTED ===")
    return success


def run_continuous_loop(interval_seconds: int = 60):
    log(f"Starting continuous testing loop (interval: {interval_seconds}s). Press Ctrl+C to stop.")
    cycle = 1
    try:
        while True:
            log(f"--- Starting Diagnostic Loop #{cycle} ---")
            success = run_diagnostics_cycle()
            cycle += 1
            log(f"Waiting {interval_seconds}s until next check...")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        log("Continuous testing stopped by user.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agent Core Diagnostic and Health Suite")
    parser.add_argument("--continuous", action="store_true", help="Run diagnostic cycle continuously every minute")
    parser.add_argument("--interval", type=int, default=60, help="Interval in seconds for continuous mode (default: 60)")
    args = parser.parse_args()

    if args.continuous:
        run_continuous_loop(args.interval)
    else:
        success = run_diagnostics_cycle()
        sys.exit(0 if success else 1)
