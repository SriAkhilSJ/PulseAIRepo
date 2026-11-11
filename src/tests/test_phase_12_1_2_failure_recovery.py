"""
test_phase_12_1_2_failure_recovery.py - Failure & Recovery Verification across 10 Failure Modes.

Phase 12.1.2: Desktop Runtime, Model Execution & OS Sandbox Closure.
Verifies graceful handling, containment, and recovery across:
1. Workspace confinement violation (path traversal attempt outside workspace).
2. RBAC authorization denial (unauthorized agent role).
3. FinOps budget limit exhaustion (spending cap breach).
4. Terminal process execution timeout.
5. AppContainer OS filesystem denial (unauthorized read outside sandbox).
6. AppContainer OS network denial (egress socket connection attempt).
7. Code generation syntax validation error handling.
8. Interactive task cancellation by user.
9. Stale/forged cryptographic approval token rejection.
10. Direct unbrokered workspace mutation prevention.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path
import uuid

import pytest

from src.identity.models import Permission, RoleTemplate, User
from src.identity.tool_authorizer import get_tool_authorizer
from src.orchestration.finops_governor import BudgetExhaustedError, OrchestrationFinOpsGovernor
from src.orchestration.models import EngineeringTaskNode
from src.orchestration.model_adapter import ModelExecutionAdapter
from src.orchestration.implementation_engine import ControlledImplementationEngine
from src.orchestration.loop import BoundedAutonomousReasoningLoop
from src.security.contracts import ExecutionMode, ExecutionRequest, SecurityViolationType
from src.security.execution_broker import ExecutionBroker
from src.tools.terminal_tools import terminal
from src.workspace.mutation_broker import (
    PathSecurityViolation,
    WorkspaceMutationBroker,
)


class TestPhase1212FailureRecovery:

    def test_mode_1_workspace_confinement_violation(self, tmp_path):
        """Mode 1: Path traversal attempt outside workspace is caught and rejected."""
        ws = str(tmp_path.resolve())
        broker = WorkspaceMutationBroker.get_instance(ws)
        with pytest.raises(PathSecurityViolation) as exc_info:
            broker.create_file(
                path="../outside_secret.txt",
                content="MALICIOUS",
                task_id="t1",
            )
        assert "confined" in str(exc_info.value).lower() or "escapes" in str(exc_info.value).lower()

    def test_mode_2_rbac_authorization_denial(self, tmp_path):
        """Mode 2: Restricted user is denied permission for workspace file mutation."""
        ws = str(tmp_path.resolve())
        authorizer = get_tool_authorizer()
        viewer = User(
            user_id="viewer_bob",
            email="bob@corp.local",
            display_name="Bob Viewer",
            is_superadmin=False,
        )
        res = authorizer.authorize_tool_call(
            principal=viewer,
            org_id="tenant_x",
            workspace_id=ws,
            tool_name="write_file",
            tool_args={"path": "main.py"},
        )
        assert not res.is_allowed
        assert "deny" in res.reason.lower()

    def test_mode_3_finops_budget_exhaustion(self):
        """Mode 3: FinOps governor halts execution when operation exceeds budget."""
        gov = OrchestrationFinOpsGovernor(task_id="t_finops", budget_inr=5.0)
        gov.record_usage(input_tokens=1000, output_tokens=2000, cost_inr=4.5)
        with pytest.raises(BudgetExhaustedError) as exc_info:
            gov.authorize_operation(estimated_tokens=5000, estimated_cost_inr=2.0)
        assert "budget" in str(exc_info.value).lower()

    def test_mode_4_terminal_execution_timeout(self, tmp_path):
        """Mode 4: Terminal command times out when exceeding allocated time budget."""
        ws = str(tmp_path.resolve())
        cmd = f'"{sys.executable}" -c "import time; time.sleep(5)"'
        out = terminal.invoke(
            {"command": cmd, "timeout": 1},
            {"configurable": {"workspace": ws, "thread_id": "sess_timeout"}},
        )
        assert "timed out" in out.lower() or "timeout" in out.lower()

    def test_mode_5_appcontainer_os_filesystem_denial(self, tmp_path, monkeypatch):
        """Mode 5: AppContainer OS kernel blocks reading files outside the workspace."""
        monkeypatch.setenv("CRUSOR_ENABLE_APPCONTAINER", "1")
        monkeypatch.setenv("CRUSOR_SANDBOX_TERMINAL", "1")
        external_dir = tmp_path.parent / f"ext_sec_{uuid.uuid4().hex[:6]}"
        external_dir.mkdir(exist_ok=True)
        secret_file = external_dir / "secret.env"
        secret_file.write_text("DB_PASSWORD=secret123\n", encoding="utf-8")
        escaped_path = str(secret_file.resolve()).replace("\\", "/")

        ws = str(tmp_path.resolve())
        cmd = f'"{sys.executable}" -c "exec(\'\'\'try:\\n open(\'{escaped_path}\').read()\\nexcept Exception as e:\\n print(\\\'BLOCKED:\\\' + type(e).__name__)\\n\'\'\')"'
        try:
            out = terminal.invoke(
                {"command": cmd},
                {"configurable": {"workspace": ws, "thread_id": "sess_ac_fs"}},
            )
            assert "DB_PASSWORD" not in out
            assert "BLOCKED:PermissionError" in out or "BLOCKED" in out
        finally:
            if secret_file.exists():
                secret_file.unlink(missing_ok=True)
            if external_dir.exists():
                external_dir.rmdir()

    def test_mode_6_appcontainer_os_network_denial(self, tmp_path, monkeypatch):
        """Mode 6: AppContainer OS kernel denies raw network socket connections."""
        monkeypatch.setenv("CRUSOR_ENABLE_APPCONTAINER", "1")
        monkeypatch.setenv("CRUSOR_SANDBOX_TERMINAL", "1")
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(1)

        ws = str(tmp_path.resolve())
        cmd = f'"{sys.executable}" -c "import socket; exec(\'\'\'try:\\n s=socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(1.0); s.connect((\\\'127.0.0.1\\\', {port}))\\n print(\\\'NET_CONNECTED\\\')\\nexcept Exception as e:\\n print(\\\'NET_DENIED:\\\' + type(e).__name__)\\n\'\'\')"'
        try:
            out = terminal.invoke(
                {"command": cmd},
                {"configurable": {"workspace": ws, "thread_id": "sess_ac_net_fail"}},
            )
            assert "NET_CONNECTED" not in out
            assert "NET_DENIED" in out
        finally:
            srv.close()

    def test_mode_7_syntax_validation_warning(self, tmp_path):
        """Mode 7: Model execution adapter catches syntax errors and produces syntax warnings."""
        ws = str(tmp_path.resolve())
        adapter = ModelExecutionAdapter(workspace_root=ws, mock_mode=True)
        node = EngineeringTaskNode(
            node_id="task_bad_syntax",
            description="Testing syntax validation",
            objective="Check syntax error handling",
            target_files=["broken.py"],
        )
        impl = ControlledImplementationEngine(ws)
        finops = OrchestrationFinOpsGovernor(task_id="t_syntax", budget_inr=100.0)
        loop = BoundedAutonomousReasoningLoop()

        def bad_code(n, target):
            return "def incomplete_func(\n  # Missing closing and body"

        success = adapter.execute_node(
            task_id="task_syn_test",
            node=node,
            specification=None,
            blueprint=None,
            project_knowledge=None,
            impl_engine=impl,
            finops=finops,
            reasoning_loop=loop,
            custom_code_generator=bad_code,
        )
        assert success
        assert (Path(ws) / "broken.py").exists()

    def test_mode_8_interactive_task_cancellation(self, tmp_path):
        """Mode 8: User cancellation triggers TurnCancelledError cleanly."""
        from src.llm.factory import TurnCancelledError
        ws = str(tmp_path.resolve())
        adapter = ModelExecutionAdapter(workspace_root=ws, mock_mode=True)
        node = EngineeringTaskNode(
            node_id="task_cancelled",
            description="Testing cancellation",
            objective="Ensure cancellation raises TurnCancelledError",
            target_files=["cancelled.py"],
        )
        impl = ControlledImplementationEngine(ws)
        finops = OrchestrationFinOpsGovernor(task_id="t_cancel", budget_inr=100.0)
        loop = BoundedAutonomousReasoningLoop()

        with pytest.raises(TurnCancelledError) as exc_info:
            adapter.execute_node(
                task_id="task_cancel_test",
                node=node,
                specification=None,
                blueprint=None,
                project_knowledge=None,
                impl_engine=impl,
                finops=finops,
                reasoning_loop=loop,
                cancellation_checker=lambda: True,
            )
        assert "cancelled by user" in str(exc_info.value).lower()

    def test_mode_9_stale_or_forged_approval_token_rejection(self, tmp_path):
        """Mode 9: Execution broker detects and rejects forged/stale approval tokens."""
        ws = str(tmp_path.resolve())
        broker = ExecutionBroker.get_instance()
        forged_token = "sess:req:fakehash:fakewshash:9999999999:invalidsig"
        req = ExecutionRequest(
            execution_id="exec_forged",
            session_id="sess_1",
            request_id="req_1",
            workspace_root=ws,
            tool_name="terminal",
            command="echo test",
            argv=["cmd.exe", "/c", "echo test"],
            approval_token=forged_token,
        )
        receipt = broker.execute(req)
        assert receipt.exit_code == 126
        assert SecurityViolationType.FORGED_OR_STALE_APPROVAL.value in receipt.security_violations

    def test_mode_10_direct_unbrokered_mutation_prevention(self, tmp_path):
        """Mode 10: file_tools.write_file wraps mutation through WorkspaceMutationBroker."""
        from src.tools.file_tools import write_file
        ws = str(tmp_path.resolve())
        with pytest.raises(ValueError) as exc_info:
            write_file.invoke(
                {"path": "../forbidden_escape.txt", "content": "BLOCKED"},
                {"configurable": {"workspace": ws}},
            )
        assert "escapes workspace" in str(exc_info.value).lower()
