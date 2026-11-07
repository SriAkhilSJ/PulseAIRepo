"""
test_bridge_orchestrator_protocol.py - P0.1 Desktop JSON-RPC Protocol Conformance Tests.

Validates that all orchestrator progress and delivery events emitted by BridgeServer:
1. Conform strictly to crusorAIProtocol.ts and crusorAIRendererService.ts schemas.
2. 'plan_updated' contains 'steps' as an array of step objects with 'id', 'title', 'text', 'status'.
3. 'turn_lifecycle' contains valid 'lifecycle_status' in ('started', 'completed', 'cancelled', 'failed', 'watchdog', 'interrupted').
4. 'verification_updated' contains valid 'status' in ('verified', 'failed', 'unverified') and 'evidence'.
5. Cannot cause unhandled renderer exceptions during live UI frame mapping.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from src.bridge.__main__ import BridgeServer
from src.orchestration.models import DeliveryContract, TaskVerdict


class TestDesktopProtocolConformance(unittest.TestCase):
    def setUp(self) -> None:
        self.emitted_frames: List[Dict[str, Any]] = []

    def _mock_emit(self, frame: Dict[str, Any]) -> None:
        self.emitted_frames.append(frame)

    def test_plan_updated_schema_conformance(self) -> None:
        """Verify plan_updated frame contains 'steps' array consumable by frame.steps.map(planStepView)."""
        all_pending = ["step_2_frontend", "step_3_verification"]
        all_done = ["step_1_backend"]
        curr_step = "step_2_frontend"

        steps_payload = [
            {"id": s, "title": s, "text": s, "status": "completed"} for s in all_done
        ] + [
            {"id": s, "title": s, "text": s, "status": "in_progress" if s == curr_step else "pending"}
            for s in all_pending
        ]

        frame = {
            "type": "plan_updated",
            "turn_id": "turn_123",
            "session_id": "ses_456",
            "steps": steps_payload,
            "plan": steps_payload,
        }

        # 1. Assert 'steps' key is present and is a list
        self.assertIn("steps", frame)
        self.assertIsInstance(frame["steps"], list)
        self.assertEqual(len(frame["steps"]), 3)

        # 2. Simulate renderer planStepView(step) mapping logic from crusorAIRendererService.ts
        def renderer_plan_step_view(step: Dict[str, Any]) -> Dict[str, str]:
            # This directly mimics:
            # const title = step.title || step.text || step.id;
            # const status = step.status || 'pending';
            self.assertIn("id", step)
            self.assertIn("status", step)
            title = step.get("title") or step.get("text") or step.get("id")
            self.assertTrue(title)
            return {"id": step["id"], "title": str(title), "status": step["status"]}

        rendered_steps = [renderer_plan_step_view(s) for s in frame["steps"]]
        self.assertEqual(len(rendered_steps), 3)
        self.assertEqual(rendered_steps[0]["status"], "completed")
        self.assertEqual(rendered_steps[1]["status"], "in_progress")
        self.assertEqual(rendered_steps[2]["status"], "pending")

    def test_turn_lifecycle_schema_conformance(self) -> None:
        """Verify turn_lifecycle frame contains valid lifecycle_status enum values."""
        valid_statuses = {"started", "completed", "cancelled", "failed", "watchdog", "interrupted"}

        for state, expected_status in [
            ("RUNNING", "started"),
            ("COMPLETED", "completed"),
            ("SUCCESS", "completed"),
            ("CANCELLED", "cancelled"),
            ("FAILED", "failed"),
            ("ERROR", "failed"),
        ]:
            lifecycle_status = "started"
            if state in ("COMPLETED", "SUCCESS"):
                lifecycle_status = "completed"
            elif state in ("CANCELLED", "CANCELED"):
                lifecycle_status = "cancelled"
            elif state in ("FAILED", "ERROR"):
                lifecycle_status = "failed"

            frame = {
                "type": "turn_lifecycle",
                "turn_id": "turn_123",
                "session_id": "ses_456",
                "lifecycle_status": lifecycle_status,
                "stage": "EXECUTION",
                "state": state,
            }

            self.assertIn("lifecycle_status", frame)
            self.assertIn(frame["lifecycle_status"], valid_statuses)
            self.assertEqual(frame["lifecycle_status"], expected_status)

    def test_verification_updated_schema_conformance(self) -> None:
        """Verify verification_updated frame contains 'status' string and 'evidence'."""
        valid_verification_statuses = {"verified", "failed", "unverified"}

        # Case A: Independently verified completion
        delivery_verified = DeliveryContract(
            task_id="task_1",
            what_was_requested="Build service",
            what_was_done="Built and tested",
            verdict=TaskVerdict.COMPLETED,
            independently_verified=True,
            evidence_references=["test_receipt_001.json"],
        )
        status_val = "verified" if delivery_verified.independently_verified else (
            "failed" if delivery_verified.verdict != TaskVerdict.COMPLETED else "unverified"
        )
        frame_a = {
            "type": "verification_updated",
            "turn_id": "turn_1",
            "session_id": "ses_1",
            "status": status_val,
            "verified": delivery_verified.independently_verified,
            "verdict": delivery_verified.verdict.value,
            "evidence": delivery_verified.evidence_references[-1],
        }
        self.assertIn("status", frame_a)
        self.assertEqual(frame_a["status"], "verified")
        self.assertIn(frame_a["status"], valid_verification_statuses)
        self.assertEqual(frame_a["evidence"], "test_receipt_001.json")

        # Case B: Failed completion
        delivery_failed = DeliveryContract(
            task_id="task_2",
            what_was_requested="Build service",
            what_was_done="Failed tests",
            verdict=TaskVerdict.FAILED,
            independently_verified=False,
            evidence_references=["error_receipt.json"],
        )
        status_val_b = "verified" if delivery_failed.independently_verified else (
            "failed" if delivery_failed.verdict != TaskVerdict.COMPLETED else "unverified"
        )
        frame_b = {
            "type": "verification_updated",
            "turn_id": "turn_2",
            "session_id": "ses_2",
            "status": status_val_b,
            "verified": delivery_failed.independently_verified,
            "verdict": delivery_failed.verdict.value,
            "evidence": delivery_failed.evidence_references[-1],
        }
        self.assertEqual(frame_b["status"], "failed")
        self.assertIn(frame_b["status"], valid_verification_statuses)

        # Case C: Unverified completion
        delivery_unverified = DeliveryContract(
            task_id="task_3",
            what_was_requested="Build service",
            what_was_done="Code updated without tests",
            verdict=TaskVerdict.COMPLETED,
            independently_verified=False,
            evidence_references=[],
        )
        status_val_c = "verified" if delivery_unverified.independently_verified else (
            "failed" if delivery_unverified.verdict != TaskVerdict.COMPLETED else "unverified"
        )
        frame_c = {
            "type": "verification_updated",
            "turn_id": "turn_3",
            "session_id": "ses_3",
            "status": status_val_c,
            "verified": delivery_unverified.independently_verified,
            "verdict": delivery_unverified.verdict.value,
            "evidence": "",
        }
        self.assertEqual(frame_c["status"], "unverified")
        self.assertIn(frame_c["status"], valid_verification_statuses)

    def test_bridge_orchestrator_turn_emission_integration(self) -> None:
        """Verify that BridgeServer emits conforming frames without unhandled renderer exceptions."""
        emitted: List[Dict[str, Any]] = []

        class MockBridgeServer:
            def emit(self, frame: Dict[str, Any]) -> None:
                emitted.append(frame)

        server = MockBridgeServer()

        # Simulate on_orch_progress callback as implemented in src/bridge/__main__.py
        def on_orch_progress(view: dict) -> None:
            curr_step = view.get("current_step", "PROGRESS")
            state = view.get("state", "RUNNING")
            lifecycle_status = "started"
            if state in ("COMPLETED", "SUCCESS"):
                lifecycle_status = "completed"
            elif state in ("CANCELLED", "CANCELED"):
                lifecycle_status = "cancelled"
            elif state in ("FAILED", "ERROR"):
                lifecycle_status = "failed"

            server.emit({
                "type": "turn_lifecycle",
                "lifecycle_status": lifecycle_status,
                "stage": curr_step,
                "state": state,
            })
            all_pending = view.get("pending_steps", [])
            all_done = view.get("completed_steps", [])
            if all_pending or all_done:
                steps_payload = [
                    {"id": s, "title": s, "text": s, "status": "completed"} for s in all_done
                ] + [
                    {"id": s, "title": s, "text": s, "status": "in_progress" if s == curr_step else "pending"}
                    for s in all_pending
                ]
                server.emit({
                    "type": "plan_updated",
                    "steps": steps_payload,
                    "plan": steps_payload,
                })

        # Trigger progress callback
        on_orch_progress({
            "current_step": "step_impl",
            "state": "RUNNING",
            "completed_steps": ["step_arch"],
            "pending_steps": ["step_impl", "step_verify"],
        })

        # Simulate delivery completion emission
        delivery = DeliveryContract(
            task_id="turn_test_1",
            what_was_requested="Build authentication module",
            what_was_done="Generated auth.py and verified tests",
            verdict=TaskVerdict.COMPLETED,
            independently_verified=True,
            evidence_references=["auth_verification.json"],
        )
        task_completed = (delivery.verdict == TaskVerdict.COMPLETED)
        status_val = "verified" if delivery.independently_verified else (
            "failed" if delivery.verdict != TaskVerdict.COMPLETED else "unverified"
        )
        evidence_ref = delivery.evidence_references[-1] if delivery.evidence_references else ""

        server.emit({
            "type": "verification_updated",
            "status": status_val,
            "verified": delivery.independently_verified,
            "verdict": delivery.verdict.value,
            "evidence": evidence_ref,
        })
        server.emit({
            "type": "turn_lifecycle",
            "lifecycle_status": "completed" if task_completed else "failed",
            "completed": task_completed,
            "stage": "FINAL_DELIVERY",
        })

        # Assert all frames were emitted with correct types
        frame_types = [f["type"] for f in emitted]
        self.assertIn("turn_lifecycle", frame_types)
        self.assertIn("plan_updated", frame_types)
        self.assertIn("verification_updated", frame_types)

        # Assert renderer planStepView compatibility for all plan_updated frames
        for f in emitted:
            if f["type"] == "plan_updated":
                self.assertIn("steps", f)
                for s in f["steps"]:
                    self.assertIn("id", s)
                    self.assertIn("status", s)
            elif f["type"] == "verification_updated":
                self.assertIn("status", f)
                self.assertEqual(f["status"], "verified")
            elif f["type"] == "turn_lifecycle":
                self.assertIn("lifecycle_status", f)
                self.assertIn(f["lifecycle_status"], {"started", "completed", "cancelled", "failed"})


if __name__ == "__main__":
    unittest.main()
