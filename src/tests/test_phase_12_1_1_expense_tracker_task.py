"""
test_phase_12_1_1_expense_tracker_task.py - End-to-End Expense Tracker Engineering Task Qualification.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.orchestration.models import TaskVerdict
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
from src.workspace.mutation_broker import WorkspaceMutationBroker


class TestPhase1211ExpenseTrackerTask(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="crusor_qual_expense_")
        self.workspace = (Path(self.tmp) / "expense_tracker").resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(["git", "init"], cwd=str(self.workspace), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "tester@crusor.ai"], cwd=str(self.workspace), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Crusor Qualifier"], cwd=str(self.workspace), check=True, capture_output=True)
            readme = self.workspace / "README.md"
            readme.write_text("# Expense Tracker Workspace\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=str(self.workspace), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=str(self.workspace), check=True, capture_output=True)
        except Exception:
            pass

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_expense_tracker_end_to_end_engineering_lifecycle(self) -> None:
        """
        Executes:
        'Build a simple expense tracker with expense creation, categories, expense totals and a dashboard. Include basic validation and tests.'
        """
        prompt = (
            "Build a simple expense tracker with expense creation, categories, "
            "expense totals and a dashboard. Include basic validation and tests."
        )

        progress_snapshots = []
        orchestrator = EngineeringExecutionOrchestrator(
            workspace_root=str(self.workspace),
            tenant_id="qual_tenant_expense",
        )

        delivery = orchestrator.run_task(
            task_prompt=prompt,
            task_id="task_qual_expense_01",
            on_progress=lambda view: progress_snapshots.append(view),
        )

        # 1. Pipeline Completion
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.task_id, "task_qual_expense_01")
        self.assertEqual(delivery.verdict, TaskVerdict.COMPLETED)

        # 2. Files Implemented & Broker Ledger Verification
        self.assertGreater(len(delivery.files_changed), 0)
        broker = WorkspaceMutationBroker.get_instance(str(self.workspace), tenant_id="qual_tenant_expense")
        records = broker.ledger.get_records("task_qual_expense_01")
        self.assertGreater(len(records), 0)
        for rec in records:
            self.assertEqual(rec.status.value, "APPLIED")
            self.assertTrue((self.workspace / rec.file_path).exists())

        # 3. Independent Verification
        self.assertTrue(delivery.independently_verified)
        self.assertGreater(len(delivery.evidence_references), 0)

        # 4. Production Readiness Diagnostic
        self.assertIsNotNone(delivery.production_readiness_verdict)

        # 5. Progress Event Progression
        stages = [s.get("current_step") for s in progress_snapshots]
        self.assertIn("USER_REQUEST", stages)
        self.assertIn("REQUEST_UNDERSTANDING", stages)
        self.assertIn("PROJECT_DISCOVERY", stages)
        self.assertIn("ARCHITECTURE_VALIDATION", stages)
        self.assertIn("ENGINEERING_PLAN", stages)
        self.assertIn("IMPLEMENTATION", stages)
        self.assertIn("FINAL_DELIVERY", stages)

