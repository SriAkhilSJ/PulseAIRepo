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


if __name__ == "__main__":
    unittest.main()
