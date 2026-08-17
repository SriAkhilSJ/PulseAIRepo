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
    return json.loads(proc.stdout.readline())


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


def test_checkpoint_list_has_structured_event(bridge, tmp_path):
    frame = send(bridge, {
        "type": "checkpoint_list", "session_id": "s", "workspace": str(tmp_path)
    })
    assert frame["type"] == "checkpoint_event"
    assert frame["checkpoints"] == []
