"""
test_phase_12_1_1_security_qualification.py - Phase 12.1.1 Security Boundary Qualification Test.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from src.workspace.baseline import WorkspaceBaselineManager
from src.workspace.models import FileOwnershipCategory, RiskLevel, WorkspaceOperationType
from src.workspace.mutation_broker import (
    MutationAuthorizationError,
    WorkspaceMutationBroker,
)
from src.workspace.path_safety import PathSafetyValidator, PathSecurityViolation
from src.workspace.risk_policy import RiskApprovalGate
from src.workspace.terminal_discipline import TerminalSafetyBroker
from src.tools.terminal_tools import terminal, start_terminal
from src.tools.file_tools import write_file, edit_file


class TestPhase1211SecurityQualification(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="crusor_qual_sec_")
        self.outside_dir = Path(self.tmp) / "outside"
        self.outside_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = (Path(self.tmp) / "workspace").resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.broker = WorkspaceMutationBroker(str(self.workspace), tenant_id="qual_sec")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_01_authorized_workspace_file_mutation(self) -> None:
        """1. Authorized workspace file mutation succeeds and records in ledger."""
        rec = self.broker.create_file(
            path="src/authorized_module.py",
            content="VALID_DATA = 1\n",
            task_id="sec_t1",
        )
        self.assertEqual(rec.status.value, "APPLIED")
        self.assertTrue((self.workspace / "src" / "authorized_module.py").exists())
        records = self.broker.ledger.get_records("sec_t1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].file_path, "src/authorized_module.py")

    def test_02_modified_user_owned_file_protection(self) -> None:
        """2. Pre-existing user-owned file cannot be clobbered without explicit approval."""
        user_file = self.workspace / "user_notes.txt"
        user_file.write_text("PRIVATE USER NOTES", encoding="utf-8")

        # Capture baseline so file is classified as user-owned
        self.broker.baseline_mgr.capture_baseline(force_refresh=True)
        self.assertTrue(self.broker.baseline_mgr.is_user_owned("user_notes.txt"))

        # Refusal without approval token
        with self.assertRaises(MutationAuthorizationError):
            self.broker.create_file(
                path="user_notes.txt",
                content="AGENT OVERWRITE",
                task_id="sec_t2",
            )
        # Content remains protected
        self.assertEqual(user_file.read_text(encoding="utf-8"), "PRIVATE USER NOTES")

    def test_03_file_outside_workspace_confinement(self) -> None:
        """3. Path traversal outside workspace boundary is blocked."""
        outside_target = self.outside_dir / "secret.txt"
        outside_target.write_text("HOST SECRET", encoding="utf-8")

        with self.assertRaises(PathSecurityViolation):
            PathSafetyValidator.resolve_and_verify(self.workspace, "../outside/secret.txt")

        with self.assertRaises(PathSecurityViolation):
            self.broker.create_file(
                path="../outside/secret.txt",
                content="HACKED",
                task_id="sec_t3",
            )
        self.assertEqual(outside_target.read_text(encoding="utf-8"), "HOST SECRET")

    def test_04_symbolic_link_targeting_outside_file(self) -> None:
        """4. Symlink escaping workspace is blocked by realpath resolution."""
        outside_target = self.outside_dir / "outside_leak.txt"
        outside_target.write_text("ORIGINAL", encoding="utf-8")

        symlink_path = self.workspace / "symlink_leak.txt"
        try:
            symlink_path.symlink_to(outside_target)
            with self.assertRaises(PathSecurityViolation):
                PathSafetyValidator.resolve_and_verify(self.workspace, "symlink_leak.txt")
        except OSError:
            # On Windows without SeCreateSymbolicLinkPrivilege, symlink creation requires admin
            pass

    def test_05_protected_credential_file(self) -> None:
        """5. Sensitive credential files are classified as PROHIBITED."""
        env_file = self.workspace / ".env"
        env_file.write_text("API_SECRET=12345", encoding="utf-8")
        self.broker.baseline_mgr.capture_baseline(force_refresh=True)

        gate = RiskApprovalGate()
        risk = gate.classify_operation_risk(".env", WorkspaceOperationType.MODIFY, FileOwnershipCategory.EXISTING_USER_CLEAN)
        self.assertEqual(risk, RiskLevel.PROHIBITED)

        # PathSafetyValidator blocks sensitive paths like .env fail-closed
        with self.assertRaises((PathSecurityViolation, MutationAuthorizationError)):
            self.broker.modify_file(
                path=".env",
                old_text="12345",
                new_text="EXPOSED",
                task_id="sec_t5",
            )
        self.assertEqual(env_file.read_text(encoding="utf-8"), "API_SECRET=12345")

    def test_06_destructive_file_operation_without_approval(self) -> None:
        """6. Deleting user-owned files is strictly blocked without HIGH_RISK approval."""
        user_code = self.workspace / "user_logic.py"
        user_code.write_text("def important(): pass", encoding="utf-8")
        self.broker.baseline_mgr.capture_baseline(force_refresh=True)

        with self.assertRaises(MutationAuthorizationError):
            self.broker.delete_file(
                path="user_logic.py",
                task_id="sec_t6",
            )
        self.assertTrue(user_code.exists())

    def test_07_shell_command_restrictions(self) -> None:
        """7. TerminalSafetyBroker blocks destructive git and shell commands."""
        allowed, risk, reason = TerminalSafetyBroker.evaluate_command_safety("git reset --hard HEAD~1")
        self.assertFalse(allowed)
        self.assertEqual(risk, RiskLevel.PROHIBITED)

        allowed2, risk2, reason2 = TerminalSafetyBroker.evaluate_command_safety("git clean -fd")
        self.assertFalse(allowed2)
        self.assertEqual(risk2, RiskLevel.PROHIBITED)
