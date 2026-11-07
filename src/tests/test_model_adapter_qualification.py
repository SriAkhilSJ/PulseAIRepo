"""
test_model_adapter_qualification.py - Phase 12.1.1 Model Execution Qualification Test.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import src.orchestration.model_adapter as ma
from src.orchestration.finops_governor import OrchestrationFinOpsGovernor
from src.orchestration.implementation_engine import ControlledImplementationEngine
from src.orchestration.loop import BoundedAutonomousReasoningLoop
from src.orchestration.model_adapter import ModelExecutionAdapter
from src.orchestration.models import EngineeringTaskNode
from src.workspace.mutation_broker import WorkspaceMutationBroker


class TestModelAdapterQualification(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="crusor_qual_model_")
        self.ws = Path(self.tmp)
        self.broker = WorkspaceMutationBroker(str(self.ws))
        self.impl_engine = ControlledImplementationEngine(str(self.ws), broker=self.broker)
        self.finops = OrchestrationFinOpsGovernor("qual_task", budget_inr=100.0, token_budget=10000)
        self.loop = BoundedAutonomousReasoningLoop()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fake_provider_prompt_fidelity_and_finops(self) -> None:
        """Verify prompt context, tool execution, and FinOps recording using fake provider."""
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="groq", model="qwen/qwen3.6-27b")

        recorded_prompts = []

        class FakeLLM:
            def invoke(self, prompt: str, **kwargs):
                recorded_prompts.append(prompt)
                resp = type(
                    "Resp",
                    (),
                    {
                        "content": "```python\nclass QualifiedService:\n    def run(self):\n        return True\n```",
                        "usage_metadata": {
                            "input_tokens": 120,
                            "output_tokens": 45,
                            "total_tokens": 165,
                        },
                    },
                )()
                return resp

        orig_get_llm = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: FakeLLM()

        try:
            node = EngineeringTaskNode(
                node_id="qual_node_1",
                description="Implement user billing validator",
                objective="Create user billing validation logic",
                target_files=["billing/validator.py"],
                related_requirement_ids=["REQ-BILLING-001", "REQ-FIN-002"],
            )

            spec = type("Spec", (), {"spec_id": "SPEC-001"})()
            blueprint = type("Blueprint", (), {"architecture_style": "MICROSERVICES"})()
            knowledge = type("Knowledge", (), {"frameworks": []})()

            res = adapter.execute_node(
                task_id="qual_task",
                node=node,
                specification=spec,
                blueprint=blueprint,
                project_knowledge=knowledge,
                impl_engine=self.impl_engine,
                finops=self.finops,
                reasoning_loop=self.loop,
            )

            self.assertTrue(res)
            self.assertEqual(len(recorded_prompts), 1)
            prompt = recorded_prompts[0]

            # Assert context delivery
            self.assertIn("qual_node_1", prompt)
            self.assertIn("REQ-BILLING-001", prompt)
            self.assertIn("REQ-FIN-002", prompt)
            self.assertIn("billing/validator.py", prompt)

            # Assert mutation landed on disk via broker
            target = self.ws / "billing" / "validator.py"
            self.assertTrue(target.exists())
            self.assertIn("class QualifiedService", target.read_text(encoding="utf-8"))

            # Assert ledger recorded mutation
            records = self.broker.ledger.get_records("qual_task")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].file_path, "billing/validator.py")

            # Assert FinOps tracked tokens and non-zero costs
            self.assertEqual(self.finops.accounting.tokens_consumed, 165)
            self.assertEqual(self.finops.accounting.input_tokens, 120)
            self.assertEqual(self.finops.accounting.output_tokens, 45)
            self.assertGreater(self.finops.accounting.spent_inr, 0.0)
            self.assertGreater(self.finops.accounting.spent_usd, 0.0)

        finally:
            ma.get_llm = orig_get_llm

    def test_missing_usage_receipt_fails_closed(self) -> None:
        """Verify that provider responses without token usage receipts fail closed."""
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="groq", model="qwen/qwen3.6-27b")

        class MissingUsageLLM:
            def invoke(self, prompt: str, **kwargs):
                # Returns response with content but NO usage_metadata or usage receipts
                return type("Resp", (), {"content": "```python\ndef run(): pass\n```"})()

        orig_get_llm = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: MissingUsageLLM()

        try:
            node = EngineeringTaskNode(
                node_id="node_missing_usage",
                description="Node with missing usage receipt",
                objective="Fail closed on missing usage",
                target_files=["pkg/unmetered.py"],
            )
            spec = type("Spec", (), {"spec_id": "SPEC-001"})()
            blueprint = type("Blueprint", (), {"architecture_style": "MODULAR"})()
            knowledge = type("Knowledge", (), {"frameworks": []})()

            with self.assertRaises(ma.MissingUsageReceiptError):
                adapter.execute_node(
                    task_id="qual_task",
                    node=node,
                    specification=spec,
                    blueprint=blueprint,
                    project_knowledge=knowledge,
                    impl_engine=self.impl_engine,
                    finops=self.finops,
                    reasoning_loop=self.loop,
                )
            # Mutation must be blocked
            self.assertFalse((self.ws / "pkg" / "unmetered.py").exists())
            # Spent cost must remain zero
            self.assertEqual(self.finops.accounting.spent_inr, 0.0)
        finally:
            ma.get_llm = orig_get_llm

    def test_unknown_pricing_fails_closed(self) -> None:
        """Verify that models with unknown pricing fail closed before unmetered execution."""
        adapter = ModelExecutionAdapter(
            str(self.ws),
            mock_mode=False,
            provider="custom",
            model="unregistered/unknown-model-xyz",
        )

        recorded = []

        class DummyLLM:
            def invoke(self, prompt: str, **kwargs):
                recorded.append(prompt)
                return type("Resp", (), {"content": "code"})()

        orig_get_llm = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: DummyLLM()

        try:
            node = EngineeringTaskNode(
                node_id="node_unknown_model",
                description="Node with unknown model pricing",
                objective="Fail closed on unknown rate card",
                target_files=["pkg/unknown_rate.py"],
            )
            spec = type("Spec", (), {"spec_id": "SPEC-001"})()
            blueprint = type("Blueprint", (), {"architecture_style": "MODULAR"})()
            knowledge = type("Knowledge", (), {"frameworks": []})()

            with self.assertRaises(ma.UnknownModelPricingError):
                adapter.execute_node(
                    task_id="qual_task",
                    node=node,
                    specification=spec,
                    blueprint=blueprint,
                    project_knowledge=knowledge,
                    impl_engine=self.impl_engine,
                    finops=self.finops,
                    reasoning_loop=self.loop,
                )
            # LLM must not have been invoked
            self.assertEqual(len(recorded), 0)
            self.assertFalse((self.ws / "pkg" / "unknown_rate.py").exists())
        finally:
            ma.get_llm = orig_get_llm

    def test_budget_exhaustion_blocks_execution(self) -> None:
        """Verify that pre-call budget checks block execution when budget is exhausted."""
        exhausted_finops = OrchestrationFinOpsGovernor("budget_test", budget_inr=0.00, token_budget=10000)
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="groq", model="qwen/qwen3.6-27b")

        recorded = []

        class DummyLLM:
            def invoke(self, prompt: str, **kwargs):
                recorded.append(prompt)
                return type("Resp", (), {"content": "code"})()

        orig_get_llm = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: DummyLLM()

        try:
            node = EngineeringTaskNode(
                node_id="node_budget_exhausted",
                description="Node exceeding budget",
                objective="Stop execution on budget exhaustion",
                target_files=["pkg/budget_blocked.py"],
            )
            spec = type("Spec", (), {"spec_id": "SPEC-001"})()
            blueprint = type("Blueprint", (), {"architecture_style": "MODULAR"})()
            knowledge = type("Knowledge", (), {"frameworks": []})()

            with self.assertRaises(ma.BudgetExhaustedError):
                adapter.execute_node(
                    task_id="budget_test",
                    node=node,
                    specification=spec,
                    blueprint=blueprint,
                    project_knowledge=knowledge,
                    impl_engine=self.impl_engine,
                    finops=exhausted_finops,
                    reasoning_loop=self.loop,
                )
            # LLM must never be called
            self.assertEqual(len(recorded), 0)
            self.assertFalse((self.ws / "pkg" / "budget_blocked.py").exists())
        finally:
            ma.get_llm = orig_get_llm

    def test_provider_failure_propagation(self) -> None:
        """Verify that model provider failures fail closed and propagate correctly."""
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="groq", model="qwen/qwen3.6-27b")

        class FailingLLM:
            def invoke(self, prompt: str, **kwargs):
                raise ConnectionError("Upstream Model Provider 504 Gateway Timeout")

        orig_get_llm = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: FailingLLM()

        try:
            node = EngineeringTaskNode(
                node_id="qual_node_fail",
                description="Failing node",
                objective="Fail operation intentionally",
                target_files=["fail.py"],
            )
            spec = type("Spec", (), {"spec_id": "SPEC-001"})()
            blueprint = type("Blueprint", (), {"architecture_style": "MODULAR"})()
            knowledge = type("Knowledge", (), {"frameworks": []})()

            with self.assertRaises(ConnectionError) as ctx:
                adapter.execute_node(
                    task_id="qual_task",
                    node=node,
                    specification=spec,
                    blueprint=blueprint,
                    project_knowledge=knowledge,
                    impl_engine=self.impl_engine,
                    finops=self.finops,
                    reasoning_loop=self.loop,
                )
            self.assertIn("504", str(ctx.exception))
            # Disk must remain untouched on failure
            self.assertFalse((self.ws / "fail.py").exists())
        finally:
            ma.get_llm = orig_get_llm
