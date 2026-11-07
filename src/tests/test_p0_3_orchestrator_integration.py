"""
test_p0_3_orchestrator_integration.py - P0.3 ModelExecutionAdapter Orchestrator Integration Tests.

Validates:
1. Production orchestrator invokes ModelExecutionAdapter without requiring custom executor.
2. Desktop Bridge (_handle_prompt) reaches the model-backed executor in 'agent' and 'plan' modes.
3. A fake provider with authentic usage receipts generates and writes code through WorkspaceMutationBroker.
4. Missing usage receipts fail closed with MissingUsageReceiptError and prevent file mutation.
5. Unknown model pricing fails closed with UnknownModelPricingError before provider invocation.
6. Budget exhaustion fails closed with BudgetExhaustedError before provider invocation.
7. Placeholder 'return OK' executor cannot silently run in production mode.
8. Deterministic execution is retained strictly for explicitly configured test/offline mode.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import src.orchestration.model_adapter as ma
from src.bridge.__main__ import BridgeServer
from src.finops.pricing_registry import PricingRegistry
from src.orchestration.finops_governor import (
    BudgetExhaustedError,
    OrchestrationFinOpsGovernor,
)
from src.orchestration.model_adapter import (
    MissingUsageReceiptError,
    ModelExecutionAdapter,
    UnknownModelPricingError,
)
from src.orchestration.models import ExecutionLimits, TaskVerdict
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
from src.workspace.mutation_broker import WorkspaceMutationBroker


class TestP03OrchestratorIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="crusor_p0_3_integration_")
        self.ws = Path(self.tmp).resolve()

        # Initialize minimal repo skeleton in workspace so repository discovery succeeds
        (self.ws / "src").mkdir(parents=True, exist_ok=True)
        (self.ws / "tests").mkdir(parents=True, exist_ok=True)
        (self.ws / "package.json").write_text('{"name": "test-project", "version": "1.0.0"}', encoding="utf-8")
        (self.ws / "src" / "index.py").write_text("# Initial source file\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_production_orchestrator_invokes_model_adapter(self) -> None:
        """Verify production orchestrator invokes ModelExecutionAdapter and writes code via mutation broker."""
        orch = EngineeringExecutionOrchestrator(
            workspace_root=str(self.ws),
            tenant_id="test_tenant",
            limits=ExecutionLimits(max_cost_inr=100.0),
            mock_mode=False,
            provider="groq",
            model="qwen/qwen3.6-27b",
        )

        recorded_prompts: List[str] = []

        class FakeLLM:
            def invoke(self, prompt: str, **kwargs):
                recorded_prompts.append(prompt)
                return type(
                    "Resp",
                    (),
                    {
                        "content": "```python\nclass UserAuthService:\n    def authenticate(self, user, token):\n        return True\n```",
                        "usage_metadata": {
                            "input_tokens": 150,
                            "output_tokens": 60,
                            "total_tokens": 210,
                        },
                    },
                )()

        orig_get_llm = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: FakeLLM()

        try:
            delivery = orch.run_task(
                task_prompt="Implement user authentication service in src/auth_service.py",
                task_id="task_p0_3_real_model",
            )

            # 1. Assert ModelExecutionAdapter was invoked with authentic context
            self.assertGreater(len(recorded_prompts), 0)
            self.assertIn("Task Node:", recorded_prompts[0])

            # 2. Assert code landed on disk via WorkspaceMutationBroker
            self.assertGreater(len(delivery.files_changed), 0, "Target files must be changed after model execution")
            for changed in delivery.files_changed:
                target_file = self.ws / changed
                self.assertTrue(target_file.exists(), f"Target file {changed} must exist after model execution")
                file_content = target_file.read_text(encoding="utf-8")
                self.assertIn("class UserAuthService", file_content)

            # 3. Assert mutation broker recorded the transaction
            records = orch.broker.ledger.get_records("task_p0_3_real_model")
            self.assertGreater(len(records), 0, "Broker ledger must record file mutation")
            for r in records:
                self.assertTrue((self.ws / r.file_path).exists())

            # 4. Assert non-zero FinOps accounting
            self.assertGreater(delivery.cost_inr, 0.0, "Cost in INR must be non-zero for real model execution")
            self.assertGreater(delivery.cost_usd, 0.0, "Cost in USD must be non-zero for real model execution")
            self.assertGreaterEqual(delivery.token_usage.get("tokens", 0), 210)

        finally:
            ma.get_llm = orig_get_llm

    def test_desktop_bridge_reaches_model_backed_executor(self) -> None:
        """Verify the production desktop bridge entry point (_run_turn) reaches ModelExecutionAdapter."""
        server = BridgeServer()
        sid = "desktop_session_p0_3"

        # Explicitly configure ModelExecutionAdapter with mock_mode=False
        adapter = ModelExecutionAdapter(
            workspace_root=str(self.ws),
            tenant_id="desktop_tenant",
            mock_mode=False,
            provider="groq",
            model="qwen/qwen3.6-27b",
        )

        server._sessions[sid] = {
            "session_id": sid,
            "workspace": str(self.ws),
            "tenant_id": "desktop_tenant",
            "mode": "agent",
            "model_adapter": adapter,
            "mock_mode": False,
        }
        server.model_adapter = adapter

        emitted_frames: List[Dict[str, Any]] = []

        def capture_emit(frame: Dict[str, Any]) -> None:
            emitted_frames.append(frame)

        server.emit = capture_emit  # type: ignore

        invoke_prompts: List[str] = []

        class FakeBridgeLLM:
            def invoke(self, prompt: str, **kwargs):
                invoke_prompts.append(prompt)
                return type(
                    "Resp",
                    (),
                    {
                        "content": "```python\nclass PaymentGateway:\n    def process_charge(self, amount):\n        return {'status': 'CHARGED'}\n```",
                        "usage_metadata": {
                            "input_tokens": 180,
                            "output_tokens": 75,
                            "total_tokens": 255,
                        },
                    },
                )()

        orig_get_llm = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: FakeBridgeLLM()

        # Temporarily configure environment to route to groq / qwen3.6-27b
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "groq",
            "LLM_MODEL": "qwen/qwen3.6-27b",
            "CRUSORAI_TEST_MODE": "0",
            "CRUSORAI_TASK_BUDGET_INR": "50.0",
        }):
            try:
                # Invoke the actual desktop entry point
                server._run_turn(
                    sid,
                    "Implement payment processor in src/payment_gateway.py",
                    str(self.ws),
                    mode="agent",
                )

                # 1. Assert protocol frames emitted
                types = [f.get("type") for f in emitted_frames]
                self.assertIn("turn_lifecycle", types)
                self.assertIn("plan_updated", types)
                self.assertIn("verification_updated", types)
                self.assertIn("turn_done", types)

                # 2. Assert FakeBridgeLLM was demonstrably called (fails if deterministic mock is used)
                self.assertGreater(len(invoke_prompts), 0, "Fake provider invoke() must be demonstrably called")
                self.assertIn("Task Node:", invoke_prompts[0])

                # 3. Assert target file was created with model generated content
                py_files = [f for f in self.ws.rglob("*.py") if f.name != "index.py"]
                self.assertGreater(len(py_files), 0, "Model generated files must land on disk")
                found_code = any("PaymentGateway" in f.read_text(encoding="utf-8") for f in py_files)
                self.assertTrue(found_code, "Generated file must contain PaymentGateway class")

                # 4. Assert mutations were written through WorkspaceMutationBroker
                orch = getattr(server, "_last_orchestrator", None)
                self.assertIsNotNone(orch, "Bridge must execute through EngineeringExecutionOrchestrator")
                all_records = [r for t_records in orch.broker.ledger._records.values() for r in t_records]
                self.assertGreater(len(all_records), 0, "WorkspaceMutationBroker ledger must record file mutations")
                for r in all_records:
                    self.assertTrue((self.ws / r.file_path).exists(), f"File {r.file_path} from broker must exist on disk")

                # 5. Assert non-zero FinOps accounting and token usage
                delivery = getattr(server, "_last_delivery", None)
                self.assertIsNotNone(delivery, "Bridge execution must produce a DeliveryContract")
                self.assertGreater(delivery.cost_inr, 0.0, "Cost in INR must be non-zero for real model execution")
                self.assertGreater(delivery.cost_usd, 0.0, "Cost in USD must be non-zero for real model execution")
                # The planner creates one implementation node per approved
                # requirement, so a task can dispatch the model more than once
                # (all three requirements here target the same file). The
                # recording must equal the provider receipt for every actual
                # dispatch, not a number that assumes a single node.
                per_call_tokens = 180 + 75  # FakeBridgeLLM usage_metadata
                self.assertGreater(len(invoke_prompts), 0)
                self.assertEqual(
                    delivery.token_usage.get("tokens"),
                    per_call_tokens * len(invoke_prompts),
                    "Recorded tokens must equal the provider receipt for every dispatched call",
                )
                self.assertGreaterEqual(delivery.token_usage.get("tokens", 0), per_call_tokens)

                # 6. Assert independent verification passed
                self.assertTrue(delivery.independently_verified, "Delivery must pass independent verification")
                self.assertEqual(delivery.verdict, TaskVerdict.COMPLETED)

            finally:
                ma.get_llm = orig_get_llm

    def test_missing_usage_receipts_prevent_file_mutation(self) -> None:
        """Verify provider responses without token usage receipts fail closed and prevent file mutation."""
        orch = EngineeringExecutionOrchestrator(
            workspace_root=str(self.ws),
            tenant_id="test_tenant",
            limits=ExecutionLimits(max_cost_inr=100.0),
            mock_mode=False,
            provider="groq",
            model="qwen/qwen3.6-27b",
        )

        class MissingReceiptLLM:
            def invoke(self, prompt: str, **kwargs):
                # Returns content but NO usage_metadata, response_metadata, or usage attribute
                return type("Resp", (), {"content": "```python\ndef unmetered_fn(): pass\n```"})()

        orig_get_llm = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: MissingReceiptLLM()

        try:
            with self.assertRaises(MissingUsageReceiptError):
                orch.run_task(
                    task_prompt="Create unmetered file in src/unmetered.py",
                    task_id="task_missing_receipt",
                )

            # Assert file was NOT mutated on disk
            target_file = self.ws / "src" / "unmetered.py"
            self.assertFalse(target_file.exists(), "File mutation must be blocked when usage receipts are missing")

            # Assert ledger has zero records
            records = orch.broker.ledger.get_records("task_missing_receipt")
            self.assertEqual(len(records), 0)

        finally:
            ma.get_llm = orig_get_llm

    def test_unknown_pricing_prevents_provider_invocation(self) -> None:
        """Verify that models without rate card fail closed before calling LLM provider."""
        orch = EngineeringExecutionOrchestrator(
            workspace_root=str(self.ws),
            tenant_id="test_tenant",
            mock_mode=False,
            provider="custom",
            model="unknown-unregistered-model-xyz",
        )

        invoke_calls: List[str] = []

        class GuardedLLM:
            def invoke(self, prompt: str):
                invoke_calls.append(prompt)
                return type("Resp", (), {"content": "code"})()

        orig_get_llm = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: GuardedLLM()

        try:
            with self.assertRaises(UnknownModelPricingError):
                orch.run_task(
                    task_prompt="Create service in src/unknown_pricing.py",
                    task_id="task_unknown_pricing",
                )

            # Assert LLM was never called
            self.assertEqual(len(invoke_calls), 0, "LLM provider must not be invoked if pricing is unknown")
            self.assertFalse((self.ws / "src" / "unknown_pricing.py").exists())

        finally:
            ma.get_llm = orig_get_llm

    def test_budget_exhaustion_prevents_provider_invocation(self) -> None:
        """Verify that zero/exhausted budget fails closed before LLM provider invocation."""
        orch = EngineeringExecutionOrchestrator(
            workspace_root=str(self.ws),
            tenant_id="test_tenant",
            limits=ExecutionLimits(max_cost_inr=0.00),
            mock_mode=False,
            provider="groq",
            model="qwen/qwen3.6-27b",
        )

        invoke_calls: List[str] = []

        class BudgetLLM:
            def invoke(self, prompt: str):
                invoke_calls.append(prompt)
                return type("Resp", (), {"content": "code"})()

        orig_get_llm = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: BudgetLLM()

        try:
            with self.assertRaises(BudgetExhaustedError):
                orch.run_task(
                    task_prompt="Create service in src/budget_blocked.py",
                    task_id="task_budget_exhausted",
                )

            # Assert LLM was never called
            self.assertEqual(len(invoke_calls), 0, "LLM provider must not be invoked when budget is exhausted")
            self.assertFalse((self.ws / "src" / "budget_blocked.py").exists())

        finally:
            ma.get_llm = orig_get_llm

    def test_placeholder_executor_cannot_silently_run_in_production_mode(self) -> None:
        """Verify that placeholder 'return OK' handlers cannot run in production mode."""
        # 1. Attempting to run in production mode without active provider keys fails closed
        orch = EngineeringExecutionOrchestrator(
            workspace_root=str(self.ws),
            tenant_id="test_tenant",
            mock_mode=False,
            provider="nonexistent_provider",
            model="qwen/qwen3.6-27b",
        )

        # Clear active keys
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "GEMINI_API_KEY": "",
            "GROQ_API_KEY": "",
            "CUSTOM_API_KEY": "",
            "NVIDIA_API_KEY": "",
            "CRUSORAI_TEST_MODE": "0",
        }):
            # Must raise error, NEVER silently generate placeholder code
            with self.assertRaises((RuntimeError, ValueError)):
                orch.run_task(
                    task_prompt="Create service in src/prod_service.py",
                    task_id="task_prod_no_key",
                )

        # 2. Even if a generator produces a placeholder 'return OK' handler, it is strictly rejected
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=True)
        node = type("Node", (), {
            "node_id": "test_node",
            "description": "test placeholder",
            "target_files": ["src/bad_placeholder.py"],
            "related_requirement_ids": [],
            "risk_level": "LOW",
        })()

        test_finops = OrchestrationFinOpsGovernor("task_test_placeholder", budget_inr=100.0)
        with self.assertRaises(ValueError) as ctx:
            adapter.execute_node(
                task_id="task_test_placeholder",
                node=node,
                specification=type("Spec", (), {})(),
                blueprint=type("BP", (), {})(),
                project_knowledge=type("PK", (), {})(),
                impl_engine=orch.impl_engine,
                finops=test_finops,
                reasoning_loop=type("RL", (), {"record_action": lambda *a, **k: None})(),
                custom_code_generator=lambda n, t: "def handle_node():\n    # Production implementation placeholder\n    return 'OK'\n",
            )
        self.assertIn("Placeholder handler generation is strictly prohibited", str(ctx.exception))

    def test_deterministic_execution_retained_in_mock_mode(self) -> None:
        """Verify that explicitly configured mock mode retains deterministic offline execution."""
        orch = EngineeringExecutionOrchestrator(
            workspace_root=str(self.ws),
            tenant_id="test_tenant",
            mock_mode=True,
        )

        delivery = orch.run_task(
            task_prompt="Create utility module in src/utils.py",
            task_id="task_mock_deterministic",
        )

        # In mock mode, deterministic code is generated without provider API calls
        self.assertGreater(len(delivery.files_changed), 0, "Deterministic execution must mutate files")
        for changed in delivery.files_changed:
            target_file = self.ws / changed
            self.assertTrue(target_file.exists())
            self.assertIn("Service", target_file.read_text(encoding="utf-8"))
        self.assertEqual(delivery.cost_inr, 0.0)


if __name__ == "__main__":
    unittest.main()
