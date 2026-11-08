"""LIVE12 readiness: bounded build metadata and autotitle-off controls."""
from __future__ import annotations

import io
import json
import os
import time
import unittest
from unittest.mock import patch

from src.bridge.__main__ import BridgeServer


def _server(*, build: str = "cached", resolved: bool = True) -> BridgeServer:
    server = BridgeServer.__new__(BridgeServer)
    server._engine_build_value = build
    server._engine_build_resolved = resolved
    server._engine_build_lock = __import__("threading").Lock()
    server._engine_build_timeout_s = 0.2
    server._write_lock = __import__("threading").Lock()
    server._protocol_out = io.BytesIO()
    return server


def _frames(server: BridgeServer) -> list[dict]:
    return [json.loads(line) for line in server._protocol_out.getvalue().decode("utf-8").splitlines()]


class TestBuildMetadata(unittest.TestCase):
    def test_emit_never_launches_git(self) -> None:
        server = _server(build="563f5cc2")
        with patch("subprocess.run", side_effect=AssertionError("Git must not run during emit")):
            server.emit({"type": "session_info", "session_id": "s1", "title": "t"})
        frame = _frames(server)[0]
        self.assertEqual(frame["build"], "563f5cc2")
        self.assertEqual(frame["type"], "session_info")
        self.assertEqual(frame["session_id"], "s1")
        self.assertEqual(frame["title"], "t")

    def test_repeated_session_info_uses_cache(self) -> None:
        server = _server(build="cached-build")
        with patch("subprocess.run", side_effect=AssertionError("Git must not run during emit")):
            for i in range(5):
                server.emit({"type": "session_info", "session_id": f"s{i}"})
        frames = _frames(server)
        self.assertEqual(len(frames), 5)
        self.assertTrue(all(frame["build"] == "cached-build" for frame in frames))

    def test_emit_does_not_call_engine_build_probe(self) -> None:
        server = _server(build="cached")
        with patch.object(server, "_engine_build", side_effect=AssertionError("probe called")):
            server.emit({"type": "session_info", "session_id": "s"})

    def test_build_probe_is_bounded_and_returns_unknown(self) -> None:
        server = _server(build="", resolved=False)
        server._read_git_build = lambda: (time.sleep(5), "late")[1]
        started = time.monotonic()
        value = server._engine_build()
        elapsed = time.monotonic() - started
        self.assertEqual(value, "unknown")
        self.assertLess(elapsed, 1.0)
        self.assertTrue(server._engine_build_resolved)

    def test_build_probe_is_cached_once(self) -> None:
        server = _server(build="", resolved=False)
        calls = {"n": 0}

        def fake_probe():
            calls["n"] += 1
            return "abc123"

        server._read_git_build = fake_probe
        self.assertEqual(server._engine_build(), "abc123")
        self.assertEqual(server._engine_build(), "abc123")
        self.assertEqual(calls["n"], 1)

    def test_unknown_build_is_explicit_and_safe(self) -> None:
        server = _server(build="unknown")
        server.emit({"type": "session_info", "session_id": "s", "renamed": True, "title": "x"})
        frame = _frames(server)[0]
        self.assertEqual(frame["build"], "unknown")
        self.assertEqual(frame["title"], "x")
        self.assertTrue(frame["renamed"])

    def test_payload_is_preserved(self) -> None:
        server = _server(build="b")
        payload = {
            "type": "session_info", "session_id": "s", "workspace": "w",
            "sessions": [{"id": "a"}], "queued": 2, "custom": {"x": 1},
        }
        server.emit(payload)
        frame = _frames(server)[0]
        for key, value in payload.items():
            self.assertEqual(frame[key], value)


class TestAutotitleOff(unittest.TestCase):
    def test_acceptance_env_does_not_override_autotitle(self) -> None:
        import tempfile
        from pathlib import Path
        from benchmarks.crusor_desktop_acceptance.live_turn import build_acceptance_env

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"CRUSORAI_AUTOTITLE": "off"}
        ):
            env = build_acceptance_env(
                run_id="preflight", evidence_dir=Path(tmp), max_dispatches=5, budget_inr=1.2,
            )
            self.assertNotIn("CRUSORAI_AUTOTITLE", env)
            self.assertEqual(os.environ["CRUSORAI_AUTOTITLE"], "off")

    def test_off_disables_auxiliary(self) -> None:
        server = BridgeServer.__new__(BridgeServer)
        with patch.dict(os.environ, {"CRUSORAI_AUTOTITLE": "off"}):
            self.assertFalse(server._auxiliary_llm_allowed())
        with patch.dict(os.environ, {"CRUSORAI_AUTOTITLE": "on"}):
            self.assertTrue(server._auxiliary_llm_allowed())

    def test_off_returns_before_store_or_provider(self) -> None:
        server = BridgeServer.__new__(BridgeServer)
        server._durable_store = lambda: (_ for _ in ()).throw(
            AssertionError("title path must not touch the store when off")
        )
        with patch.dict(os.environ, {"CRUSORAI_AUTOTITLE": "off"}):
            server._maybe_autotitle_session("s", "hi")

    def test_harness_and_bridge_agree_on_off_values(self) -> None:
        from benchmarks.crusor_desktop_acceptance.live_turn import autotitle_disabled

        server = BridgeServer.__new__(BridgeServer)
        for value in ("off", "0", "false", "no", "OFF", "  Off  "):
            with patch.dict(os.environ, {"CRUSORAI_AUTOTITLE": value}):
                self.assertFalse(
                    server._auxiliary_llm_allowed(),
                    f"bridge must disable auxiliary for {value!r}",
                )
                self.assertTrue(
                    autotitle_disabled(), f"harness must see {value!r} as disabled",
                )
        for value in ("on", "1", "true", "", "yes"):
            with patch.dict(os.environ, {"CRUSORAI_AUTOTITLE": value}):
                self.assertTrue(
                    server._auxiliary_llm_allowed(),
                    f"bridge must allow auxiliary for {value!r}",
                )
                self.assertFalse(
                    autotitle_disabled(), f"harness must see {value!r} as enabled",
                )

    def test_auxiliary_wait_is_skipped_when_titling_disabled(self) -> None:
        import tempfile
        from benchmarks.crusor_desktop_acceptance.live_turn import (
            wait_for_auxiliary_accounting,
        )

        with tempfile.TemporaryDirectory() as tmp:
            started = time.monotonic()
            result = wait_for_auxiliary_accounting(tmp, timeout_s=90.0, expected=False)
            elapsed = time.monotonic() - started
        self.assertFalse(result["waited"])
        self.assertEqual(result["skipped"], "auxiliary_disabled")
        self.assertLess(elapsed, 2.0, "titling-off must not burn the 90 s wait")


class TestAutotitleOffVerdict(unittest.TestCase):
    """A titling-off run must pass with zero title calls and fail on any."""

    @staticmethod
    def _instance():
        import tempfile
        from pathlib import Path
        from benchmarks.crusor_desktop_acceptance.live_acceptance import (
            LiveAcceptance,
            LiveTurnOptions,
        )

        tmp = Path(tempfile.mkdtemp(prefix="live12_verdict_"))
        return LiveAcceptance(LiveTurnOptions(
            evidence_dir=tmp / "ev", workspace=tmp / "ws", prompt="p", max_dispatches=5,
        ))

    @staticmethod
    def _in_turn() -> dict:
        final = {"total": 10, "failed": 0, "errors": 0,
                 "command": "python -m pytest -q tests/test_duration.py"}
        return {
            "available": True,
            "tests": [final],
            "final_test_run": final,
            "repairs": [],
            "completion_ok": True,
            "completion": {"ok": True, "blocked": False},
            "contract": {
                "contract_hash": "a" * 64,
                "ambiguities": [],
                "components": [
                    {"role": "SOURCE", "target_file": "src/duration.py",
                     "requirement_ids": ["REQ-001"]},
                    {"role": "TEST", "target_file": "tests/test_duration.py",
                     "requirement_ids": ["REQ-002"]},
                ],
            },
            "assignment": {"requirement_map": {
                "REQ-001": ["src/duration.py"],
                "REQ-002": ["tests/test_duration.py"],
            }},
            "plan": {"ok": True, "work_units": 2, "demand": 2},
            "cross_file": {"ok": True, "errors": []},
        }

    def _apply(self, acc, *, extra_aux: bool = False) -> None:
        records = [
            {"subsystem": "engineering", "status": "settled", "actual_cost_inr": 0.10,
             "model": "z-ai/glm-5.3-flash", "provider": "custom"},
            {"subsystem": "engineering", "status": "settled", "actual_cost_inr": 0.02,
             "model": "z-ai/glm-5.3-flash", "provider": "custom"},
        ]
        if extra_aux:
            records.append(
                {"subsystem": "session_titling", "status": "settled",
                 "actual_cost_inr": 0.01, "model": "qwen/qwen3.7-flash",
                 "provider": "cheap"},
            )
        calls = len(records)
        spent = round(sum(r["actual_cost_inr"] for r in records), 8)
        acc.state["correlation"] = {"run_id": "r", "session_id": "s", "turn_id": "t"}
        acc.state["stages"] = {"turn_terminal": {"status": "completed"}}
        acc.state["renderer_console"] = {"unhandled_errors": 0}
        acc.state["in_turn"] = self._in_turn()
        acc.state["invocations"] = {
            "available": True,
            "records": records,
            "summary": {"total_calls": calls, "settled_calls": calls,
                        "uncertain_calls": 0, "total_cost_inr": spent},
        }
        acc.state["session_financials"] = {
            "calls_count": calls, "settled_count": calls, "uncertain_count": 0,
            "active_count": 0, "spent_inr": spent,
        }
        acc.state["session_title"] = ""
        acc.state["autotitle"] = {"disabled": True, "value": "off"}

    @staticmethod
    def _verify() -> dict:
        return {"module_exists": True, "ast_ok": True, "pytest_returncode": 0,
                "independent_smoke": {"ok": True}}

    def test_title_off_with_zero_title_calls_passes(self) -> None:
        acc = self._instance()
        self._apply(acc)
        verdict = acc._verdict(
            {"ok": True, "dispatches_used": 2},
            {"ok": True, "calls_count": 2},
            self._verify(),
        )
        self.assertEqual(verdict, "P0.6.9_ACCEPTANCE_PASSED")
        self.assertEqual(acc.state["auxiliary_gate"]["aux_records"], 0)
        self.assertTrue(acc.state["auxiliary_gate"]["ok"])

    def test_title_off_with_a_title_call_fails(self) -> None:
        acc = self._instance()
        self._apply(acc, extra_aux=True)
        verdict = acc._verdict(
            {"ok": True, "dispatches_used": 3},
            {"ok": True, "calls_count": 2},
            self._verify(),
        )
        self.assertEqual(verdict, "P0.6.9_ACCEPTANCE_FAILED")
        self.assertEqual(acc.state["auxiliary_gate"]["aux_records"], 1)
        self.assertFalse(acc.state["auxiliary_gate"]["ok"])

    def test_title_enabled_still_requires_a_settled_title_call(self) -> None:
        acc = self._instance()
        self._apply(acc)
        acc.state["autotitle"] = {"disabled": False, "value": "on"}
        verdict = acc._verdict(
            {"ok": True, "dispatches_used": 2},
            {"ok": True, "calls_count": 2},
            self._verify(),
        )
        self.assertEqual(verdict, "P0.6.9_ACCEPTANCE_FAILED")


class _VisualStub:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def evaluate(self, expression: str) -> dict:
        self.calls += 1
        if self.fail:
            from benchmarks.crusor_desktop_acceptance.cdp_client import CdpError

            raise CdpError("no target")
        return {
            "tool_rows": 2, "running_rows": 1, "activity_rows": 1,
            "streaming_messages": 1, "plan_live": 1,
        }

    def screenshot(self) -> str:
        self.calls += 1
        if self.fail:
            from benchmarks.crusor_desktop_acceptance.cdp_client import CdpError

            raise CdpError("no target")
        return "cG5n"  # base64("png")


class TestVisualSampling(unittest.TestCase):
    """Mid-turn visual evidence must exist, be bounded, and never abort a turn."""

    def test_sample_records_panel_counts_and_is_bounded(self) -> None:
        acc = TestAutotitleOffVerdict._instance()
        stub = _VisualStub()
        for _ in range(3):
            acc._sample_visual(stub, "turn-running", max_samples=2)
        samples = acc.state["visual"]
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0]["panel"]["tool_rows"], 2)
        self.assertEqual(samples[0]["panel"]["running_rows"], 1)
        self.assertTrue(samples[0]["screenshot"].endswith("turn-00.png"))

    def test_sample_tolerates_cdp_failure(self) -> None:
        acc = TestAutotitleOffVerdict._instance()
        acc._sample_visual(_VisualStub(fail=True), "turn-running")
        entry = acc.state["visual"][0]
        self.assertIn("panel_error", entry)
        self.assertIn("screenshot_error", entry)
        self.assertEqual(entry["label"], "turn-running")


if __name__ == "__main__":
    unittest.main()
