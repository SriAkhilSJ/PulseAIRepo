"""P0.6.9 — Universal provider accounting (offline).

Proves every real invocation carries a reservation, attribution and settlement:
the governed gateway for auxiliary/background calls, the invocation ledger, the
acceptance-mode proxy refusal, and session-level reconciliation.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.finops.governed import AuxiliaryAccountingError, GovernedProviderGateway
from src.finops.invocation_context import (
    assert_governed_for_acceptance,
    current_scope,
    invocation_scope,
    ledger_path,
    read_invocations,
    summarize_invocations,
)
from src.llm.acceptance_guard import acceptance_mode
from src.llm.factory import RetryLLMProxy


class FakeResponse:
    def __init__(self, text: str = "Duration parser", input_tokens: int = 20, output_tokens: int = 5):
        self.content = text
        self.usage_metadata = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }


class FakeClient:
    def __init__(self, *, response=None, error: Exception | None = None):
        self.response = response or FakeResponse()
        self.error = error
        self.calls = 0
        self.saw_scope = False

    def invoke(self, prompt, **kwargs):
        self.calls += 1
        self.saw_scope = current_scope() is not None
        if self.error:
            raise self.error
        return self.response


def _ws() -> Path:
    root = Path(tempfile.mkdtemp(prefix="p0_6_9_")).resolve()
    (root / ".crusorai" / "finops").mkdir(parents=True, exist_ok=True)
    return root


def _gateway(ws: Path, **overrides) -> GovernedProviderGateway:
    options = dict(
        subsystem="session_titling",
        operation_type="auxiliary",
        session_id="session-test",
        run_id="run-test",
        turn_id="turn-test",
        workspace_id="ws-test",
        budget_inr=0.50,
        token_budget=4000,
    )
    options.update(overrides)
    return GovernedProviderGateway(ws, **options)


class TestGovernedGateway(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = _ws()

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_successful_call_reserves_usage_settles_and_records(self) -> None:
        client = FakeClient()
        result = _gateway(self.ws).invoke(
            prompt="Write a short title.",
            provider="groq",
            model="qwen/qwen3.6-27b",
            max_output_tokens=64,
            purpose="session_title",
            client=client,
        )
        self.assertEqual(result.status, "settled")
        self.assertEqual(result.input_tokens, 20)
        self.assertEqual(result.output_tokens, 5)
        self.assertGreater(result.actual_cost_inr, 0)
        self.assertTrue(client.saw_scope, "provider call must run inside a reservation scope")
        records = read_invocations(self.ws)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["subsystem"], "session_titling")
        self.assertEqual(record["status"], "settled")
        self.assertEqual(record["reservation_id"], result.reservation_id)
        self.assertEqual(record["settlement_id"], result.reservation_id)
        self.assertEqual(record["session_id"], "session-test")
        self.assertEqual(record["run_id"], "run-test")
        self.assertEqual(record["turn_id"], "turn-test")
        self.assertEqual(record["actual_cost_inr"], result.actual_cost_inr)
        finops = list((self.ws / ".crusorai" / "finops").glob("*_finops.json"))
        self.assertTrue(finops)
        data = json.loads(finops[0].read_text(encoding="utf-8"))
        self.assertEqual(data["accounting"]["calls_count"], 1)
        self.assertEqual(len(data["settled_reservations"]), 1)

    def test_unpriced_model_is_refused_before_dispatch(self) -> None:
        client = FakeClient()
        with self.assertRaises(AuxiliaryAccountingError):
            _gateway(self.ws).invoke(
                prompt="x",
                provider="groq",
                model="definitely/unknown-model-xyz",
                max_output_tokens=64,
                purpose="session_title",
                client=client,
            )
        self.assertEqual(client.calls, 0)
        records = read_invocations(self.ws)
        self.assertEqual(records[0]["status"], "blocked")

    def test_post_dispatch_error_is_uncertain_not_free(self) -> None:
        client = FakeClient(error=TimeoutError("read timed out"))
        with self.assertRaises(TimeoutError):
            _gateway(self.ws).invoke(
                prompt="x", provider="groq", model="qwen/qwen3.6-27b",
                max_output_tokens=64, purpose="session_title", client=client,
            )
        records = read_invocations(self.ws)
        self.assertEqual(records[0]["status"], "uncertain")
        self.assertEqual(records[0]["settlement_id"], "")
        data = json.loads(list((self.ws / ".crusorai" / "finops").glob("*_finops.json"))[0].read_text(encoding="utf-8"))
        self.assertEqual(len(data["uncertain_reservations"]), 1)

    def test_client_construction_failure_releases(self) -> None:
        def boom():
            raise RuntimeError("cannot build client")

        with self.assertRaises(AuxiliaryAccountingError):
            _gateway(self.ws).invoke(
                prompt="x", provider="groq", model="qwen/qwen3.6-27b",
                max_output_tokens=64, purpose="session_title", client_factory=boom,
            )
        records = read_invocations(self.ws)
        self.assertEqual(records[0]["status"], "released")

    def test_two_calls_are_two_distinct_settlements(self) -> None:
        gw = _gateway(self.ws)
        first = gw.invoke(prompt="a", provider="groq", model="qwen/qwen3.6-27b",
                          max_output_tokens=64, purpose="title", client=FakeClient())
        second = gw.invoke(prompt="b", provider="groq", model="qwen/qwen3.6-27b",
                           max_output_tokens=64, purpose="title", client=FakeClient())
        self.assertNotEqual(first.invocation_id, second.invocation_id)
        records = read_invocations(self.ws)
        self.assertEqual(len(records), 2)
        self.assertEqual(summarize_invocations(records)["settled_calls"], 2)

    def test_zero_budget_refuses(self) -> None:
        client = FakeClient()
        with self.assertRaises(AuxiliaryAccountingError):
            _gateway(self.ws, budget_inr=0.0).invoke(
                prompt="x", provider="groq", model="qwen/qwen3.6-27b",
                max_output_tokens=64, purpose="title", client=client,
            )
        self.assertEqual(client.calls, 0)


class TestAcceptanceProxyBoundary(unittest.TestCase):
    def test_unaccounted_proxy_call_fails_closed_in_acceptance(self) -> None:
        client = FakeClient()
        proxy = RetryLLMProxy(client, max_attempts=1, provider="groq")
        with acceptance_mode("test-run", max_dispatches=5):
            with self.assertRaises(Exception) as ctx:
                proxy.invoke("hello")
        self.assertIn("financial reservation", str(ctx.exception).lower())
        self.assertEqual(client.calls, 0, "no request may reach the provider")

    def test_accounted_proxy_call_is_allowed_in_acceptance(self) -> None:
        client = FakeClient()
        proxy = RetryLLMProxy(client, max_attempts=1, provider="groq")
        with acceptance_mode("test-run", max_dispatches=5):
            with invocation_scope(
                subsystem="engineering", reservation_id="res-1",
                operation_type="implementation", provider="groq",
                model="qwen/qwen3.6-27b", purpose="node",
            ):
                response = proxy.invoke("hello")
        self.assertEqual(response.content, "Duration parser")
        self.assertEqual(client.calls, 1)

    def test_outside_acceptance_scope_is_not_required(self) -> None:
        assert_governed_for_acceptance()  # no-op


class TestLedgerAndReconciliation(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = _ws()

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_summary_splits_task_and_auxiliary(self) -> None:
        from src.finops.invocation_context import record_invocation

        record_invocation(self.ws, {"subsystem": "engineering", "status": "settled",
                                    "actual_cost_inr": 0.10, "model": "m1", "provider": "p1"})
        record_invocation(self.ws, {"subsystem": "engineering", "status": "settled",
                                    "actual_cost_inr": 0.02, "model": "m1", "provider": "p1"})
        record_invocation(self.ws, {"subsystem": "session_titling", "status": "settled",
                                    "actual_cost_inr": 0.01, "model": "m2", "provider": "p2"})
        summary = summarize_invocations(read_invocations(self.ws))
        self.assertEqual(summary["total_calls"], 3)
        self.assertEqual(summary["settled_calls"], 3)
        self.assertAlmostEqual(summary["total_cost_inr"], 0.13, places=8)
        self.assertAlmostEqual(summary["by_subsystem"]["engineering"]["cost_inr"], 0.12, places=8)
        self.assertAlmostEqual(summary["by_subsystem"]["session_titling"]["cost_inr"], 0.01, places=8)

    def test_aggregate_finops_sums_task_and_auxiliary(self) -> None:
        from benchmarks.crusor_desktop_acceptance.live_turn import read_all_orchestration_finops

        root = self.ws / ".crusorai" / "finops"
        (root / "turn_task_finops.json").write_text(json.dumps({
            "accounting": {"task_id": "turn_task", "spent_inr": 0.12, "calls_count": 2},
            "settled_reservations": {"a": {}, "b": {}},
            "uncertain_reservations": {}, "active_reservations": {},
        }), encoding="utf-8")
        (root / "aux_session_titling_finops.json").write_text(json.dumps({
            "accounting": {"task_id": "aux_session_titling", "spent_inr": 0.01, "calls_count": 1},
            "settled_reservations": {"c": {}},
            "uncertain_reservations": {}, "active_reservations": {},
        }), encoding="utf-8")
        aggregate = read_all_orchestration_finops(self.ws)
        self.assertEqual(aggregate["calls_count"], 3)
        self.assertEqual(aggregate["settled_count"], 3)
        self.assertAlmostEqual(aggregate["spent_inr"], 0.13, places=8)

    def test_local_title_fallback_is_distinct_from_provider(self) -> None:
        from src.bridge.__main__ import BridgeServer

        title = BridgeServer._local_title("Create a duration parser with tests")
        self.assertTrue(title)
        self.assertNotIn("qwen", title.lower())
        self.assertFalse(ledger_path(self.ws).exists())


class TestTitlingAccounting(unittest.TestCase):
    def test_governed_invoke_shape_is_used_by_the_titler(self) -> None:
        # generate_session_title accepts an injected invoke; prove the returned
        # text flows through and the invocation ledger records the provider call.
        from src.runtime.session_titling import generate_session_title

        ws = _ws()
        try:
            gateway = _gateway(ws)
            calls = {"n": 0}

            def invoke(prompt):
                calls["n"] += 1
                return gateway.invoke(
                    prompt=prompt, provider="groq", model="qwen/qwen3.6-27b",
                    max_output_tokens=64, purpose="session_title", client=FakeClient(),
                ).text

            title = generate_session_title("Create a duration parser", "Done", invoke=invoke)
            self.assertTrue(title)
            self.assertEqual(calls["n"], 1)
            records = read_invocations(ws)
            self.assertEqual(records[0]["subsystem"], "session_titling")
            self.assertEqual(records[0]["status"], "settled")
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class TestBridgeTitlingWiring(unittest.TestCase):
    def test_bridge_titler_uses_the_governed_gateway(self) -> None:
        from src.bridge.__main__ import BridgeServer

        ws = _ws()

        class FakeStore:
            def __init__(self):
                self.title = ""

            def get_session(self, sid):
                return {"title": self.title, "workspace": str(ws)}

            def list_sessions_rich(self, *args, **kwargs):
                return []

            def set_title(self, sid, title):
                self.title = title
                return True

        store = FakeStore()
        server = object.__new__(BridgeServer)
        server._sessions = {}
        server._durable_store = lambda: store
        emitted = []
        server.emit = emitted.append

        client = FakeClient(response=FakeResponse("Duration parser"))
        records = []
        try:
            with patch.dict(os.environ, {
                "CRUSORAI_ACCEPTANCE_RUN_ID": "run-bridge",
                "CRUSORAI_SESSION_ID": "session-bridge",
                "CRUSORAI_TURN_ID": "turn-bridge",
                "CRUSORAI_WORKSPACE_ID": "ws-bridge",
            }, clear=False):
                with patch("src.llm.factory.get_llm", return_value=client):
                    server._maybe_autotitle_session(
                        "session-bridge", "Create a duration parser", "Done", wait=True,
                    )
            records = read_invocations(ws)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

        self.assertTrue(store.title)
        self.assertEqual(client.calls, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["subsystem"], "session_titling")
        self.assertEqual(records[0]["status"], "settled")
        self.assertEqual(records[0]["session_id"], "session-bridge")
        self.assertGreater(records[0]["actual_cost_inr"], 0)
        self.assertTrue(any(frame.get("type") == "session_info" for frame in emitted))


if __name__ == "__main__":
    unittest.main()
