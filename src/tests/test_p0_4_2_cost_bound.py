"""
test_p0_4_2_cost_bound.py - P0.4.2 input-token upper bound & error classification.

The adapter must reserve a defensible UPPER BOUND for the exact prompt it is
about to send, not an optimistic ``chars // 3`` estimate. These tests exercise
the real ``ModelExecutionAdapter`` and ``OrchestrationFinOpsGovernor`` paths
with in-process fake providers only: no network or paid provider calls are
made.

Covers:
A. Prompt token bound
   1. Long source-code prompts.
   2. Unicode / multilingual text.
   3. Emoji and JSON-special characters.
   4. Very short prompts.
   5. Unknown-model fallback is a byte bound, never a char ratio.
   6. Large prompts close to the configured budget.
   7. Usage receipts exceeding the calculated input-token bound breach.
B. Invocation outcome classification
   8. Structured HTTP 4xx rejections release the hold.
   9. Text-only "400" strings, TypeErrors, 5xx and 408 retain an uncertain hold.
  10. Errors raised before dispatch release directly.
"""

from __future__ import annotations

from decimal import Decimal
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import src.orchestration.model_adapter as ma
from src.finops.pricing_registry import (
    ModelPricingMetadata,
    ModelPricingRegistry,
    PricingRegistry,
    VerificationStatus,
)
from src.orchestration.finops_governor import (
    BudgetExhaustedError,
    OrchestrationFinOpsGovernor,
)
from src.orchestration.implementation_engine import ControlledImplementationEngine
from src.orchestration.loop import BoundedAutonomousReasoningLoop
from src.orchestration.model_adapter import (
    ModelExecutionAdapter,
    PROMPT_OVERHEAD_TOKENS_PER_MESSAGE,
    PROMPT_OVERHEAD_TOKENS_PER_REQUEST,
    _provider_status_code,
    calculate_max_request_cost,
    estimate_prompt_token_upper_bound,
    is_uncertain_post_dispatch_error,
)
from src.orchestration.models import EngineeringTaskNode
from src.workspace.mutation_broker import WorkspaceMutationBroker

PROVIDER = "groq"
MODEL = "qwen/qwen3.6-27b"

_PROMPT_OVERHEAD = PROMPT_OVERHEAD_TOKENS_PER_MESSAGE + PROMPT_OVERHEAD_TOKENS_PER_REQUEST


def _response(
    content: str = "```python\nclass CostBoundService:\n    pass\n```",
    input_tokens: int = 100,
    output_tokens: int = 50,
):
    return type(
        "Resp",
        (),
        {
            "content": content,
            "usage_metadata": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        },
    )()


class _HttpError(Exception):
    """Fake provider error with documented HTTP status evidence."""

    def __init__(self, status_code: int, message: str = "provider rejection") -> None:
        super().__init__(message)
        self.status_code = status_code


class TestP042CostBound(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="crusor_p0_4_2_")
        self.ws = Path(self.tmp).resolve()
        self.storage_dir = self.ws / ".crusorai" / "finops"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.broker = WorkspaceMutationBroker(str(self.ws))
        self.impl_engine = ControlledImplementationEngine(str(self.ws), broker=self.broker)
        self.loop = BoundedAutonomousReasoningLoop()

        self._orig_get_llm = ma.get_llm

    def tearDown(self) -> None:
        ma.get_llm = self._orig_get_llm
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _make_finops(self, budget_inr: float = 100.0, token_budget: int = 150000):
        scope = f"p0_4_2_{uuid.uuid4().hex[:10]}"
        gov = OrchestrationFinOpsGovernor(
            scope,
            budget_inr=budget_inr,
            token_budget=token_budget,
            storage_dir=str(self.storage_dir),
            workspace_root=str(self.ws),
        )
        return scope, gov

    def _make_node(
        self,
        node_id: str = "node_cost_bound",
        target_file: str = "src/cost_bound_target.py",
        max_tokens: int = 512,
    ) -> EngineeringTaskNode:
        node = EngineeringTaskNode(
            node_id=node_id,
            description="Implement a cost-bounded service",
            objective="Verify the prompt token upper bound is reserved",
            target_files=[target_file],
        )
        node.max_tokens = max_tokens
        return node

    def _execute(self, scope: str, gov, adapter, node) -> bool:
        return adapter.execute_node(
            task_id=scope,
            node=node,
            specification=type("Spec", (), {"spec_id": "SPEC-P042"})(),
            blueprint=type("Blueprint", (), {"architecture_style": "MODULAR"})(),
            project_knowledge=type("Knowledge", (), {"frameworks": []})(),
            impl_engine=self.impl_engine,
            finops=gov,
            reasoning_loop=self.loop,
        )

    def _call_direct(
        self,
        gov,
        adapter: ModelExecutionAdapter,
        node: EngineeringTaskNode,
        existing_content: str,
    ) -> str:
        return adapter._call_model_for_implementation(
            node=node,
            target_file=node.target_files[0],
            existing_content=existing_content,
            specification=type("Spec", (), {"spec_id": "SPEC-P042"})(),
            blueprint=type("Blueprint", (), {"architecture_style": "MODULAR"})(),
            project_knowledge=type("Knowledge", (), {"frameworks": []})(),
            finops=gov,
        )

    def _max_cost(self, input_tokens: int, output_tokens: int):
        return calculate_max_request_cost(
            PricingRegistry.get_pricing_registry(),
            model=MODEL,
            provider=PROVIDER,
            input_tokens=input_tokens,
            max_output_tokens=output_tokens,
        )

    # ==================================================================
    # A. Prompt token upper bound
    # ==================================================================
    def test_long_source_code_prompt_is_bounded_above_exact_count(self) -> None:
        lines = []
        for i in range(2500):
            lines.append(
                f'def function_{i}(value: int) -> int:\n'
                f'    """Docstring number {i}."""\n'
                f'    return value + {i}'
            )
        prompt = "\n".join(lines)

        bound = estimate_prompt_token_upper_bound(prompt, provider="openai", model="gpt-4o-mini")

        self.assertIsNotNone(bound.exact_local_tokens, "tiktoken must provide the local exact count")
        self.assertGreaterEqual(
            bound.upper_bound_tokens,
            bound.exact_local_tokens + _PROMPT_OVERHEAD,
            "Bound must cover the exact local count plus template overhead",
        )
        self.assertGreaterEqual(bound.upper_bound_tokens, len(prompt.encode("utf-8")))
        self.assertGreater(
            bound.upper_bound_tokens,
            max(100, len(prompt) // 3),
            "The old chars//3 heuristic must not be the basis of the bound",
        )

    def test_unicode_and_multilingual_text_is_bounded(self) -> None:
        prompt = (
            "源代码 " * 500
            + "مرحبا بالعالم " * 300
            + "नमस्ते दुनिया " * 300
        )
        bound = estimate_prompt_token_upper_bound(prompt, provider="openai", model="gpt-4o-mini")

        raw_bytes = len(prompt.encode("utf-8"))
        self.assertGreaterEqual(
            bound.serialized_bytes,
            raw_bytes,
            "JSON-escaped ASCII serialization must be >= raw UTF-8 bytes",
        )
        self.assertGreaterEqual(bound.upper_bound_tokens, raw_bytes)
        self.assertGreater(bound.upper_bound_tokens, len(prompt))
        self.assertIsNotNone(bound.exact_local_tokens)
        self.assertGreaterEqual(
            bound.upper_bound_tokens, bound.exact_local_tokens + _PROMPT_OVERHEAD
        )

    def test_emoji_and_special_characters_are_bounded(self) -> None:
        prompt = (
            "😀🚀🔥👩‍💻" * 400
            + '\n"double quotes" and \\backslashes\\ and \t tabs \r\n' * 100
        )
        bound = estimate_prompt_token_upper_bound(prompt, provider="openai", model="gpt-4o-mini")

        raw_bytes = len(prompt.encode("utf-8"))
        self.assertGreaterEqual(bound.serialized_bytes, raw_bytes)
        self.assertGreaterEqual(bound.upper_bound_tokens, raw_bytes)
        self.assertIsNotNone(bound.exact_local_tokens)
        self.assertGreaterEqual(
            bound.upper_bound_tokens, bound.exact_local_tokens + _PROMPT_OVERHEAD
        )

    def test_very_short_prompts_keep_the_template_floor(self) -> None:
        for prompt in ("", "x", "hi", "{"):
            bound = estimate_prompt_token_upper_bound(prompt, provider="openai", model="gpt-4o-mini")
            self.assertGreaterEqual(bound.upper_bound_tokens, _PROMPT_OVERHEAD)
            if bound.exact_local_tokens is not None:
                self.assertGreaterEqual(
                    bound.upper_bound_tokens, bound.exact_local_tokens + _PROMPT_OVERHEAD
                )

    def test_unknown_model_uses_byte_bound_not_character_ratio(self) -> None:
        prompt = "世界" * 1000
        bound = estimate_prompt_token_upper_bound(prompt, provider=PROVIDER, model=MODEL)

        self.assertIsNone(bound.exact_local_tokens, "Qwen has no native tiktoken encoding")
        self.assertEqual(bound.method, "serialized_utf8_bytes+chat_template_overhead")
        self.assertGreaterEqual(bound.upper_bound_tokens, len(prompt.encode("utf-8")))
        self.assertGreater(bound.upper_bound_tokens, len(prompt))
        self.assertGreater(bound.upper_bound_tokens, max(100, len(prompt) // 3))

    def test_reservation_matches_prompt_bound_and_max_cost(self) -> None:
        scope, gov = self._make_finops(budget_inr=100.0, token_budget=150000)
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider=PROVIDER, model=MODEL)
        captured = []

        class CapturingLLM:
            def invoke(self, prompt: str, **kwargs):
                captured.append(prompt)
                return _response(input_tokens=100, output_tokens=50)

        ma.get_llm = lambda provider=None, model=None: CapturingLLM()

        node = self._make_node(max_tokens=512)
        target = self.ws / node.target_files[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def existing_handler():\n    return 'ok'\n" * 80, encoding="utf-8")

        with patch.object(gov, "reserve", wraps=gov.reserve) as reserve_spy:
            self.assertTrue(self._execute(scope, gov, adapter, node))

        self.assertEqual(len(captured), 1)
        bound = estimate_prompt_token_upper_bound(captured[0], provider=PROVIDER, model=MODEL)
        expected_cost = self._max_cost(bound.upper_bound_tokens, 512)

        kwargs = reserve_spy.call_args.kwargs
        self.assertEqual(kwargs["estimated_tokens"], bound.upper_bound_tokens + 512)
        self.assertEqual(kwargs["estimated_cost_inr"], float(expected_cost.cost_inr))
        self.assertEqual(kwargs["estimated_cost_usd"], float(expected_cost.cost_usd))
        self.assertEqual(gov.accounting.reserved_inr, 0.0, "Commit must release the hold")

    def test_max_cost_uses_higher_reasoning_rate_when_applicable(self) -> None:
        registry = ModelPricingRegistry()
        registry.register_model_pricing(
            ModelPricingMetadata(
                provider="testprov",
                model="reasoning-priced-model",
                input_price_per_1m=Decimal("1.00"),
                output_price_per_1m=Decimal("2.00"),
                reasoning_price_per_1m=Decimal("10.00"),
                verification_status=VerificationStatus.VERIFIED,
            )
        )

        cost = calculate_max_request_cost(
            registry,
            model="reasoning-priced-model",
            provider="testprov",
            input_tokens=1000,
            max_output_tokens=1000,
        )

        # Every ceiling token is reserved at the higher reasoning rate, not
        # the cheaper visible-output rate.
        self.assertEqual(cost.input_cost, Decimal("0.001000"))
        self.assertEqual(cost.output_cost, Decimal("0.000000"))
        self.assertEqual(cost.reasoning_cost, Decimal("0.010000"))
        self.assertEqual(cost.cost_usd, Decimal("0.011000"))

    def test_request_rejected_before_dispatch_when_max_cost_cannot_fit(self) -> None:
        scope, gov = self._make_finops(budget_inr=0.000001, token_budget=150000)
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider=PROVIDER, model=MODEL)
        invoked = []

        class TrackingLLM:
            def invoke(self, prompt: str, **kwargs):
                invoked.append(prompt)
                return _response()

        ma.get_llm = lambda provider=None, model=None: TrackingLLM()

        with self.assertRaises(BudgetExhaustedError):
            self._execute(scope, gov, adapter, self._make_node())

        self.assertEqual(invoked, [], "Provider must not be dispatched when max cost cannot fit")
        self.assertEqual(gov.accounting.reserved_inr, 0.0)
        self.assertEqual(len(gov._active_reservations), 0)

    def test_token_budget_rejection_happens_before_dispatch(self) -> None:
        # Enough room for the node-level 800-token precheck, but not for the
        # real prompt bound + output ceiling.
        scope, gov = self._make_finops(budget_inr=100.0, token_budget=2000)
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider=PROVIDER, model=MODEL)
        invoked = []

        class TrackingLLM:
            def invoke(self, prompt: str, **kwargs):
                invoked.append(prompt)
                return _response()

        ma.get_llm = lambda provider=None, model=None: TrackingLLM()

        node = self._make_node(max_tokens=512)
        target = self.ws / node.target_files[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x" * 4000, encoding="utf-8")

        with self.assertRaises(BudgetExhaustedError):
            self._execute(scope, gov, adapter, node)

        self.assertEqual(invoked, [], "Provider must not be dispatched when the token bound cannot fit")
        self.assertEqual(gov.accounting.reserved_inr, 0.0)

    def test_large_prompt_close_to_budget_succeeds_then_one_cent_lower_fails(self) -> None:
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider=PROVIDER, model=MODEL)
        node = self._make_node(max_tokens=512)
        existing_content = "def large_module():\n    return 42\n" * 250
        captured = []

        class CapturingLLM:
            def invoke(self, prompt: str, **kwargs):
                captured.append(prompt)
                return _response(input_tokens=200, output_tokens=100)

        ma.get_llm = lambda provider=None, model=None: CapturingLLM()

        # First pass with generous headroom, only to materialise the exact
        # prompt and therefore the exact upper bound/cost.
        scope_a, gov_a = self._make_finops(budget_inr=100.0, token_budget=150000)
        self._call_direct(gov_a, adapter, node, existing_content)
        prompt = captured[-1]
        bound = estimate_prompt_token_upper_bound(prompt, provider=PROVIDER, model=MODEL)
        max_cost = self._max_cost(bound.upper_bound_tokens, 512)
        self.assertGreater(float(max_cost.cost_inr), 0.0)

        # Exactly enough money and tokens: succeeds.
        scope_b, gov_b = self._make_finops(
            budget_inr=float(max_cost.cost_inr) + 0.001,
            token_budget=bound.upper_bound_tokens + 512,
        )
        result = self._call_direct(gov_b, adapter, node, existing_content)
        self.assertIn("class CostBoundService", result)
        self.assertEqual(gov_b.accounting.reserved_inr, 0.0)

        # Just below the maximum request cost: rejected before dispatch.
        scope_c, gov_c = self._make_finops(
            budget_inr=float(max_cost.cost_inr) - 0.001,
            token_budget=150000,
        )
        calls_before = len(captured)
        with self.assertRaises(BudgetExhaustedError):
            self._call_direct(gov_c, adapter, node, existing_content)
        self.assertEqual(len(captured), calls_before, "A rejected reservation must not dispatch")

    def test_usage_receipt_exceeding_bound_triggers_breach_and_blocks_spend(self) -> None:
        scope, gov = self._make_finops(budget_inr=200.0, token_budget=500000)
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider=PROVIDER, model=MODEL)
        node = self._make_node(max_tokens=512)
        captured = []

        class OverReceiptLLM:
            def invoke(self, prompt: str, **kwargs):
                captured.append(prompt)
                bound = estimate_prompt_token_upper_bound(prompt, provider=PROVIDER, model=MODEL)
                # Provider reports more input tokens than the calculated bound.
                return _response(
                    input_tokens=bound.upper_bound_tokens + 50000,
                    output_tokens=512,
                )

        ma.get_llm = lambda provider=None, model=None: OverReceiptLLM()

        self._call_direct(gov, adapter, node, "def existing():\n    return 1\n" * 40)

        bound = estimate_prompt_token_upper_bound(captured[0], provider=PROVIDER, model=MODEL)
        self.assertGreater(gov.accounting.tokens_consumed, bound.upper_bound_tokens)
        self.assertGreater(gov.accounting.spent_inr, 0.0)
        self.assertTrue(gov.accounting.is_breached, "Receipts above the bound must flag a breach")
        self.assertIn("exceeded reserved maximum", gov.accounting.breach_reason)

        with self.assertRaises(BudgetExhaustedError):
            gov.reserve(estimated_tokens=100, estimated_cost_inr=0.01)

    # ==================================================================
    # B. Invocation outcome classification
    # ==================================================================
    def test_structured_http_rejections_are_confirmed_unbilled(self) -> None:
        for status in (400, 401, 403, 404, 422, 429):
            with self.subTest(status=status):
                exc = _HttpError(status)
                self.assertEqual(_provider_status_code(exc), status)
                self.assertFalse(
                    is_uncertain_post_dispatch_error(exc),
                    f"HTTP {status} is documented rejection evidence and is unbilled",
                )

    def test_ambiguous_post_dispatch_errors_retain_the_hold(self) -> None:
        for exc in (
            TypeError("bad signature inside invoke"),
            ValueError("local validation blew up after invoke started"),
            TimeoutError("read timeout"),
            _HttpError(408, "request timeout"),
            _HttpError(500, "internal server error"),
            _HttpError(503, "service unavailable"),
            ConnectionError("connection reset"),
            Exception("provider said 400 Bad Request"),
        ):
            with self.subTest(exc=repr(exc)):
                self.assertTrue(
                    is_uncertain_post_dispatch_error(exc),
                    f"{type(exc).__name__} does not prove the request was never billed",
                )

    def test_text_only_status_numbers_are_not_status_evidence(self) -> None:
        exc = RuntimeError("upstream returned 429 too many requests")
        self.assertIsNone(_provider_status_code(exc))
        self.assertTrue(is_uncertain_post_dispatch_error(exc))

    def test_structured_4xx_end_to_end_releases_hold(self) -> None:
        scope, gov = self._make_finops(budget_inr=100.0, token_budget=150000)
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider=PROVIDER, model=MODEL)
        calls = []

        class RejectingLLM:
            def invoke(self, prompt: str, **kwargs):
                calls.append(prompt)
                raise _HttpError(400, "invalid request payload")

        ma.get_llm = lambda provider=None, model=None: RejectingLLM()

        with self.assertRaises(_HttpError):
            self._execute(scope, gov, adapter, self._make_node())

        self.assertEqual(len(calls), 1)
        self.assertEqual(gov.accounting.reserved_inr, 0.0)
        self.assertEqual(len(gov._uncertain_reservations), 0)
        self.assertFalse((self.ws / "src" / "cost_bound_target.py").exists())

    def test_type_error_inside_invocation_retains_uncertain_hold(self) -> None:
        scope, gov = self._make_finops(budget_inr=100.0, token_budget=150000)
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider=PROVIDER, model=MODEL)
        calls = []

        class AmbiguousLLM:
            def invoke(self, prompt: str, **kwargs):
                calls.append(prompt)
                raise TypeError("kwargs rejected after dispatch began")

        ma.get_llm = lambda provider=None, model=None: AmbiguousLLM()

        with self.assertRaises(TypeError):
            self._execute(scope, gov, adapter, self._make_node())

        self.assertEqual(len(calls), 1, "No unbounded retry")
        self.assertEqual(len(gov._uncertain_reservations), 1)
        self.assertGreater(gov.accounting.reserved_inr, 0.0)
        self.assertEqual(gov.accounting.spent_inr, 0.0)

    def test_text_only_400_retains_uncertain_hold(self) -> None:
        scope, gov = self._make_finops(budget_inr=100.0, token_budget=150000)
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider=PROVIDER, model=MODEL)

        class TextStatusLLM:
            def invoke(self, prompt: str, **kwargs):
                raise RuntimeError("400 Bad Request (status reported in message only)")

        ma.get_llm = lambda provider=None, model=None: TextStatusLLM()

        with self.assertRaises(RuntimeError):
            self._execute(scope, gov, adapter, self._make_node())

        self.assertEqual(len(gov._uncertain_reservations), 1)
        self.assertGreater(gov.accounting.reserved_inr, 0.0)

    def test_predispatch_client_failure_releases_without_dispatch(self) -> None:
        scope, gov = self._make_finops(budget_inr=100.0, token_budget=150000)
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider=PROVIDER, model=MODEL)
        invoked = []

        def boom(provider=None, model=None):
            raise RuntimeError("provider client stack unavailable")

        ma.get_llm = boom

        with self.assertRaises(RuntimeError):
            self._execute(scope, gov, adapter, self._make_node())

        self.assertEqual(invoked, [])
        self.assertEqual(gov.accounting.reserved_inr, 0.0)
        self.assertEqual(len(gov._active_reservations), 0)
        self.assertEqual(len(gov._uncertain_reservations), 0)


if __name__ == "__main__":
    unittest.main()
