"""Live11 repair: exactly-once submissions and truthful interrupted-call state.

No provider is called. The bridge test drives the real ``BridgeServer.handle``
dispatch boundary with a fake turn starter; the financial tests use the real
``OrchestrationFinOpsGovernor`` with a disposable workspace.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.bridge.__main__ import BridgeServer
from src.finops.invocation_context import read_invocations, record_invocation
from src.finops.recovery import (
    reconcile_workspace_finops,
    reconcile_workspace_submissions,
)
from src.orchestration.finops_governor import OrchestrationFinOpsGovernor
from src.runtime.submission_ledger import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RUNNING,
    SubmissionLedger,
    get_submission_ledger,
    prompt_sha256,
    reset_submission_ledgers,
)


def _ws() -> Path:
    root = Path(tempfile.mkdtemp(prefix="live11_repair_")).resolve()
    (root / ".crusorai" / "finops").mkdir(parents=True, exist_ok=True)
    return root


class FakeStore:
    def __init__(self):
        self.created = set()

    def get_session(self, sid):
        return {"id": sid} if sid in self.created else None

    def create_session(self, *args, **kwargs):
        sid = args[0] if args else kwargs.get("session_id", "")
        self.created.add(sid)
        return {"id": sid}


def _bridge(ws: Path) -> tuple[BridgeServer, list]:
    started: list = []
    server = BridgeServer.__new__(BridgeServer)
    server._sessions = {}
    server._workers = {}
    server._submission_ledgers = {}
    server._reconciled_workspaces = {str(ws)}
    server._known_workspaces = {str(ws)}
    server._shutdown = threading.Event()
    server.greeted = True
    server.protocol_version = 2
    server.frames = []
    server.emit = lambda frame: server.frames.append(frame)
    server._start_preview_proxy = lambda workspace: None
    server._durable_store = lambda: FakeStore()
    server._run_turn = (
        lambda sid, text, workspace, mode="agent", reasoning_effort=None, submission_id=None:
        started.append((sid, text, submission_id))
    )
    return server, started


def _wait(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TestSubmissionLedger(unittest.TestCase):
    def setUp(self) -> None:
        reset_submission_ledgers()
        self.ws = _ws()
        self.ledger = SubmissionLedger(self.ws)

    def tearDown(self) -> None:
        reset_submission_ledgers()
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_session_create_is_idempotent(self) -> None:
        first = self.ledger.record_session("sub-1", session_id="session-a")
        second = self.ledger.record_session("sub-1", session_id="session-b")
        self.assertEqual(first.session_id, "session-a")
        self.assertEqual(second.session_id, "session-a")
        self.assertEqual(len(self.ledger.summary()["states"]), 1)

    def test_prompt_claimed_exactly_once(self) -> None:
        self.ledger.record_session("sub-1", session_id="session-a")
        ok1, rec1, reason1 = self.ledger.claim_prompt("sub-1", session_id="session-a")
        ok2, rec2, reason2 = self.ledger.claim_prompt("sub-1", session_id="session-a")
        self.assertTrue(ok1, reason1)
        self.assertFalse(ok2)
        self.assertEqual(reason2, STATE_RUNNING)
        self.assertEqual(rec1.state, STATE_RUNNING)

    def test_duplicate_prompt_without_session_create_claims_once(self) -> None:
        ok1, _, _ = self.ledger.claim_prompt("sub-2", session_id="session-a")
        ok2, rec, reason = self.ledger.claim_prompt("sub-2", session_id="session-a")
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertEqual(reason, STATE_RUNNING)
        self.assertEqual(rec.session_id, "session-a")

    def test_cross_session_replay_is_rejected(self) -> None:
        self.ledger.record_session("sub-1", session_id="session-a")
        ok, rec, reason = self.ledger.claim_prompt("sub-1", session_id="session-b")
        self.assertFalse(ok)
        self.assertEqual(reason, "session_mismatch")
        self.assertEqual(rec.session_id, "session-a")

    def test_terminal_state_is_final(self) -> None:
        self.ledger.record_session("sub-1", session_id="session-a")
        self.ledger.claim_prompt("sub-1", session_id="session-a")
        self.ledger.mark_terminal("sub-1", STATE_COMPLETED, turn_id="turn-a")
        ok, rec, reason = self.ledger.claim_prompt("sub-1", session_id="session-a")
        self.assertFalse(ok)
        self.assertEqual(reason, STATE_COMPLETED)
        self.ledger.mark_terminal("sub-1", STATE_FAILED)
        self.assertEqual(self.ledger.get("sub-1").state, STATE_COMPLETED)

    def test_distinct_submissions_are_both_accepted(self) -> None:
        self.ledger.record_session("sub-1", session_id="session-a")
        self.ledger.record_session("sub-2", session_id="session-b")
        ok1, _, _ = self.ledger.claim_prompt("sub-1", session_id="session-a")
        ok2, _, _ = self.ledger.claim_prompt("sub-2", session_id="session-b")
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertEqual(self.ledger.summary()["total"], 2)

    def test_durable_reload_keeps_completed_submission(self) -> None:
        self.ledger.record_session("sub-1", session_id="session-a")
        self.ledger.claim_prompt("sub-1", session_id="session-a")
        self.ledger.mark_terminal("sub-1", STATE_COMPLETED, turn_id="turn-a")
        reloaded = SubmissionLedger(self.ws)
        rec = reloaded.get("sub-1")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.state, STATE_COMPLETED)
        self.assertEqual(rec.turn_id, "turn-a")
        ok, _, _ = reloaded.claim_prompt("sub-1", session_id="session-a")
        self.assertFalse(ok)

    def test_concurrent_claims_accept_exactly_one(self) -> None:
        self.ledger.record_session("sub-1", session_id="session-a")
        accepted: list[bool] = []
        lock = threading.Lock()

        def claim():
            ok, _, _ = self.ledger.claim_prompt("sub-1", session_id="session-a")
            with lock:
                accepted.append(ok)

        threads = [threading.Thread(target=claim) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(accepted.count(True), 1)

    def test_restart_marks_running_submission_failed(self) -> None:
        self.ledger.record_session("sub-1", session_id="session-a")
        self.ledger.claim_prompt("sub-1", session_id="session-a")
        reloaded = SubmissionLedger(self.ws)
        changed = reloaded.reconcile_running()
        self.assertEqual([rec.submission_id for rec in changed], ["sub-1"])
        self.assertEqual(reloaded.get("sub-1").state, STATE_FAILED)
        ok, _, _ = reloaded.claim_prompt("sub-1", session_id="session-a")
        self.assertFalse(ok)

    def test_legacy_replay_window_is_scoped_to_other_sessions(self) -> None:
        sha = prompt_sha256("build it")
        self.ledger.record_session("sub-1", session_id="session-a", prompt_sha=sha)
        self.ledger.claim_prompt("sub-1", session_id="session-a", prompt_sha=sha)
        self.ledger.mark_terminal("sub-1", STATE_COMPLETED)
        self.assertIsNotNone(self.ledger.find_recent_completed(sha))
        self.assertIsNone(self.ledger.find_recent_completed(sha, exclude_session_id="session-a"))
        self.assertIsNone(self.ledger.find_recent_completed(sha, window_s=0.0))


class TestBridgeDispatchBoundary(unittest.TestCase):
    def setUp(self) -> None:
        reset_submission_ledgers()
        self.ws = _ws()
        self._env = os.environ.get("CRUSORAI_BRIDGE_RUNNER")
        os.environ["CRUSORAI_BRIDGE_RUNNER"] = "echo"
        self.server, self.started = _bridge(self.ws)

    def tearDown(self) -> None:
        reset_submission_ledgers()
        if self._env is None:
            os.environ.pop("CRUSORAI_BRIDGE_RUNNER", None)
        else:
            os.environ["CRUSORAI_BRIDGE_RUNNER"] = self._env
        shutil.rmtree(self.ws, ignore_errors=True)

    def _create(self, submission_id: str) -> str:
        self.server.handle({
            "type": "session_create", "workspace": str(self.ws),
            "submission_id": submission_id,
        })
        infos = [f for f in self.server.frames if f.get("type") == "session_info" and f.get("session_id")]
        self.assertTrue(infos)
        return infos[-1]["session_id"]

    def test_one_submission_creates_one_session_and_one_turn(self) -> None:
        sid = self._create("sub-1")
        self.assertEqual(len(self.server._sessions), 1)
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid,
            "text": "build it", "submission_id": "sub-1",
        })
        self.assertTrue(_wait(lambda: len(self.started) == 1))
        # Duplicate IPC delivery of the same prompt is a no-op.
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid,
            "text": "build it", "submission_id": "sub-1",
        })
        time.sleep(0.15)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(len(self.server._sessions), 1)
        self.assertTrue(any(f.get("duplicate_submission") for f in self.server.frames))

    def test_duplicate_session_create_does_not_mint_a_second_session(self) -> None:
        sid1 = self._create("sub-1")
        sid2 = self._create("sub-1")
        self.assertEqual(sid1, sid2)
        self.assertEqual(len(self.server._sessions), 1)

    def test_cross_session_prompt_rejected(self) -> None:
        sid = self._create("sub-1")
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid,
            "text": "build it", "submission_id": "sub-1",
        })
        self.assertTrue(_wait(lambda: len(self.started) == 1))
        err = None
        for frame in self.server.frames:
            if frame.get("type") == "error":
                err = frame
        self.assertIsNone(err)  # baseline has no error
        # A replay bound to a different session is refused before dispatch.
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": "session-other",
            "text": "build it", "submission_id": "sub-1",
        })
        self.assertTrue(any(f.get("type") == "error" for f in self.server.frames))
        self.assertEqual(len(self.started), 1)

    def test_distinct_submission_creates_a_second_turn(self) -> None:
        sid = self._create("sub-1")
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid,
            "text": "build it", "submission_id": "sub-1",
        })
        self.assertTrue(_wait(lambda: len(self.started) == 1))
        get_submission_ledger(self.ws).mark_terminal("sub-1", STATE_COMPLETED, turn_id="turn-1")
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid,
            "text": "add docs", "submission_id": "sub-2",
        })
        self.assertTrue(_wait(lambda: len(self.started) == 2))
        self.assertEqual([row[2] for row in self.started], ["sub-1", "sub-2"])

    def test_new_session_same_prompt_with_new_id_is_blocked(self) -> None:
        sid = self._create("sub-1")
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid,
            "text": "build it", "submission_id": "sub-1",
        })
        self.assertTrue(_wait(lambda: len(self.started) == 1))
        get_submission_ledger(self.ws).mark_terminal("sub-1", STATE_COMPLETED, turn_id="turn-1")
        # A second session has no durable row yet; an identical prompt with a
        # brand-new id is the Live11 replay shape (new session, same text).
        sid2 = self._create("sub-2")
        self.assertNotEqual(sid, sid2)
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid2,
            "text": "build it", "submission_id": "sub-2",
        })
        time.sleep(0.15)
        self.assertEqual(len(self.started), 1)
        self.assertTrue(any(
            f.get("duplicate_submission") and f.get("submission_reason") == "new_session_same_prompt"
            for f in self.server.frames
        ))

    def test_existing_session_same_prompt_is_allowed(self) -> None:
        sid = self._create("sub-1")
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid,
            "text": "build it", "submission_id": "sub-1",
        })
        self.assertTrue(_wait(lambda: len(self.started) == 1))
        get_submission_ledger(self.ws).mark_terminal("sub-1", STATE_COMPLETED, turn_id="turn-1")
        # Same session already has a durable row: a deliberate repeat is a new
        # turn, not a session replay.
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid,
            "text": "build it", "submission_id": "sub-2",
        })
        self.assertTrue(_wait(lambda: len(self.started) == 2))

    def test_legacy_replay_without_id_is_blocked_for_another_session(self) -> None:
        sid = self._create("sub-1")
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid,
            "text": "build it", "submission_id": "sub-1",
        })
        self.assertTrue(_wait(lambda: len(self.started) == 1))
        get_submission_ledger(self.ws).mark_terminal("sub-1", STATE_COMPLETED, turn_id="turn-1")
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": sid,
            "text": "build it", "submission_id": "sub-2",
        })
        self.assertTrue(_wait(lambda: len(self.started) == 2))
        # A no-id replay for a DIFFERENT session is refused by the content window.
        other = "session-other"
        self.server._sessions[other] = {"session_id": other, "workspace": str(self.ws)}
        self.server.handle({
            "type": "prompt", "workspace": str(self.ws), "session_id": other,
            "text": "build it",
        })
        time.sleep(0.15)
        self.assertEqual(len(self.started), 2)


class TestFinancialLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = _ws()
        self.storage = self.ws / ".crusorai" / "finops"
        self.task_id = f"turn_task_{os.urandom(4).hex()}"
        self.governor = OrchestrationFinOpsGovernor(
            self.task_id,
            budget_inr=5.0,
            token_budget=150000,
            storage_dir=str(self.storage),
            workspace_root=str(self.ws),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def _reserve(self, amount: float = 0.10) -> str:
        return self.governor.reserve(
            estimated_tokens=1000,
            estimated_cost_inr=amount,
            purpose="test_dispatch",
        )

    def test_reserved_without_dispatch_is_released(self) -> None:
        rid = self._reserve()
        events = self.governor.reconcile_orphaned_reservations(reason="test")
        self.assertEqual(events[0]["to_state"], "released")
        self.assertNotIn(rid, self.governor._active_reservations)
        self.assertIn(rid, self.governor._settled_reservations)
        self.assertEqual(self.governor._settled_reservations[rid].status, "released")
        self.assertEqual(self.governor.accounting.reserved_inr, 0.0)

    def test_in_flight_becomes_uncertain_and_retains_hold(self) -> None:
        rid = self._reserve()
        self.governor.mark_in_flight(rid)
        events = self.governor.reconcile_orphaned_reservations(reason="test")
        self.assertEqual(events[0]["to_state"], "uncertain")
        self.assertIn(rid, self.governor._uncertain_reservations)
        self.assertNotIn(rid, self.governor._active_reservations)
        self.assertGreater(self.governor.accounting.reserved_inr, 0.0)
        self.assertEqual(self.governor._uncertain_reservations[rid].status, "uncertain")

    def test_reconciliation_is_idempotent(self) -> None:
        rid = self._reserve()
        self.governor.mark_in_flight(rid)
        self.assertEqual(len(self.governor.reconcile_orphaned_reservations()), 1)
        self.assertEqual(self.governor.reconcile_orphaned_reservations(), [])
        self.assertIn(rid, self.governor._uncertain_reservations)

    def test_uncertain_commit_is_settled_once(self) -> None:
        rid = self._reserve(0.20)
        self.governor.mark_in_flight(rid)
        self.governor.reconcile_orphaned_reservations()
        self.governor.commit_reservation(
            reservation_id=rid,
            actual_input_tokens=10,
            actual_output_tokens=5,
            actual_cached_tokens=0,
            actual_cost_inr=0.01,
            actual_cost_usd=0.0001,
        )
        spent_after_first = self.governor.accounting.spent_inr
        self.governor.commit_reservation(
            reservation_id=rid,
            actual_input_tokens=10,
            actual_output_tokens=5,
            actual_cached_tokens=0,
            actual_cost_inr=0.01,
            actual_cost_usd=0.0001,
        )
        self.assertEqual(self.governor.accounting.spent_inr, spent_after_first)
        self.assertIn(rid, self.governor._settled_reservations)
        self.assertEqual(self.governor._settled_reservations[rid].status, "reconciled")

    def test_workspace_sweep_resolves_orphan_file(self) -> None:
        rid = self._reserve()
        self.governor.mark_in_flight(rid)
        # Simulate a new process: sweep the durable file with a fresh governor.
        receipt = reconcile_workspace_finops(self.ws, reason="test_restart", force=True)
        self.assertEqual(receipt["tasks_reconciled"], 1)
        data = json.loads((self.storage / f"{self.task_id}_finops.json").read_text(encoding="utf-8"))
        self.assertNotIn(rid, data.get("active_reservations") or {})
        self.assertIn(rid, data.get("uncertain_reservations") or {})
        lifecycle = (self.storage / "lifecycle.jsonl").read_text(encoding="utf-8")
        self.assertIn(rid, lifecycle)
        self.assertIn("uncertain", lifecycle)

    def test_startup_sweep_skips_current_process_reservations(self) -> None:
        rid = self._reserve()
        self.governor.mark_in_flight(rid)
        receipt = reconcile_workspace_finops(self.ws, reason="test_startup")
        self.assertEqual(receipt["tasks_reconciled"], 0)
        data = json.loads((self.storage / f"{self.task_id}_finops.json").read_text(encoding="utf-8"))
        self.assertIn(rid, data.get("active_reservations") or {})

    def test_submission_restart_reconciliation_marks_failed(self) -> None:
        ledger = SubmissionLedger(self.ws)
        ledger.record_session("sub-1", session_id="session-a")
        ledger.claim_prompt("sub-1", session_id="session-a")
        receipt = reconcile_workspace_submissions(self.ws)
        self.assertEqual(receipt["reconciled"], 1)
        self.assertEqual(get_submission_ledger(self.ws).get("sub-1").state, STATE_FAILED)

    def test_invocation_record_carries_finish_reason_and_cap(self) -> None:
        record_invocation(self.ws, {
            "invocation_id": "inv_test",
            "subsystem": "engineering",
            "operation_type": "implementation",
            "provider": "custom",
            "model": "z-ai/glm-5.3-flash",
            "reservation_id": "res_test",
            "status": "settled",
            "requested_output_tokens": 8192,
            "finish_reason": "length",
            "response_received_at": 123.0,
            "usage_receipt_present": True,
            "input_tokens": 10,
            "output_tokens": 8192,
            "actual_cost_inr": 0.1,
            "actual_cost_usd": 0.001,
            "started_at": 120.0,
            "completed_at": 124.0,
        })
        rows = read_invocations(self.ws)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["finish_reason"], "length")
        self.assertEqual(rows[0]["requested_output_tokens"], 8192)
        self.assertTrue(rows[0]["usage_receipt_present"])
        self.assertIsNotNone(rows[0]["response_received_at"])


if __name__ == "__main__":
    unittest.main()
