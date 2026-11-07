"""P0.6.5 — live acceptance harness: offline regression suite.

These tests cover the *mechanisms* the live run depends on. They are not
evidence that a desktop turn succeeded; they prove the harness refuses to call
a turn successful when the chain is broken.

  1. Acceptance env carries the run id, budget and isolated home.
  2. Engine readiness requires the panel's own "Crusor ready" chip, not an
     enabled composer.
  3. One UI submission = one manifest, matched by prompt sha256.
  4. Guard evidence must come from the app's own bridge PID (the P0.6.4.1
     weakness: two unrelated records used to count as correlation).
  5. Guard evidence must show attempts_per_dispatch == 1 and <=5 dispatches.
  6. Financial settlement must exist and stay within budget.
  7. Worker->bridge ownership is decided by ancestry, not by name matching.
  8. The prompt is typed with real input events and sent with Enter.
  9. Console evidence finds the bridge's acceptance line.
 10. Verdict stays FAILED when any required stage is missing.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from benchmarks.crusor_desktop_acceptance import live_turn as lt
from benchmarks.crusor_desktop_acceptance.processes import ProcessInfo, engine_processes_from


class _FakeCdp:
    def __init__(self, *, status_text: str = "Crusor ready", composer_value: str = ""):
        self.status_text = status_text
        self.value = composer_value
        self.calls: list[tuple[str, dict]] = []

    def evaluate(self, expression: str, **kwargs):
        if "crusorai-engine-status" in expression:
            return {"present": True, "text": self.status_text, "cls": "crusorai-engine-status is-ready"}
        if "textarea.crusorai-composer-input" in expression:
            if "el.focus()" in expression:
                return {"focused": True, "disabled": False, "readonly": False}
            return self.value
        return None

    def call(self, method: str, params: dict | None = None, **kwargs):
        self.calls.append((method, params or {}))
        if method == "Input.insertText":
            self.value = (params or {}).get("text", "")
        return {}


class TestAcceptanceEnv(unittest.TestCase):
    def test_1_env_is_isolated_and_bounded(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="p0_6_5_env_"))
        env = lt.build_acceptance_env(run_id="p0_6_5_test", evidence_dir=tmp, max_dispatches=5, budget_inr=5.0)
        self.assertEqual(env["CRUSORAI_ACCEPTANCE_RUN_ID"], "p0_6_5_test")
        self.assertEqual(env["CRUSORAI_ACCEPTANCE_MAX_DISPATCHES"], "5")
        self.assertEqual(Path(env["CRUSORAI_ACCEPTANCE_EVIDENCE_PATH"]).resolve(),
                         (tmp / "acceptance_dispatch.json").resolve())
        self.assertEqual(Path(env["CRUSORAI_HOME"]).resolve(), (tmp / "home").resolve())
        self.assertEqual(env["CRUSORAI_TURN_COST_BUDGET_INR"], "5.00")
        self.assertEqual(env["CRUSORAI_SESSION_COST_BUDGET_INR"], "5.00")
        self.assertEqual(env["CRUSORAI_COST_GOVERNANCE"], "on")


class TestEngineReadiness(unittest.TestCase):
    def test_2_ready_requires_the_ready_chip(self) -> None:
        self.assertTrue(lt.wait_for_engine_ready(_FakeCdp(status_text="Crusor ready"), timeout_s=2)["ready"])
        not_ready = lt.wait_for_engine_ready(_FakeCdp(status_text="Engine starting"), timeout_s=0.6)
        self.assertFalse(not_ready["ready"])
        self.assertEqual(not_ready["state"]["text"], "Engine starting")

    def test_2b_missing_chip_is_not_ready(self) -> None:
        client = MagicMock()
        client.evaluate.return_value = {"present": False}
        self.assertFalse(lt.wait_for_engine_ready(client, timeout_s=0.3)["ready"])


class TestTurnManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="p0_6_5_home_"))
        self.turns = self.home / "evidence" / "turns" / "session-x"
        self.turns.mkdir(parents=True)

    def _write(self, turn_id: str, prompt: str, status: str = "running") -> Path:
        import hashlib

        payload = {
            "identity": {"session_id": "session-x", "turn_id": turn_id, "workspace_id": "ws-1"},
            "request": {"sha256": hashlib.sha256(prompt.encode()).hexdigest(), "byte_length": len(prompt)},
            "terminal": {"status": status, "completed": status == "completed"},
        }
        path = self.turns / f"{turn_id}.json"
        encoded = json.dumps(payload).encode()
        path.write_bytes(encoded)
        path.with_suffix(".json.sha256").write_text(hashlib.sha256(encoded).hexdigest(), encoding="ascii")
        return path

    def test_3_manifest_is_matched_by_prompt_hash(self) -> None:
        self._write("turn-wrong", "some other prompt")
        self._write("turn-right", "the acceptance prompt")
        seen = lt.list_turn_manifests(self.home)
        self.assertEqual(len(seen), 2)
        got = lt.wait_for_turn_manifest(self.home, prompt_sha=lt.prompt_sha256("the acceptance prompt"),
                                        seen_before=set(), timeout_s=3)
        self.assertTrue(got["prompt_sha256_matches"])
        self.assertEqual(got["manifest"]["identity"]["turn_id"], "turn-right")

    def test_3b_only_new_manifests_are_considered(self) -> None:
        self._write("turn-old", "the acceptance prompt")
        seen = lt.list_turn_manifests(self.home)
        with self.assertRaises(TimeoutError):
            lt.wait_for_turn_manifest(self.home, prompt_sha=lt.prompt_sha256("the acceptance prompt"),
                                      seen_before=seen, timeout_s=0.5)

    def test_3c_tampered_manifest_is_ignored(self) -> None:
        path = self._write("turn-tampered", "the acceptance prompt")
        path.write_bytes(path.read_bytes().replace(b"session-x", b"session-y"))
        with self.assertRaises(TimeoutError):
            lt.wait_for_turn_manifest(self.home, prompt_sha=lt.prompt_sha256("the acceptance prompt"),
                                      seen_before=set(), timeout_s=0.5)


class TestGuardCorrelation(unittest.TestCase):
    def _ledger(self, **over) -> dict:
        base = {
            "available": True, "run_id": "p0_6_5_x", "max_dispatches": 5,
            "attempts_per_dispatch": 1, "dispatches_used": 2, "pid": 4242,
            "claims": [{"sequence": 1, "stage": "retry_llm_proxy", "model": "m"},
                       {"sequence": 2, "stage": "retry_llm_proxy", "model": "m"}],
        }
        base.update(over)
        return base

    def test_4_guard_must_come_from_the_app_bridge_pid(self) -> None:
        ok = lt.classify_guard(self._ledger(), run_id="p0_6_5_x", bridge_pid=4242)
        self.assertTrue(ok["ok"])
        foreign = lt.classify_guard(self._ledger(pid=9999), run_id="p0_6_5_x", bridge_pid=4242)
        self.assertFalse(foreign["ok"], "a ledger from another process must not count")
        self.assertFalse(foreign["pid_matches_bridge"])

    def test_4b_guard_accepts_the_real_interpreter_of_a_shimmed_bridge(self) -> None:
        ledger = self._ledger(pid=8152)
        ok = lt.classify_guard(ledger, run_id="p0_6_5_x", owned_bridge_pids=[26972, 8152])
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["pid"], 8152)
        # A pid outside the app-owned set is still refused.
        self.assertFalse(lt.classify_guard(self._ledger(pid=1234), run_id="p0_6_5_x",
                                           owned_bridge_pids=[26972, 8152])["ok"])

    def test_5_single_attempt_and_dispatch_ceiling(self) -> None:
        self.assertFalse(lt.classify_guard(self._ledger(attempts_per_dispatch=2),
                                           run_id="p0_6_5_x", bridge_pid=4242)["ok"])
        six = self._ledger(dispatches_used=6, claims=[{"sequence": i} for i in range(1, 7)])
        self.assertFalse(lt.classify_guard(six, run_id="p0_6_5_x", bridge_pid=4242)["ok"])
        self.assertFalse(lt.classify_guard(self._ledger(run_id="other"),
                                           run_id="p0_6_5_x", bridge_pid=4242)["ok"])

    def test_5b_missing_ledger_is_not_evidence(self) -> None:
        self.assertFalse(lt.classify_guard({"available": False}, run_id="r", bridge_pid=1)["ok"])


class TestFinancialClassification(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="p0_6_5_fin_"))
        self.db = self.tmp / "sessions.db"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE financial_reservations (reservation_id TEXT, root_session_id TEXT, session_id TEXT, turn_id TEXT, estimated_cost_inr REAL, estimated_tokens INT, purpose TEXT, status TEXT, created_at REAL, updated_at REAL)")
        con.execute("CREATE TABLE financial_call_ledger (event_id TEXT, root_session_id TEXT, child_session_id TEXT, turn_id TEXT, provider TEXT, model TEXT, tier TEXT, purpose TEXT, input_tokens INT, output_tokens INT, cached_tokens INT, total_tokens INT, estimated_cost_usd REAL, estimated_cost_inr REAL, actual_cost_usd REAL, actual_cost_inr REAL, cost_known INT, pricing_status TEXT, reservation_id TEXT, call_outcome TEXT, created_at REAL, cache_write_tokens INT)")
        con.execute("CREATE TABLE financial_session_snapshots (session_id TEXT, root_session_id TEXT, cumulative_cost_inr REAL, turn_cost_inr REAL, total_calls_count INT)")
        con.commit()
        con.close()

    def _insert(self, *, status: str, cost: float, cost_known: int = 1) -> None:
        con = sqlite3.connect(self.db)
        con.execute(
            "INSERT INTO financial_reservations (reservation_id, root_session_id, session_id, turn_id, "
            "estimated_cost_inr, estimated_tokens, purpose, status, created_at, updated_at) "
            "VALUES ('res_1','s1','s1','t1',0.5,1000,'work',?,1,1)", (status,))
        con.execute(
            "INSERT INTO financial_call_ledger (event_id, root_session_id, child_session_id, turn_id, provider, "
            "model, tier, purpose, input_tokens, output_tokens, cached_tokens, total_tokens, estimated_cost_usd, "
            "estimated_cost_inr, actual_cost_usd, actual_cost_inr, cost_known, pricing_status, reservation_id, "
            "call_outcome, created_at, cache_write_tokens) "
            "VALUES ('e1','s1',NULL,'t1','custom','m','standard','work',100,200,0,300,0.0001,0.01,NULL,?,?,"
            "'verified','res_1','ok',1,0)", (cost, cost_known))
        con.commit()
        con.close()

    def test_6_settled_within_budget_passes(self) -> None:
        self._insert(status="reconciled", cost=0.0123)
        state = lt.read_financial_state(self.db, session_id="s1", turn_id="t1")
        result = lt.classify_financials(state, budget_inr=5.0)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["all_settled"])
        self.assertLess(result["total_cost_inr"], 5.0)

    def test_6b_unsettled_or_over_budget_fails(self) -> None:
        self._insert(status="in_flight", cost=0.01)
        self.assertFalse(lt.classify_financials(
            lt.read_financial_state(self.db, session_id="s1", turn_id="t1"), budget_inr=5.0)["ok"])
        self.db.unlink()
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE financial_reservations (reservation_id TEXT, root_session_id TEXT, session_id TEXT, turn_id TEXT, estimated_cost_inr REAL, estimated_tokens INT, purpose TEXT, status TEXT, created_at REAL, updated_at REAL)")
        con.execute("CREATE TABLE financial_call_ledger (event_id TEXT, root_session_id TEXT, child_session_id TEXT, turn_id TEXT, provider TEXT, model TEXT, tier TEXT, purpose TEXT, input_tokens INT, output_tokens INT, cached_tokens INT, total_tokens INT, estimated_cost_usd REAL, estimated_cost_inr REAL, actual_cost_usd REAL, actual_cost_inr REAL, cost_known INT, pricing_status TEXT, reservation_id TEXT, call_outcome TEXT, created_at REAL, cache_write_tokens INT)")
        con.execute("CREATE TABLE financial_session_snapshots (session_id TEXT, root_session_id TEXT, cumulative_cost_inr REAL, turn_cost_inr REAL, total_calls_count INT)")
        con.commit(); con.close()
        self._insert(status="reconciled", cost=9.99)
        over = lt.classify_financials(
            lt.read_financial_state(self.db, session_id="s1", turn_id="t1"), budget_inr=5.0)
        self.assertFalse(over["ok"])
        self.assertFalse(over["within_budget"])

    def test_6c_missing_db_is_not_evidence(self) -> None:
        self.assertFalse(lt.classify_financials({"available": False}, budget_inr=5.0)["ok"])


class TestProcessOwnership(unittest.TestCase):
    def test_7_bridge_must_be_child_of_the_apps_utility_process(self) -> None:
        utility = ProcessInfo(pid=200, ppid=100, name="CrusorAI.exe",
                              command_line="CrusorAI.exe --type=utility --utility-sub-type=node.mojom.NodeService")
        owned_bridge = ProcessInfo(pid=300, ppid=200, name="python.exe",
                                   command_line="python.exe -m src.bridge")
        result = engine_processes_from([utility, owned_bridge], 100)
        self.assertTrue(result["ancestry_ok"])
        self.assertEqual(result["owned_bridge_pids"], [300])

    def test_7b_unowned_python_is_not_the_apps_bridge(self) -> None:
        utility = ProcessInfo(pid=200, ppid=100, name="CrusorAI.exe", command_line="--type=utility")
        stray = ProcessInfo(pid=400, ppid=1, name="python.exe", command_line="python.exe -m src.bridge")
        result = engine_processes_from([utility, stray], 100)
        self.assertFalse(result["ancestry_ok"])
        self.assertEqual(result["bridge_pids"], [400])
        self.assertEqual(result["owned_bridge_pids"], [])

    def test_7c_python_without_bridge_module_is_foreign(self) -> None:
        utility = ProcessInfo(pid=200, ppid=100, name="CrusorAI.exe", command_line="--type=utility")
        preview = ProcessInfo(pid=500, ppid=200, name="python.exe", command_line="python.exe -m src.preview.server")
        result = engine_processes_from([utility, preview], 100)
        self.assertEqual(result["bridge_pids"], [])
        self.assertEqual(result["foreign_python_pids"], [500])

    def test_7d_venv_shim_and_real_interpreter_are_both_owned(self) -> None:
        utility = ProcessInfo(pid=200, ppid=100, name="CrusorAI.exe", command_line="--type=utility")
        shim = ProcessInfo(pid=300, ppid=200, name="python.exe",
                           command_line=r".venv\Scripts\python.exe -m src.bridge")
        real = ProcessInfo(pid=400, ppid=300, name="python.exe",
                           command_line=r"uv\python\cpython.exe -m src.bridge")
        result = engine_processes_from([utility, shim, real], 100)
        self.assertEqual(result["owned_bridge_pids"], [300, 400])
        self.assertTrue(result["ancestry_ok"])


class TestUiSubmission(unittest.TestCase):
    def test_8_typing_uses_real_input_events(self) -> None:
        client = _FakeCdp()
        typed = lt.type_prompt(client, "hello crusor")
        self.assertTrue(typed["typed_matches_prompt"])
        methods = [c[0] for c in client.calls]
        self.assertIn("Input.insertText", methods, "text must be typed, not set via JS")

    def test_8b_enter_is_a_key_event(self) -> None:
        client = _FakeCdp()
        lt.press_enter(client)
        methods = [c[0] for c in client.calls]
        self.assertEqual(methods.count("Input.dispatchKeyEvent"), 2)
        self.assertEqual(methods[0], "Input.dispatchKeyEvent")
        keys = [c[1].get("key") for c in client.calls if c[0] == "Input.dispatchKeyEvent"]
        self.assertTrue(all(k == "Enter" for k in keys))
        # rawKeyDown (not keyDown/char): no text is inserted, so the composer's
        # preventDefault() handler owns the submission.
        self.assertNotIn("text", client.calls[0][1])
        self.assertEqual(client.calls[0][1].get("type"), "rawKeyDown")


class TestConsoleEvidence(unittest.TestCase):
    def test_9_acceptance_line_is_found(self) -> None:
        console = {"consoleWarns": [
            {"message": "[CrusorAI Engine] [bridge][env] loaded"},
            {"message": "[CrusorAI Engine] [bridge][acceptance] run=p0_6_5_x max_dispatches=5 attempts_per_dispatch=1"},
        ]}
        from benchmarks.crusor_desktop_acceptance.live_acceptance import LiveAcceptance

        found = LiveAcceptance._find_acceptance_line(console)
        self.assertTrue(found["found"])
        self.assertIn("p0_6_5_x", found["message"])

    def test_9b_absent_line_is_reported_absent(self) -> None:
        from benchmarks.crusor_desktop_acceptance.live_acceptance import LiveAcceptance

        self.assertFalse(LiveAcceptance._find_acceptance_line({"consoleWarns": []})["found"])


class TestVerdictGates(unittest.TestCase):
    def _instance(self):
        from benchmarks.crusor_desktop_acceptance.live_acceptance import LiveAcceptance, LiveTurnOptions

        tmp = Path(tempfile.mkdtemp(prefix="p0_6_5_verdict_"))
        return LiveAcceptance(LiveTurnOptions(
            evidence_dir=tmp / "ev", workspace=tmp / "ws", prompt="p", max_dispatches=5,
        ))

    def test_10_missing_correlation_cannot_pass(self) -> None:
        acc = self._instance()
        acc.state["stages"] = {"turn_terminal": {"status": "completed"}}
        acc.state["renderer_console"] = {"unhandled_errors": 0}
        verdict = acc._verdict(
            {"ok": True},
            {"ok": True},
            {"module_exists": True, "ast_ok": True, "pytest_returncode": 0},
        )
        self.assertEqual(verdict, "P0.6.5_ACCEPTANCE_FAILED")

    def test_10b_full_chain_passes_the_gate_math(self) -> None:
        acc = self._instance()
        acc.state["correlation"] = {"run_id": "r", "session_id": "s", "turn_id": "t", "workspace_id": "w"}
        acc.state["stages"] = {"turn_terminal": {"status": "completed"}}
        acc.state["renderer_console"] = {"unhandled_errors": 0}
        verdict = acc._verdict(
            {"ok": True},
            {"ok": True},
            {"module_exists": True, "ast_ok": True, "pytest_returncode": 0},
        )
        self.assertEqual(verdict, "P0.6.5_DESKTOP_ACCEPTED")

    def test_10c_guard_or_finance_failure_blocks_acceptance(self) -> None:
        acc = self._instance()
        acc.state["correlation"] = {"run_id": "r"}
        acc.state["stages"] = {"turn_terminal": {"status": "completed"}}
        acc.state["renderer_console"] = {"unhandled_errors": 0}
        good_verify = {"module_exists": True, "ast_ok": True, "pytest_returncode": 0}
        self.assertEqual(acc._verdict({"ok": False}, {"ok": True}, good_verify), "P0.6.5_ACCEPTANCE_FAILED")
        self.assertEqual(acc._verdict({"ok": True}, {"ok": False}, good_verify), "P0.6.5_ACCEPTANCE_FAILED")
        self.assertEqual(acc._verdict({"ok": True}, {"ok": True},
                                      {"module_exists": True, "ast_ok": True, "pytest_returncode": 1}),
                         "P0.6.5_ACCEPTANCE_FAILED")


class TestDiscoveryGitBounded(unittest.TestCase):
    """The P0.6.5 hang: git must never wedge project discovery."""

    def setUp(self) -> None:
        import subprocess
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="p0_6_5_git_"))
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=False)
        subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=self.tmp, check=False)
        subprocess.run(["git", "config", "user.name", "a"], cwd=self.tmp, check=False)
        (self.tmp / "a.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.tmp, check=False)
        subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=self.tmp, check=False)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_11_git_detection_returns_real_branch_and_head(self) -> None:
        from src.intelligence.discovery import RepositoryDiscoveryEngine

        data = RepositoryDiscoveryEngine(str(self.tmp)).discover_repository()
        self.assertTrue(data["git_info"]["is_git"])
        self.assertNotEqual(data["git_info"]["branch"], "unknown")
        self.assertLessEqual(len(data["git_info"]["head"]), 8)

    def test_11b_hung_git_is_killed_and_reported_quickly(self) -> None:
        import subprocess
        import time

        from src.intelligence.discovery import RepositoryDiscoveryEngine

        engine = RepositoryDiscoveryEngine(str(self.tmp))
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            engine._run_git(self.tmp, ["-c", "alias.slow=!sleep 30", "slow"], timeout=0.8)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 10.0, "a timed-out git call must not block the scan")


class TestTurnManifestPath(unittest.TestCase):
    def test_12_manifest_is_found_under_evidence_session_dir(self) -> None:
        import hashlib
        import json
        import tempfile

        home = Path(tempfile.mkdtemp(prefix="p0_6_5_path_"))
        session = home / "evidence" / "session-abc"
        session.mkdir(parents=True)
        payload = {
            "identity": {"session_id": "session-abc", "turn_id": "turn-1", "workspace_id": "ws-1"},
            "request": {"sha256": hashlib.sha256(b"prompt").hexdigest()},
            "terminal": {"status": "in_progress"},
        }
        path = session / "turn-1.json"
        encoded = json.dumps(payload).encode()
        path.write_bytes(encoded)
        path.with_suffix(".json.sha256").write_text(hashlib.sha256(encoded).hexdigest(), encoding="ascii")

        found = lt.list_turn_manifests(home)
        self.assertEqual(found, {str(path)})
        got = lt.wait_for_turn_manifest(home, prompt_sha=lt.prompt_sha256("prompt"),
                                        seen_before=set(), timeout_s=2)
        self.assertEqual(got["manifest"]["identity"]["turn_id"], "turn-1")


if __name__ == "__main__":
    unittest.main()
