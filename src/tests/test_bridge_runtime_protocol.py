from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from src.bridge.protocol import PROTOCOL_VERSION


def send(proc, frame):
    proc.stdin.write(json.dumps(frame) + "\n")
    proc.stdin.flush()
    # Async observability frames (workspace.bound) trail direct replies and
    # are never the answer to a method — skip them.
    while True:
        reply = json.loads(proc.stdout.readline())
        if reply.get("type") not in {"workspace.bound", "llm.request"}:
            return reply


@pytest.fixture
def bridge():
    env = dict(os.environ)
    env["PULSEAI_BRIDGE_RUNNER"] = "echo"
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.bridge"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    assert send(proc, {"type": "hello", "protocol": PROTOCOL_VERSION})["type"] == "hello"
    yield proc
    proc.kill()


def test_session_create_list_and_resume(bridge, tmp_path):
    ws = str(tmp_path)
    created = send(bridge, {"type": "session_create", "session_id": "s1", "workspace": ws})
    assert created["type"] == "session_info" and created["session_id"] == "s1"
    listed = send(bridge, {"type": "session_list", "session_id": "s1"})
    assert any(s["session_id"] == "s1" for s in listed["sessions"])
    resumed = send(bridge, {"type": "session_resume", "session_id": "s1", "workspace": ws})
    assert resumed["resumed"] is True and "events" in resumed


def test_queue_steer_cancel_are_protocol_distinct(bridge):
    queued = send(bridge, {"type": "queue", "session_id": "s", "text": "later"})
    assert queued["queued"] == 1
    steered = send(bridge, {"type": "steer", "session_id": "s", "text": "change"})
    assert steered["steer_accepted"] is False  # no active turn
    cancelled = send(bridge, {"type": "cancel", "session_id": "s"})
    assert cancelled["cancel_requested"] is False


def test_queue_frame_honors_the_execution_mode(bridge):
    """An explicit queue frame may carry a mode; a bogus one falls back to
    agent and queues fine. Depth receipts prove every frame landed; the
    registry-level mode preservation is pinned in
    test_hermes_runtime_values.test_queue_preserves_the_prompt_execution_mode."""
    first = send(bridge, {"type": "queue", "session_id": "sq", "text": "explain this", "mode": "ask"})
    second = send(bridge, {"type": "queue", "session_id": "sq", "text": "plan it", "mode": "plan"})
    third = send(bridge, {"type": "queue", "session_id": "sq", "text": "bogus", "mode": "nonsense"})
    assert (first["queued"], second["queued"], third["queued"]) == (1, 2, 3)


def test_checkpoint_list_has_structured_event(bridge, tmp_path):
    frame = send(bridge, {
        "type": "checkpoint_list", "session_id": "s", "workspace": str(tmp_path)
    })
    assert frame["type"] == "checkpoint_event"
    assert frame["checkpoints"] == []
