"""Deterministic, provider-free scripted turn for desktop UI acceptance.

This is an explicit test seam (like CRUSORAI_BRIDGE_RUNNER=echo), not a model
simulation: every frame below is a fixed fixture. It exercises the real bridge,
approval queue, workspace write, typed cards and terminal receipt.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

STREAM_TEXT = (
    "Crusor — Build and Ship with Ease 🚀\n\n"
    "Created `hello.md` with a short greeting. "
    "क्रूसोर — आसान और भरोसेमंद। 日本語：開発を加速する。\n\n"
    "Verification passed and the workspace contains only the requested file."
)


def scripted_enabled() -> bool:
    return os.environ.get("CRUSORAI_BRIDGE_RUNNER", "").strip().lower() in {
        "scripted", "cards",
    }


CHAT_SCRIPT: list[dict[str, Any]] = [{
    "content": (
        "Crusor — Build and Ship with Ease 🚀\n\n"
        "Created `hello.md` with a short greeting. "
        "क्रूसोर — आसान और भरोसेमंद। 日本語：開発を加速する。\n\n"
        "Verification passed and the workspace contains only the requested file."
    ),
    "chunks": [
        "Crusor — Build ",
        "and Ship with Ease 🚀\n\n",
        "Created `hello.md` with a short greeting. ",
        "क्रूसोर — आसान और भरोसेमंद। ",
        "日本語：開発を加速する。\n\n",
        "Verification passed and the workspace",
        " contains only the requested file.",
    ],
    "usage": {"input_tokens": 128, "output_tokens": 64, "total_tokens": 192},
}]

TOOL_SCRIPT: list[dict[str, Any]] = [
    {
        "tool_calls": [{
            "name": "write_file",
            "args": {
                "path": "hello.md",
                "content": "Crusor — Build and Ship with Ease 🚀\n\nCreated hello.md.\nVerified.",
            },
            "id": "call-scripted-write-1",
        }],
    },
    {
        "content": (
            "Crusor — Build and Ship with Ease 🚀\n\n"
            "Created hello.md after approval and verified it."
        ),
        "chunks": [
            "Crusor — Build ",
            "and Ship with Ease 🚀\n\n",
            "Created hello.md after approval and verified it.",
        ],
        "usage": {"input_tokens": 96, "output_tokens": 32, "total_tokens": 128},
    },
]

_ENGINEERING_TEXT = (
    "Crusor is an AI-powered coding IDE that plans changes, applies them through "
    "an approval-gated workspace broker, runs verification, and reports a truthful "
    "delivery receipt.\n"
)
ENGINEERING_SCRIPT: list[dict[str, Any]] = [
    {
        "content": _ENGINEERING_TEXT,
        "usage": {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60},
    }
    for _ in range(12)
]


def install_provider_fixture(*, mode: str = "agent") -> None:
    """Configure the provider seam, then let the real graph run.

    This never emits transcript frames itself. The normal bridge forwarder,
    LangGraph nodes, checkpointer and receipt own the turn.
    """
    import json

    scenario = os.environ.get("CRUSORAI_SCRIPTED_SCENARIO", "").strip().lower()
    if not scenario:
        scenario = "tool" if mode in {"debug", "agent"} and os.environ.get(
            "CRUSORAI_SCRIPTED_TOOL_TURN", ""
        ).strip().lower() in {"1", "true", "yes", "on"} else "chat"
    os.environ["CRUSORAI_TEST_MODE"] = "1"
    os.environ.setdefault("CRUSORAI_AUTOTITLE", "0")
    if scenario == "engineering":
        os.environ["CRUSORAI_FORCE_REAL_MODEL"] = "1"
    if not os.environ.get("CRUSORAI_TEST_LLM_SCRIPT", "").strip():
        script = (
            ENGINEERING_SCRIPT if scenario == "engineering"
            else TOOL_SCRIPT if scenario == "tool"
            else CHAT_SCRIPT
        )
        os.environ["CRUSORAI_TEST_LLM_SCRIPT"] = json.dumps(script, ensure_ascii=False)


def _delay() -> None:
    try:
        ms = int(os.environ.get("CRUSORAI_SCRIPTED_DELAY_MS", "90") or "90")
    except ValueError:
        ms = 90
    if ms > 0:
        time.sleep(min(ms, 2_000) / 1000.0)


def _card(card_type: str, card_id: str, data: dict[str, Any], session_id: str, turn_id: str) -> dict[str, Any]:
    from src.bridge.agent_cards import normalize_card

    card = normalize_card(
        {"schema_version": 1, "card_type": card_type, "card_id": card_id, "data": data},
        session_id=session_id,
        turn_id=turn_id,
    )
    assert card is not None
    return card


def run_scripted_turn(
    *,
    emit: Callable[[dict], None],
    identity: Any,
    workspace: str,
    session_id: str,
    prompt: str,
    finalize_evidence: Callable[..., dict],
    emit_terminal: Callable[[dict], None],
    touch_turn: Callable[[str, str], None],
    cancelled: Callable[[str], bool],
) -> None:
    """Emit a fixed stream, wait for a real approval, then settle truthfully."""
    from src.bridge.agent_cards import card_frames_for_frame
    from src.dashboard.event_bus import approval_queue
    from src.runtime.turn_receipt import build_turn_receipt

    turn_id = identity.turn_id
    session = session_id
    turn_fields = {**identity.event_fields(), "session_id": session}

    def send(frame: dict) -> None:
        emit(frame)
        try:
            for card in card_frames_for_frame(frame, turn_id=turn_id):
                emit({"type": "agent_card", **turn_fields, "card": card})
        except Exception:
            pass

    def send_card(card: dict[str, Any]) -> None:
        emit({"type": "agent_card", **turn_fields, "card": card})

    def wait() -> bool:
        _delay()
        return cancelled(session)

    activity_id = f"{turn_id}:activity"
    send_card(_card("activity", activity_id, {
        "stage": "understanding",
        "label": "Understanding request",
        "status": "running",
    }, session, turn_id))
    if wait():
        return _cancel(emit_terminal, finalize_evidence, turn_fields, "cancelled during understanding")

    # Token chunks in fixed order: emoji and Devanagari stay intact.
    chunks = ["Crusor — Build ", "and Ship with Ease 🚀\n\n",
              "Created `hello.md`", " with a short greeting. ",
              "क्रूसोर — आसान और भरोसेमंद। ", "日本語：開発を加速する。\n\n",
              "Verification passed and the workspace", " contains only the requested file."]
    for chunk in chunks:
        if wait():
            return _cancel(emit_terminal, finalize_evidence, turn_fields, "cancelled during streaming")
        emit({"type": "token", **turn_fields, "text": chunk})

    send_card(_card("activity", activity_id, {
        "stage": "planning", "label": "Planning changes", "status": "running",
    }, session, turn_id))
    steps = [
        {"text": "Inspect the workspace", "status": "completed"},
        {"text": "Create hello.md", "status": "in_progress"},
        {"text": "Verify the delivered file", "status": "pending"},
    ]
    send({"type": "plan_updated", **turn_fields, "steps": steps,
          "summary": "Create one Markdown greeting and verify it."})
    emit({"type": "agent_card", **turn_fields, "card": _card("plan", f"{turn_id}:plan", {
        "summary": "Create one Markdown greeting and verify it.",
        "outcome": "Exactly one requested Markdown file.",
        "files": ["hello.md"],
        "steps": steps,
        "verification": ["decode UTF-8 bytes", "confirm workspace contents"],
    }, session, turn_id)})

    tool_id = "scripted-write-1"
    tool_args = {"path": "hello.md", "content": STREAM_TEXT}
    send({"type": "tool_call_start", **turn_fields, "tool_id": tool_id,
          "name": "write_file", "arguments": tool_args})
    send_card(_card("tool", f"{turn_id}:tool:{tool_id}", {
        "tool_id": tool_id, "name": "write_file",
        "description": "Writing hello.md", "status": "running",
    }, session, turn_id))

    diff = {
        "path": "hello.md", "operation": "create",
        "unified": "--- /dev/null\n+++ b/hello.md\n@@ -0,0 +1,4 @@\n+Crusor — Build and Ship with Ease 🚀\n+\n+Created hello.md.\n+Verified.",
    }
    approval_id = f"{turn_id}:approval:{tool_id}"
    send({"type": "safety_request", **turn_fields, "tool_id": tool_id,
          "name": "write_file", "arguments": tool_args, "diff": diff})
    approval_queue.request(
        tool_id, "write_file", tool_args, session_id=session, diff=diff,
    )
    send_card(_card("approval", approval_id, {
        "tool_id": tool_id, "path": "hello.md", "operation": "create",
        "diff": diff["unified"], "digest": "sha256:scripted-fixture",
        "status": "pending",
    }, session, turn_id))

    decision = approval_queue.wait_for_decision(
        tool_id, timeout=None, should_stop=lambda: cancelled(session),
    )
    if decision is None or decision.get("cancelled"):
        send_card(_card("approval", approval_id, {
            "tool_id": tool_id, "path": "hello.md", "operation": "create",
            "diff": diff["unified"], "digest": "sha256:scripted-fixture",
            "status": "cancelled",
        }, session, turn_id))
        return _cancel(emit_terminal, finalize_evidence, turn_fields, "cancelled while awaiting approval")

    approved = bool(decision.get("decision"))
    send_card(_card("approval", approval_id, {
        "tool_id": tool_id, "path": "hello.md", "operation": "create",
        "diff": diff["unified"], "digest": "sha256:scripted-fixture",
        "status": "approved" if approved else "denied",
    }, session, turn_id))
    if not approved:
        send({"type": "tool_call_end", **turn_fields, "tool_id": tool_id,
              "name": "write_file", "status": "denied",
              "result": {"error": "approval denied"}})
        message = "Approval denied. No file was written."
        evidence_done = finalize_evidence(
            status="denied", completed=False, cancelled=False,
            message=message, reason="approval_denied",
        )
        receipt = build_turn_receipt(
            session_id=session, turn_id=turn_id,
            state={"task_status": "denied"}, message=message,
            completed=False, denied=True, workspace=workspace,
            evidence=evidence_done,
        )
        emit_terminal({
            "type": "turn_done", **turn_fields, "message": message,
            "completed": False, "cancelled": False, "denied": True,
            "stub": False, "evidence": evidence_done, "receipt": receipt,
        })
        return

    target = Path(workspace) / "hello.md"
    target.write_bytes(STREAM_TEXT.encode("utf-8"))
    lines = STREAM_TEXT.count("\n") + 1
    send({"type": "tool_call_end", **turn_fields, "tool_id": tool_id,
          "name": "write_file", "status": "completed",
          "result": {"path": "hello.md", "lines_added": lines, "lines_removed": 0,
                     "duration_ms": 12}})

    send_card(_card("activity", activity_id, {
        "stage": "testing", "label": "Running tests", "status": "running",
    }, session, turn_id))
    test_tool = "scripted-tests-1"
    send({"type": "tool_call_start", **turn_fields, "tool_id": test_tool,
          "name": "run_tests", "arguments": {"path": "hello.md"}})
    send({"type": "tool_call_end", **turn_fields, "tool_id": test_tool,
          "name": "run_tests", "status": "completed",
          "result": {"executed": 3, "passed": 3, "failed": 0, "skipped": 0,
                     "duration_ms": 240, "failures": []}})

    send_card(_card("activity", activity_id, {
        "stage": "verifying", "label": "Verifying result", "status": "running",
    }, session, turn_id))
    send({"type": "verification_updated", **turn_fields,
          "status": "verified", "verification_status": "verified",
          "verified_requirements": ["hello.md exists", "UTF-8 bytes decode exactly"],
          "unverified_requirements": [], "changed_files": ["hello.md"],
          "evidence_refs": ["scripted://turn/verification"]})
    emit({"type": "agent_card", **turn_fields, "card": _card("verification", f"{turn_id}:verification", {
        "status": "VERIFIED",
        "verified": ["hello.md exists", "UTF-8 bytes decode exactly"],
        "unverified": [], "changed_files": ["hello.md"],
        "evidence": ["scripted://turn/verification"],
    }, session, turn_id)})

    send({"type": "telemetry", **turn_fields, "model": "scripted-fixture",
          "provider": "none", "input_tokens": 128, "output_tokens": 64,
          "cached_tokens": 0, "cost_inr": 0.0, "cost_usd": 0.0,
          "cost_certainty": "actual"})
    emit({"type": "agent_card", **turn_fields, "card": _card("cost", f"{turn_id}:cost", {
        "model": "scripted-fixture", "provider": "none",
        "input_tokens": 128, "output_tokens": 64, "cached_tokens": 0,
        "cost_inr": 0.0, "cost_usd": 0.0, "certainty": "actual",
    }, session, turn_id)})

    touch_turn(session, prompt)
    evidence_done = finalize_evidence(
        status="completed", completed=True, cancelled=False,
        message=STREAM_TEXT, reason="scripted_stream_fixture",
    )
    delivery = {
        "task_id": turn_id,
        "verdict": "COMPLETED",
        "independently_verified": True,
        "files_changed": ["hello.md"],
        "tests_executed": ["run_tests (3)"],
        "tests_passed": ["3"],
        "tests_failed": [],
        "what_was_requested": prompt,
        "what_was_implemented": ["Created hello.md via an approved mutation."],
        "cost_inr": 0.0,
        "cost_usd": 0.0,
        "duration_seconds": 1.0,
    }
    receipt = build_turn_receipt(
        session_id=session, turn_id=turn_id,
        state={
            "task_status": "completed",
            "engineering_delivery": delivery,
            "approval_receipts": [{"tool_id": tool_id, "decision": "approved"}],
            "mutation_receipts": [{
                "operation_id": "scripted-op-1",
                "file_path": "hello.md",
                "operation_type": "create",
                "status": "applied",
            }],
        },
        message=STREAM_TEXT, completed=True, workspace=workspace,
        evidence=evidence_done,
    )
    emit({"type": "agent_card", **turn_fields, "card": _card("delivery", f"{turn_id}:delivery", {
        "verdict": "COMPLETED", "status": "completed",
        "verification": "verified", "files_modified": ["hello.md"],
        "tests_executed": ["run_tests (3)"], "tests_passed": ["3"],
        "tests_failed": [], "approvals": 1, "mutations": 1,
        "message": STREAM_TEXT,
    }, session, turn_id)})
    emit_terminal({
        "type": "turn_done", **turn_fields, "message": STREAM_TEXT,
        "completed": True, "cancelled": False, "stub": False,
        "evidence": evidence_done, "receipt": receipt,
    })


def _cancel(
    emit_terminal: Callable[[dict], None],
    finalize_evidence: Callable[..., dict],
    turn_fields: dict,
    reason: str,
) -> None:
    message = "Operation cancelled by the user."
    evidence_done = finalize_evidence(
        status="cancelled", completed=False, cancelled=True,
        message=message, reason=reason,
    )
    emit_terminal({
        "type": "turn_done", **turn_fields, "message": message,
        "completed": False, "cancelled": True, "stub": False,
        "evidence": evidence_done,
    })
