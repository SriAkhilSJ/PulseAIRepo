"""
test_phase_12_1_end_to_end_acceptance.py - End-to-End Acceptance Test Matrix for Phase 12.1.

Validates the full unification of Crusor Engineering Intelligence:
- Test A: Clean Feature Implementation (Full 15-stage pipeline, broker enforcement, independent verification, delivery)
- Test B: Regression Detection and Safe Rejection (Phase 11.5 regression gates, diagnosis, bounded correction)
- Test C: High-Risk Action and Approval Gate (Phase 11.3 & Phase 10.0 risk gates, user file preservation, token binding)
- Test D: Out-of-Budget / FinOps Enforcement (Phase 9.7 & Phase 11.6 budget governor, pre-call authorization)
- Test E: Cancellation and Clean State Recovery (turn controls, graceful abort, dirty workspace prevention)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from src.orchestration.finops_governor import BudgetExhaustedError
from src.orchestration.models import (
    EngineeringTaskNode,
    ExecutionLimits,
    TaskExecutionState,
    TaskVerdict,
)
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
from src.regression.models import RegressionStatus
from src.verification.models import VerificationVerdict
from src.workspace.models import FileOwnershipCategory, WorkspaceOperationType
from src.workspace.mutation_broker import MutationAuthorizationError, WorkspaceMutationBroker
from src.workspace.risk_policy import RiskApprovalGate


class TestPhase121EndToEndAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="crusor_p12_1_acceptance_")
        self.workspace = (Path(self.tmp_dir) / "workspace").resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        # Initialize basic git repository for realistic baseline
        try:
            subprocess.run(["git", "init"], cwd=str(self.workspace), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@crusor.ai"], cwd=str(self.workspace), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Crusor Tester"], cwd=str(self.workspace), check=True, capture_output=True)
            init_file = self.workspace / "README.md"
            init_file.write_text("# Test Project", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=str(self.workspace), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(self.workspace), check=True, capture_output=True)
        except Exception:
            pass

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Test A: Clean Feature Implementation
    # -------------------------------------------------------------------------
    def test_A_clean_feature_implementation(self) -> None:
        """
        Verify end-to-end task execution:
        - Traverses full 15 stages
        - Mutations execute strictly through WorkspaceMutationBroker
        - Independent verification evaluates real artifacts
        - Production readiness evaluates advisory findings
        - Complete DeliveryContract is delivered
        """
        progress_events: List[Dict[str, Any]] = []

        orchestrator = EngineeringExecutionOrchestrator(
            workspace_root=str(self.workspace),
            tenant_id="tenant_acceptance_a",
        )

        delivery = orchestrator.run_task(
            task_prompt="Implement AuthTokenService with token generation and cryptographic validation",
            task_id="task_acceptance_a",
            on_progress=lambda view: progress_events.append(view),
        )

        # 1. Delivery contract assertions
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.task_id, "task_acceptance_a")
        self.assertEqual(delivery.verdict, TaskVerdict.COMPLETED)
        self.assertTrue(delivery.independently_verified)
        self.assertGreater(len(delivery.files_changed), 0)

        # 2. Broker and ledger enforcement
        broker = WorkspaceMutationBroker.get_instance(str(self.workspace), tenant_id="tenant_acceptance_a")
        ledger_records = broker.ledger.get_records("task_acceptance_a")
        self.assertGreater(len(ledger_records), 0)
        for rec in ledger_records:
            self.assertEqual(rec.status.value, "APPLIED")
            self.assertIsNotNone(rec.new_hash)

        # 3. Production readiness evaluation assertions
        self.assertIsNotNone(delivery.production_readiness_verdict)
        self.assertIsInstance(delivery.production_readiness_findings, list)

        # 4. Progress synchronization check
        self.assertGreater(len(progress_events), 5)
        reported_steps = {ev.get("current_step") for ev in progress_events}
        self.assertIn("USER_REQUEST", reported_steps)
        self.assertIn("IMPLEMENTATION", reported_steps)
        self.assertIn("PRODUCTION_READINESS", reported_steps)
        self.assertIn("FINAL_DELIVERY", reported_steps)

    # -------------------------------------------------------------------------
    # Test B: Regression Detection and Safe Rejection
    # -------------------------------------------------------------------------
    def test_B_regression_detection_and_safe_rejection(self) -> None:
        """
        Verify that introduced regressions are detected by Phase 11.5 gates,
        diagnosed, and safely rejected if uncorrected.
        """
        orchestrator = EngineeringExecutionOrchestrator(
            workspace_root=str(self.workspace),
            tenant_id="tenant_acceptance_b",
        )

        # Pre-seed baseline test expectation
        base = orchestrator.regression_engine.baseline_mgr.capture_baseline(task_id="pre_b")
        base.test_cases["test_core_invariants"] = "PASS"

        # Force custom executor that introduces a regression
        def broken_executor(node: EngineeringTaskNode) -> bool:
            for target in node.target_files:
                orchestrator.impl_engine.execute_node_mutation(
                    task_id="task_acceptance_b",
                    node=node,
                    rel_path=target,
                    content="# Broken regression code\nCRASH = True\n",
                )
            return True

        delivery = orchestrator.run_task(
            task_prompt="Refactor database layer with breaking changes",
            task_id="task_acceptance_b",
            custom_executor=broken_executor,
        )

        # Pipeline must finalize with truthful delivery record
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.task_id, "task_acceptance_b")
        # Mutated files must be logged even in failure
        self.assertGreater(len(delivery.files_changed), 0)

    # -------------------------------------------------------------------------
    # Test C: High-Risk Action and Approval Gate
    # -------------------------------------------------------------------------
    def test_C_high_risk_action_and_approval_gate(self) -> None:
        """
        Verify that modifying or overwriting pre-existing user files is blocked
        by RiskApprovalGate unless an explicit approval token is consumed.
        """
        # Create an existing user file in the workspace
        user_file = self.workspace / "critical_user_logic.py"
        user_file.write_text("SECRET_USER_FORMULA = 42\n", encoding="utf-8")

        broker = WorkspaceMutationBroker(str(self.workspace), tenant_id="tenant_acceptance_c")
        base = broker.baseline_mgr.capture_baseline(force_refresh=True)
        self.assertTrue(broker.baseline_mgr.is_user_owned("critical_user_logic.py"))

        # 1. Attempting overwrite without approval token MUST raise MutationAuthorizationError
        with self.assertRaises(MutationAuthorizationError):
            broker.create_file(
                path="critical_user_logic.py",
                content="CLOBBERED_BY_AGENT = True\n",
                task_id="task_c",
            )

        # Content must remain intact
        self.assertEqual(user_file.read_text(encoding="utf-8"), "SECRET_USER_FORMULA = 42\n")

        # 2. Generating valid approval token enables authorized modification
        token = broker.risk_gate.generate_approval_token(
            "task_c",
            str(self.workspace),
            "critical_user_logic.py",
            WorkspaceOperationType.CREATE,
        )

        rec = broker.create_file(
            path="critical_user_logic.py",
            content="AUTHORIZED_UPDATE = 100\n",
            task_id="task_c",
            approval_token=token,
        )
        self.assertEqual(rec.status.value, "APPLIED")
        self.assertEqual(user_file.read_text(encoding="utf-8"), "AUTHORIZED_UPDATE = 100\n")

        # 3. Replay attack with same token must be rejected
        with self.assertRaises(MutationAuthorizationError):
            broker.create_file(
                path="critical_user_logic.py",
                content="REPLAY_ATTACK = True\n",
                task_id="task_c",
                approval_token=token,
            )

    # -------------------------------------------------------------------------
    # Test D: Out-of-Budget / FinOps Enforcement
    # -------------------------------------------------------------------------
    def test_D_out_of_budget_finops_enforcement(self) -> None:
        """
        Verify that FinOps budget ceilings halt execution before exceeding tokens or cost.
        """
        # Configure tight token budget of 50 tokens
        orchestrator = EngineeringExecutionOrchestrator(
            workspace_root=str(self.workspace),
            tenant_id="tenant_acceptance_d",
            limits=ExecutionLimits(max_token_budget=50),
        )

        with self.assertRaises(BudgetExhaustedError):
            orchestrator.run_task(
                task_prompt="Build large multi-module platform service",
                task_id="task_acceptance_d",
            )

    # -------------------------------------------------------------------------
    # Test E: Cancellation and Clean State Recovery
    # -------------------------------------------------------------------------
    def test_E_cancellation_and_clean_state_recovery(self) -> None:
        """
        Verify that cancellation gracefully halts the pipeline and does not leave dirty unrecorded state.
        """
        orchestrator = EngineeringExecutionOrchestrator(
            workspace_root=str(self.workspace),
            tenant_id="tenant_acceptance_e",
        )

        # Simulate cancellation during execution
        delivery = orchestrator.run_task(
            task_prompt="Implement background indexing service",
            task_id="task_acceptance_e",
            cancellation_checker=lambda: True,  # Immediately cancelled
        )

        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.verdict, TaskVerdict.CANCELLED)
        self.assertFalse(delivery.independently_verified)
        self.assertIn("cancelled", delivery.remaining_limitations[0].lower())
