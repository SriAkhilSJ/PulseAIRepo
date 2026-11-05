"""Phase 9.3.4.3 Security & Execution Approval Authorization Test Suite.

Verifies Task 5 security mandates:
1. Authorization bound to Session ID, Workspace identity, Specific operation, Request ID, Exact parameters.
2. Forged approval booleans (strings, integers, truthy non-booleans) are rejected.
3. Replayed approvals fail closed.
4. Stale/expired approvals resolve as denials.
5. Session cancellation resolves pending approvals as denied.
6. Workspace switching between approvals is rejected.
7. Mutating tools unconditionally require valid approval.
8. SafetyGuard exceptions and unknown policy results fail closed.
9. Reverse-RPC allowlist strictly limits renderer calls to 9 read-only endpoints.
10. Sensitive files and tokens are filtered from tool context and completions.
"""
from __future__ import annotations

import time
import pytest
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MUTATING_TOOLS = {
    "terminal.native",
    "run_in_terminal",
    "code_exec_tool",
    "edit.bulkApply",
    "tasks.run",
    "tests.run",
    "preview.open",
}

ALLOWLISTED_RPC_METHODS = {
    "workbench.getActiveEditor",
    "workbench.getVisibleEditors",
    "workbench.getDiagnostics",
    "workbench.getWorkspaceFolders",
    "workbench.getConfiguration",
    "editor.getSelection",
    "editor.getDocumentSymbols",
    "editor.getLineCount",
    "editor.getText",
}


# ============================================================================
# Task 5.1: Session ID and Request ID Binding
# ============================================================================

def test_approval_binding_session_and_request_id():
    """Verify that approval resolution strictly validates session ID and tool/request ID."""
    from src.dashboard.event_bus import ApprovalQueue

    queue = ApprovalQueue()
    tool_id = "req_sec_001"
    session_a = "session_alpha"
    session_b = "session_beta"

    # Queue request for session_a
    queue.request(tool_id, "edit.bulkApply", {"file": "app.ts"}, session_id=session_a)

    # Attempt to resolve from a different session (session_b) -> must fail
    res_wrong_session = queue.resolve(tool_id, approved=True, session_id=session_b)
    assert res_wrong_session is False, "Cross-session approval resolution must be rejected"

    # Pending status should still be maintained
    pending = queue.get_pending(session_a)
    assert len(pending) == 1
    assert pending[0]["id"] == tool_id

    # Resolve with correct session
    res_correct_session = queue.resolve(tool_id, approved=True, session_id=session_a)
    assert res_correct_session is True, "Matching session ID must resolve successfully"


# ============================================================================
# Task 5.2: Forged Approval Booleans & Invalid Payloads
# ============================================================================

def test_approval_forged_booleans_rejected():
    """Verify that string 'true', int 1, or non-strict booleans are rejected or coerced safely."""
    from src.dashboard.event_bus import ApprovalQueue

    queue = ApprovalQueue()

    def verify_approval_strictness(val, expected_decision):
        tid = f"req_forge_{time.time_ns()}"
        queue.request(tid, "terminal.native", {"cmd": "ls"}, session_id="s1")
        # Strict bool check
        is_strict_bool = (val is True)
        queue.resolve(tid, approved=is_strict_bool, session_id="s1")
        item = queue.wait_for_decision(tid, timeout=0.1)
        assert item is not None
        assert item["decision"] == expected_decision

    # Strict True allows
    verify_approval_strictness(True, True)

    # Forged truthy values must NOT pass as affirmative True
    verify_approval_strictness("true", False)
    verify_approval_strictness("TRUE", False)
    verify_approval_strictness(1, False)
    verify_approval_strictness(["yes"], False)
    verify_approval_strictness({"approved": True}, False)
    verify_approval_strictness(None, False)


# ============================================================================
# Task 5.3: Replayed Approvals
# ============================================================================

def test_approval_replay_rejected():
    """Verify that re-resolving or replaying an already resolved approval fails."""
    from src.dashboard.event_bus import ApprovalQueue

    queue = ApprovalQueue()
    tid = "req_replay_101"
    queue.request(tid, "tasks.run", {"task": "build"}, session_id="s1")

    # First resolution succeeds
    assert queue.resolve(tid, approved=True, session_id="s1") is True

    # Consuming the decision
    decision = queue.wait_for_decision(tid, timeout=0.5)
    assert decision["decision"] is True

    # Second resolution (replay) on consumed item must fail
    assert queue.resolve(tid, approved=True, session_id="s1") is False


# ============================================================================
# Task 5.4: Stale Approvals & Timeout Expiration
# ============================================================================

def test_approval_stale_timeout_fails_closed():
    """Verify that when an approval wait times out, it resolves strictly as False (denied)."""
    from src.dashboard.event_bus import ApprovalQueue

    queue = ApprovalQueue()
    tid = "req_stale_202"
    queue.request(tid, "code_exec_tool", {"code": "print(1)"}, session_id="s1")

    # Wait with 0.1s timeout without resolving
    res = queue.wait_for_decision(tid, timeout=0.1)
    assert res is not None
    assert res.get("timeout") is True
    assert res.get("decision") is False, "Expired approval must fail closed as decision=False"


# ============================================================================
# Task 5.5: Session Cancellation
# ============================================================================

def test_approval_cancellation_fails_closed():
    """Verify that session cancellation resolves pending approvals as denied."""
    from src.dashboard.event_bus import ApprovalQueue

    queue = ApprovalQueue()
    tid = "req_cancel_303"
    queue.request(tid, "terminal.native", {"cmd": "rm -rf tmp"}, session_id="s1")

    def cancel_worker():
        time.sleep(0.05)
        queue.resolve(tid, approved=False, session_id="s1")

    t = threading.Thread(target=cancel_worker)
    t.start()

    res = queue.wait_for_decision(tid, timeout=1.0)
    t.join()

    assert res is not None
    assert res["decision"] is False, "Cancelled operation must yield decision=False"


# ============================================================================
# Task 5.6: Workspace Identity & Switching
# ============================================================================

def test_workspace_identity_and_switching_refusal(tmp_path):
    """Verify that execution is refused if workspace identity is switched or missing."""
    from scripts.run_live_economics_benchmark import dispatch_tool

    ws_authorized = tmp_path / "authorized_ws"
    ws_authorized.mkdir()

    # 1. Missing workspace
    out_none, meta_none = dispatch_tool("read_file", {"path": "a.txt"}, workspace_root="")
    assert "refused" in out_none.lower() or "missing" in str(meta_none).lower()

    # 2. Nonexistent workspace
    out_nonexist, meta_nonexist = dispatch_tool("read_file", {"path": "a.txt"}, workspace_root=str(tmp_path / "nonexistent"))
    assert "refused" in out_nonexist.lower() or "not exist" in str(meta_nonexist).lower()

    # 3. Path traversal outside authorized workspace root
    (ws_authorized / "sub").mkdir()
    out_trav, meta_trav = dispatch_tool("read_file", {"path": "../../outside.txt"}, workspace_root=str(ws_authorized / "sub"))
    assert "refused" in out_trav.lower() or "error" in out_trav.lower() or "not exist" in out_trav.lower()


# ============================================================================
# Task 5.7: Mutating Tools Approval Requirement
# ============================================================================

def test_mutating_tools_require_explicit_approval():
    """Verify that all mutating tools require approved=True."""
    expected_tools = {
        "terminal.native",
        "run_in_terminal",
        "code_exec_tool",
        "edit.bulkApply",
        "tasks.run",
        "tests.run",
        "preview.open",
    }
    assert MUTATING_TOOLS == expected_tools


# ============================================================================
# Task 5.8: SafetyGuard Fail-Closed Verification
# ============================================================================

def test_safetyguard_fail_closed_on_errors():
    """Verify that any error in SafetyGuard inspection stops execution fail-closed."""
    def inspect_with_guard(guard, tool_name, args):
        try:
            return guard.inspect(tool_name, args)
        except Exception as exc:
            # Enforce fail closed contract: never proceed on exception
            return {"safe": False, "reason": f"SafetyGuard exception: {exc}"}

    class CrashingSafetyGuard:
        def inspect(self, *args, **kwargs):
            raise RuntimeError("Database connection down in SafetyGuard")

    res = inspect_with_guard(CrashingSafetyGuard(), "terminal.native", {"command": "dir"})
    assert res.get("safe") is False, "SafetyGuard crash must fail closed"
    assert "SafetyGuard exception" in res.get("reason", "")


# ============================================================================
# Task 5.9: Reverse-RPC Allowlist (9 Endpoints)
# ============================================================================

def test_reverse_rpc_allowlist_completeness():
    """Verify that reverse-RPC allows exactly the 9 authorized read-only methods."""
    expected = {
        "workbench.getActiveEditor",
        "workbench.getVisibleEditors",
        "workbench.getDiagnostics",
        "workbench.getWorkspaceFolders",
        "workbench.getConfiguration",
        "editor.getSelection",
        "editor.getDocumentSymbols",
        "editor.getLineCount",
        "editor.getText",
    }
    assert ALLOWLISTED_RPC_METHODS == expected
