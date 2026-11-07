"""P0.6.4.1 — Acceptance retry clamp & dispatch budget.

Proves, offline (no provider network calls):

  1. Acceptance mode forces exactly one attempt per invocation.
  2. A retryable provider error does not cause a second request.
  3. SDK retries are forced/held at 0 (fails closed otherwise).
  4. The five-dispatch turn limit is enforced BEFORE the provider is reached.
  5. Normal sessions keep their configured retry behaviour.
  6. No unmetered dispatch path: the budget is shared by every proxy and every
     stage of the turn, so a sixth dispatch is impossible from any client.
  7. The bridge activates the guard from CRUSORAI_ACCEPTANCE_RUN_ID and can
     persist its ledger.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from src.llm.acceptance_guard import (
    AcceptanceBudgetExceeded,
    AcceptanceDisciplineError,
    AcceptanceGuard,
    acceptance_mode,
    activate_from_environment,
    active_guard,
    claim_dispatch,
    clamp_max_attempts,
    enforce_sdk_single_retry,
    write_evidence,
)
from src.llm.factory import RetryLLMProxy


class _CountingLLM:
    """Minimal provider client: counts real invocations, optionally raises."""

    model = "fake-acceptance-model"

    def __init__(self, error: Exception | None = None, max_retries: int = 0):
        self.calls = 0
        self.error = error
        self.max_retries = max_retries

    # proxy-facing surface
    def bind_tools(self, tool_list):  # noqa: D401 - test double
        return self

    def bind(self, **kwargs):
        return self

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages, config=None, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return MagicMock(content="fake-response", tool_calls=None)


class TestAcceptanceClamp(unittest.TestCase):
    def tearDown(self) -> None:
        self.assertIsNone(active_guard(), "acceptance guard leaked out of the test")

    def test_1_acceptance_forces_a_single_attempt(self) -> None:
        with acceptance_mode("run_t1", max_dispatches=5):
            proxy = RetryLLMProxy(_CountingLLM(), max_attempts=5)
            self.assertEqual(proxy._max_attempts, 1)
            # Explicit per-call budgets are clamped too.
            proxy2 = RetryLLMProxy(_CountingLLM(), max_attempts=9)
            self.assertEqual(proxy2._max_attempts, 1)
        # Outside the mode the requested budget is preserved.
        self.assertEqual(RetryLLMProxy(_CountingLLM(), max_attempts=5)._max_attempts, 5)

    def test_2_retryable_error_does_not_retry(self) -> None:
        inner = _CountingLLM(error=ConnectionError("transient upstream reset"))
        with acceptance_mode("run_t2", max_dispatches=5):
            proxy = RetryLLMProxy(inner, max_attempts=5)
            with self.assertRaises(ConnectionError):
                proxy.invoke([{"role": "user", "content": "hi"}])
        self.assertEqual(inner.calls, 1, "a retryable error must not trigger a second request")

    def test_3_sdk_retries_are_forced_to_zero(self) -> None:
        inner = _CountingLLM(max_retries=3)
        with acceptance_mode("run_t3", max_dispatches=5):
            RetryLLMProxy(inner, max_attempts=5)
        self.assertEqual(inner.max_retries, 0)

        class _ReadOnly:
            model = "fake-readonly"

            def __init__(self):
                object.__setattr__(self, "_frozen", True)

            @property
            def max_retries(self):
                return 2

            def __setattr__(self, name, value):
                raise AttributeError("read-only client")

        with acceptance_mode("run_t3b", max_dispatches=5):
            with self.assertRaises(AcceptanceDisciplineError):
                enforce_sdk_single_retry(_ReadOnly())

    def test_4_five_dispatch_limit_is_enforced_before_the_provider(self) -> None:
        inner = _CountingLLM()
        with acceptance_mode("run_t4", max_dispatches=5) as guard:
            proxy = RetryLLMProxy(inner, max_attempts=5)
            for _ in range(5):
                proxy.invoke([{"role": "user", "content": "step"}])
            self.assertEqual(inner.calls, 5)
            with self.assertRaises(AcceptanceBudgetExceeded):
                proxy.invoke([{"role": "user", "content": "sixth"}])
            self.assertEqual(inner.calls, 5, "the sixth request must never reach the provider")
            self.assertEqual(guard.used, 5)
            self.assertEqual(guard.remaining, 0)

    def test_5_normal_sessions_keep_configured_retry_behaviour(self) -> None:
        inner = _CountingLLM(error=ConnectionError("transient"))
        proxy = RetryLLMProxy(inner, max_attempts=3)
        self.assertEqual(proxy._max_attempts, 3)
        with self.assertRaises(ConnectionError):
            proxy.invoke([{"role": "user", "content": "hi"}])
        self.assertEqual(inner.calls, 3, "outside acceptance mode the retry policy is unchanged")

    def test_6_no_unmetered_dispatch_path_across_stages(self) -> None:
        """Planning and implementation lanes share ONE turn budget."""
        planner = _CountingLLM()
        implementer = _CountingLLM()
        aux = _CountingLLM()
        with acceptance_mode("run_t6", max_dispatches=5) as guard:
            proxies = [
                RetryLLMProxy(planner, max_attempts=5),
                RetryLLMProxy(implementer, max_attempts=5),
                RetryLLMProxy(aux, max_attempts=5),
            ]
            proxies[0].invoke([{"role": "user", "content": "plan"}])
            proxies[1].invoke([{"role": "user", "content": "implement"}])
            proxies[1].invoke([{"role": "user", "content": "implement-2"}])
            proxies[2].invoke([{"role": "user", "content": "aux"}])
            proxies[0].invoke([{"role": "user", "content": "plan-2"}])
            self.assertEqual((planner.calls, implementer.calls, aux.calls), (2, 2, 1))
            self.assertEqual(guard.used, 5)
            # Any further dispatch from ANY proxy (any stage) is refused.
            for proxy in proxies:
                with self.assertRaises(AcceptanceBudgetExceeded):
                    proxy.invoke([{"role": "user", "content": "more"}])
            self.assertEqual(planner.calls + implementer.calls + aux.calls, 5)

    def test_6b_claims_are_recorded_with_stage_and_sequence(self) -> None:
        with acceptance_mode("run_t6b", max_dispatches=2) as guard:
            claim_dispatch(stage="planning", model="m1")
            claim_dispatch(stage="implementation", model="m2")
            snapshot = guard.snapshot()
        self.assertEqual(snapshot["dispatches_used"], 2)
        self.assertEqual([c["stage"] for c in snapshot["claims"]], ["planning", "implementation"])
        self.assertEqual([c["sequence"] for c in snapshot["claims"]], [1, 2])

    def test_7_clamp_is_identity_outside_acceptance(self) -> None:
        self.assertEqual(clamp_max_attempts(5), 5)
        self.assertIsNone(claim_dispatch(stage="noop"))


class TestAcceptanceEnvironment(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            "CRUSORAI_ACCEPTANCE_RUN_ID": os.environ.get("CRUSORAI_ACCEPTANCE_RUN_ID"),
            "CRUSORAI_ACCEPTANCE_MAX_DISPATCHES": os.environ.get("CRUSORAI_ACCEPTANCE_MAX_DISPATCHES"),
        }
        self.tmp = Path(tempfile.mkdtemp(prefix="crusor_p0_6_4_1_"))

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_8_bridge_env_activates_the_guard(self) -> None:
        os.environ["CRUSORAI_ACCEPTANCE_RUN_ID"] = "run_env_1"
        os.environ["CRUSORAI_ACCEPTANCE_MAX_DISPATCHES"] = "5"
        guard = activate_from_environment()
        try:
            self.assertIsNotNone(guard)
            assert guard is not None
            self.assertEqual(guard.run_id, "run_env_1")
            self.assertEqual(guard.max_dispatches, 5)
            self.assertIs(active_guard(), guard)
        finally:
            # reset module state for other tests
            import src.llm.acceptance_guard as mod
            with mod._active_lock:
                mod._active_guard = None

    def test_8b_no_env_means_no_acceptance_mode(self) -> None:
        os.environ.pop("CRUSORAI_ACCEPTANCE_RUN_ID", None)
        self.assertIsNone(activate_from_environment())
        self.assertIsNone(active_guard())

    def test_9_evidence_ledger_is_persisted(self) -> None:
        guard = AcceptanceGuard(run_id="run_ev", max_dispatches=2)
        guard.claim(stage="planning", model="m")
        target = self.tmp / "acceptance_dispatch.json"
        write_evidence(guard, str(target))
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["run_id"], "run_ev")
        self.assertEqual(payload["dispatches_used"], 1)
        self.assertEqual(payload["attempts_per_dispatch"], 1)
        self.assertEqual(payload["claims"][0]["stage"], "planning")


if __name__ == "__main__":
    unittest.main()
