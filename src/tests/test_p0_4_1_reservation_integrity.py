"""
test_p0_4_1_reservation_integrity.py - P0.4.1 reservation integrity & token ceiling tests.

Exercises the REAL ModelExecutionAdapter path (not a bypass) plus the canonical
BudgetGovernor two-phase lifecycle. No network/paid provider calls are made:
every LLM client is an in-process fake monkeypatched onto ``ma.get_llm``.

Covers:
1.  Exact provider output-token ceiling reaches the invocation kwargs.
2.  OpenAI-compatible wire payload carries the ceiling (max_completion_tokens).
3.  A client that cannot enforce the ceiling is blocked BEFORE dispatch.
4.  No unbounded retry after TypeError; one metered dispatch == one request,
    and an in-invocation TypeError retains an uncertain hold.
5.  Canonical reservation denial blocks provider invocation.
6.  The exact canonical reservation ID is used for commit and release.
7.  Durable persistence failure blocks provider invocation.
8.  Timeout after dispatch produces an uncertain reservation holding funds.
9.  Uncertain reservations survive a restart and cannot become available budget.
10. Duplicate settlement does not double-charge.
11. Concurrent reservations cannot oversubscribe the enforced budget.
"""

from __future__ import annotations

import concurrent.futures
from decimal import Decimal
import shutil
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from langchain_openai import ChatOpenAI

from src.finops.budget_governor import get_budget_governor
from src.finops.pricing_registry import quantize_currency
from src.llm.factory import TurnCancelledError
import src.orchestration.model_adapter as ma
from src.orchestration.finops_governor import (
    BudgetExhaustedError,
    FinancialPersistenceError,
    OrchestrationFinOpsGovernor,
)
from src.orchestration.implementation_engine import ControlledImplementationEngine
from src.orchestration.loop import BoundedAutonomousReasoningLoop
from src.orchestration.model_adapter import (
    ModelExecutionAdapter,
    UnsupportedTokenCeilingError,
    build_output_token_kwargs,
    can_enforce_token_limit,
    is_uncertain_post_dispatch_error,
)
from src.orchestration.models import EngineeringTaskNode
from src.workspace.mutation_broker import WorkspaceMutationBroker


def _response(content: str = "```python\nclass TokenHandler:\n    pass\n```"):
    return type(
        "Resp",
        (),
        {
            "content": content,
            "usage_metadata": {"input_tokens": 120, "output_tokens": 60, "total_tokens": 180},
        },
    )()


def _spec():
    return type("Spec", (), {"spec_id": "SPEC-P041"})()


def _blueprint():
    return type("Blueprint", (), {"architecture_style": "MODULAR"})()


def _knowledge():
    return type("Knowledge", (), {"frameworks": []})()


class TestP041ReservationIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="crusor_p0_4_1_")
        self.ws = Path(self.tmp).resolve()
        self.storage_dir = self.ws / ".crusorai" / "finops"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.broker = WorkspaceMutationBroker(str(self.ws))
        self.impl_engine = ControlledImplementationEngine(str(self.ws), broker=self.broker)
        self.loop = BoundedAutonomousReasoningLoop()

        # Unique scope per test: the canonical governor is process-global.
        self.scope_id = f"p0_4_1_{uuid.uuid4().hex[:10]}"
        self.finops = OrchestrationFinOpsGovernor(
            self.scope_id,
            budget_inr=100.0,
            token_budget=50000,
            storage_dir=str(self.storage_dir),
            workspace_root=str(self.ws),
        )

        self._orig_get_llm = ma.get_llm

    def tearDown(self) -> None:
        ma.get_llm = self._orig_get_llm
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_node(self, node_id: str = "node_p0_4_1", max_tokens: int = 1500) -> EngineeringTaskNode:
        node = EngineeringTaskNode(
            node_id=node_id,
            description="Create secure token handler",
            objective="Enforce token ceiling",
            target_files=["src/token_handler.py"],
        )
        # The adapter reads an optional per-node ceiling.
        node.max_tokens = max_tokens
        return node

    def _run_node(self, adapter: ModelExecutionAdapter, node: EngineeringTaskNode) -> bool:
        return adapter.execute_node(
            task_id=self.scope_id,
            node=node,
            specification=_spec(),
            blueprint=_blueprint(),
            project_knowledge=_knowledge(),
            impl_engine=self.impl_engine,
            finops=self.finops,
            reasoning_loop=self.loop,
        )

    # ------------------------------------------------------------------
    # 1-2. Token ceiling reaches the provider request
    # ------------------------------------------------------------------
    def test_provider_receives_configured_max_tokens(self) -> None:
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="groq", model="qwen/qwen3.6-27b")
        received = []

        class CapturingLLM:
            def invoke(self, prompt: str, **kwargs):
                received.append(kwargs)
                return _response()

        ma.get_llm = lambda provider=None, model=None: CapturingLLM()

        self.assertTrue(self._run_node(adapter, self._make_node(max_tokens=1850)))

        self.assertEqual(received[0].get("max_tokens"), 1850)
        # Increment 2: the shared model gateway attaches correlation metadata
        # via LangChain's `config` keyword; the wire token ceiling is unchanged.
        self.assertIn("metadata", received[0].get("config", {}))
        self.assertEqual(self.finops.accounting.reserved_inr, 0.0, "Commit must release the hold")

    def test_openai_wire_payload_carries_output_token_ceiling(self) -> None:
        kwargs = build_output_token_kwargs("openai", 321)
        self.assertEqual(kwargs, {"max_tokens": 321})

        client = ChatOpenAI(model="gpt-4o-mini", api_key="sk-test")
        payload = client._get_request_payload("hi", **kwargs)
        self.assertEqual(payload.get("max_completion_tokens"), 321)
        self.assertNotIn("max_tokens", payload)

        # Gemini/Google use GenerationConfig.max_output_tokens.
        self.assertEqual(build_output_token_kwargs("gemini", 99), {"max_output_tokens": 99})
        self.assertEqual(build_output_token_kwargs("unknown-provider", 99), {})

    def test_unsupported_token_ceiling_blocks_dispatch(self) -> None:
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="groq", model="qwen/qwen3.6-27b")
        dispatch_attempted = []

        class IncompatibleLLM:
            def invoke(self, prompt: str):  # no **kwargs, no max_tokens
                dispatch_attempted.append(True)
                return _response()

        self.assertFalse(can_enforce_token_limit(IncompatibleLLM(), provider="groq", max_output_tokens=1500))
        ma.get_llm = lambda provider=None, model=None: IncompatibleLLM()

        with self.assertRaises(UnsupportedTokenCeilingError):
            self._run_node(adapter, self._make_node())

        self.assertEqual(dispatch_attempted, [], "Provider must not be invoked without an enforceable ceiling")
        self.assertEqual(self.finops.accounting.reserved_inr, 0.0)
        self.assertEqual(self.finops.accounting.reserved_tokens, 0)

    def test_no_unbounded_retry_after_type_error(self) -> None:
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="groq", model="qwen/qwen3.6-27b")

        class RetryingProxy:
            def __init__(self) -> None:
                self._max_attempts = 5
                self.calls = 0

            def invoke(self, prompt: str, **kwargs):
                self.calls += 1
                if self.calls < self._max_attempts:
                    return self.invoke(prompt, **kwargs)
                raise TypeError("simulated signature mismatch")

        proxy = RetryingProxy()
        ma.get_llm = lambda provider=None, model=None: proxy

        with self.assertRaises(TypeError):
            self._run_node(adapter, self._make_node())

        self.assertEqual(proxy._max_attempts, 1, "Adapter must force a single metered dispatch")
        self.assertEqual(proxy.calls, 1, "TypeError must not trigger a retry without the token limit")
        self.assertGreater(
            self.finops.accounting.reserved_inr,
            0.0,
            "A TypeError raised inside invoke is ambiguous and must retain the hold",
        )
        self.assertEqual(len(self.finops._uncertain_reservations), 1)

    # ------------------------------------------------------------------
    # 5-7. Canonical reservation + persistence fail closed before dispatch
    # ------------------------------------------------------------------
    def test_canonical_denial_prevents_provider_invocation(self) -> None:
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="groq", model="qwen/qwen3.6-27b")
        invoked = []

        class TrackingLLM:
            def invoke(self, prompt: str, **kwargs):
                invoked.append(True)
                return _response()

        ma.get_llm = lambda provider=None, model=None: TrackingLLM()

        with patch.object(
            get_budget_governor(),
            "reserve_budget",
            return_value=(False, "", "canonical hard limit breached"),
        ):
            with self.assertRaises(BudgetExhaustedError):
                self._run_node(adapter, self._make_node())

        self.assertEqual(invoked, [], "Provider must never run when the canonical reservation is denied")
        self.assertEqual(self.finops.accounting.reserved_inr, 0.0)
        self.assertEqual(len(self.finops._active_reservations), 0)

    def test_exact_canonical_id_used_for_commit_and_release(self) -> None:
        gov = self.finops

        res_id = gov.reserve(estimated_tokens=1000, estimated_cost_inr=2.00, estimated_cost_usd=0.024)
        canonical_id = gov._active_reservations[res_id].canonical_reservation_id
        self.assertTrue(canonical_id, "Canonical reservation ID must be captured")

        canonical = get_budget_governor()
        with patch.object(canonical, "commit_reservation", wraps=canonical.commit_reservation) as spy:
            gov.commit_reservation(
                reservation_id=res_id,
                actual_input_tokens=200,
                actual_output_tokens=200,
                actual_cached_tokens=0,
                actual_cost_inr=1.50,
                actual_cost_usd=0.018,
            )
            spy.assert_called_once()
            self.assertEqual(spy.call_args.kwargs["reservation_id"], canonical_id)
            self.assertEqual(spy.call_args.kwargs["scope_key"], self.scope_id)

        res_id_2 = gov.reserve(estimated_tokens=1000, estimated_cost_inr=2.00, estimated_cost_usd=0.024)
        canonical_id_2 = gov._active_reservations[res_id_2].canonical_reservation_id
        self.assertTrue(canonical_id_2)

        with patch.object(canonical, "release_reservation", wraps=canonical.release_reservation) as spy_rel:
            gov.release_reservation(res_id_2, reason="test_release")
            spy_rel.assert_called_once()
            self.assertEqual(spy_rel.call_args.kwargs["reservation_id"], canonical_id_2)
            self.assertEqual(spy_rel.call_args.kwargs["scope_key"], self.scope_id)

        self.assertNotIn(canonical_id_2, canonical.get_scope_state(self.scope_id).active_reservations)

    def test_persistence_failure_prevents_provider_invocation(self) -> None:
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="groq", model="qwen/qwen3.6-27b")
        invoked = []

        class TrackingLLM:
            def invoke(self, prompt: str, **kwargs):
                invoked.append(True)
                return _response()

        ma.get_llm = lambda provider=None, model=None: TrackingLLM()

        with patch.object(self.finops, "_persist_state", side_effect=IOError("durable disk write failed")):
            with self.assertRaises(FinancialPersistenceError):
                self._run_node(adapter, self._make_node())

        self.assertEqual(invoked, [], "Provider must never run when the reservation is not durably recorded")
        self.assertEqual(self.finops.accounting.reserved_inr, 0.0)
        self.assertEqual(len(self.finops._active_reservations), 0)

    # ------------------------------------------------------------------
    # 8-9. Uncertain post-dispatch outcomes
    # ------------------------------------------------------------------
    def test_timeout_after_dispatch_marks_uncertain_and_retains_hold(self) -> None:
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="groq", model="qwen/qwen3.6-27b")

        class TimingOutLLM:
            def invoke(self, prompt: str, **kwargs):
                raise TimeoutError("HTTP read timeout after 180s")

        ma.get_llm = lambda provider=None, model=None: TimingOutLLM()
        self.assertTrue(is_uncertain_post_dispatch_error(TimeoutError("t")))
        self.assertTrue(is_uncertain_post_dispatch_error(TurnCancelledError("cancelled")))
        self.assertTrue(
            is_uncertain_post_dispatch_error(TypeError("bad signature")),
            "A TypeError raised inside invoke does not prove the request was never billed",
        )

        with self.assertRaises(TimeoutError):
            self._run_node(adapter, self._make_node())

        self.assertEqual(len(self.finops._uncertain_reservations), 1)
        uncertain = next(iter(self.finops._uncertain_reservations.values()))
        self.assertEqual(uncertain.status, "uncertain")
        self.assertGreater(self.finops.accounting.reserved_inr, 0.0)
        self.assertGreater(self.finops.accounting.reserved_tokens, 0)

    def test_uncertain_reservations_survive_restart(self) -> None:
        task_id = f"p0_4_1_restart_{uuid.uuid4().hex[:8]}"
        gov1 = OrchestrationFinOpsGovernor(
            task_id, budget_inr=10.00, token_budget=10000, storage_dir=str(self.storage_dir)
        )
        res_id = gov1.reserve(estimated_tokens=1500, estimated_cost_inr=4.00, estimated_cost_usd=0.048)
        gov1.mark_in_flight(res_id)
        gov1.mark_uncertain(res_id, reason="provider_socket_timeout")
        self.assertEqual(gov1.accounting.reserved_inr, 4.00)

        gov2 = OrchestrationFinOpsGovernor(
            task_id, budget_inr=10.00, token_budget=10000, storage_dir=str(self.storage_dir)
        )
        self.assertEqual(gov2.accounting.reserved_inr, 4.00, "Uncertain hold must survive restart")
        self.assertIn(res_id, gov2._uncertain_reservations)
        self.assertEqual(gov2._uncertain_reservations[res_id].status, "uncertain")

        with self.assertRaises(BudgetExhaustedError):
            gov2.reserve(estimated_tokens=2000, estimated_cost_inr=7.00, estimated_cost_usd=0.084)

        # Remaining headroom (6.00) is still usable.
        self.assertTrue(gov2.reserve(estimated_tokens=1000, estimated_cost_inr=5.00, estimated_cost_usd=0.060).startswith("res_"))

    # ------------------------------------------------------------------
    # 10-11. Idempotent settlement + concurrency
    # ------------------------------------------------------------------
    def test_duplicate_settlement_does_not_double_charge(self) -> None:
        gov = self.finops
        res_id = gov.reserve(estimated_tokens=1000, estimated_cost_inr=2.00, estimated_cost_usd=0.024)

        gov.commit_reservation(
            reservation_id=res_id,
            actual_input_tokens=100,
            actual_output_tokens=100,
            actual_cached_tokens=0,
            actual_cost_inr=1.25,
            actual_cost_usd=0.015,
        )
        spent_after_first = gov.accounting.spent_inr
        canonical_state = get_budget_governor().get_scope_state(self.scope_id)
        canonical_after_first = canonical_state.committed_spend_usd

        # Replayed settlement must be a no-op, not a second charge.
        gov.commit_reservation(
            reservation_id=res_id,
            actual_input_tokens=100,
            actual_output_tokens=100,
            actual_cached_tokens=0,
            actual_cost_inr=1.25,
            actual_cost_usd=0.015,
        )
        gov.release_reservation(res_id, reason="duplicate_release_after_commit")

        self.assertEqual(gov.accounting.spent_inr, spent_after_first)
        self.assertEqual(gov.accounting.reserved_inr, 0.0)
        self.assertEqual(canonical_state.committed_spend_usd, canonical_after_first)
        self.assertEqual(canonical_after_first, quantize_currency(Decimal("0.015")))

    def test_concurrent_reservations_cannot_oversubscribe_budget(self) -> None:
        task_id = f"p0_4_1_concurrent_{uuid.uuid4().hex[:8]}"
        gov = OrchestrationFinOpsGovernor(
            task_id, budget_inr=10.00, token_budget=50000, storage_dir=str(self.storage_dir)
        )

        successes = []
        rejections = []
        lock = threading.Lock()

        def worker(idx: int) -> None:
            try:
                r_id = gov.reserve(
                    estimated_tokens=1000,
                    estimated_cost_inr=2.00,
                    estimated_cost_usd=0.024,
                    purpose=f"worker_{idx}",
                )
                with lock:
                    successes.append(r_id)
            except BudgetExhaustedError:
                with lock:
                    rejections.append(idx)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(10)]
            concurrent.futures.wait(futures)

        self.assertEqual(len(successes), 5, "Exactly 5 x INR 2.00 fit in the INR 10.00 budget")
        self.assertEqual(len(rejections), 5)
        self.assertEqual(gov.accounting.reserved_inr, 10.00)
        self.assertLessEqual(
            gov.accounting.reserved_inr + gov.accounting.spent_inr,
            gov.accounting.budget_inr,
        )


if __name__ == "__main__":
    unittest.main()
