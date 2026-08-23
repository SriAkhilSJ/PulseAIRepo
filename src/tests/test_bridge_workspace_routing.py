"""P0: workspace identity routing on the bridge (no-model, deterministic).

The desktop must bind every Pulse session to the user's OPENED workspace and
never silently fall back to ".", the engine root, pulse-res/app, or the app
directory. The bridge enforces the same contract, so this suite pins:

- no-folder blocking: workspace-required methods reject empty/missing/blank;
- exact propagation: session_create / prompt echo the exact canonical path
  (and its derived workspace_id) â€” no normalization to ".";
- non-workspace methods (hello, session_list) stay usable without a folder.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from src.bridge.protocol import PROTOCOL_VERSION
from src.runtime.identity import workspace_id

NO_WORKSPACE_ERROR = (
    "workspace required: open a project folder before starting a Pulse session"
)


@pytest.fixture
def bridge():
    env = dict(os.environ)
    env["PULSEAI_BRIDGE_RUNNER"] = "echo"
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.bridge"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    send(proc, {"type": "hello", "protocol": PROTOCOL_VERSION})
    yield proc
    proc.kill()


def send(proc, frame, expect_reply=True):
    proc.stdin.write(json.dumps(frame) + "\n")
    proc.stdin.flush()
    if not expect_reply:
        return None
    # Async observability frames (workspace.bound) follow direct replies and
    # are never the answer to a method — skip them.
    while True:
        reply = json.loads(proc.stdout.readline())
        if reply.get("type") not in {"workspace.bound", "llm.request"}:
            return reply


# ---------------------------------------------------------------------------
# NO-FOLDER BLOCKING
# ---------------------------------------------------------------------------


def test_session_create_without_workspace_is_rejected(bridge):
    reply = send(bridge, {"type": "session_create", "session_id": "s"})
    assert reply["type"] == "error"
    assert NO_WORKSPACE_ERROR in reply["message"]


def test_prompt_without_workspace_is_rejected(bridge):
    reply = send(bridge, {"type": "prompt", "session_id": "s", "text": "hi"})
    assert reply["type"] == "error"
    assert NO_WORKSPACE_ERROR in reply["message"]


def test_blank_workspace_is_rejected(bridge):
    reply = send(bridge, {"type": "session_create", "session_id": "s", "workspace": "   "})
    assert reply["type"] == "error"


def test_hello_and_list_work_without_folder(bridge):
    # session_list is not workspace-bound: an empty window can still show state.
    listed = send(bridge, {"type": "session_list", "session_id": "s"})
    assert listed["type"] == "session_info"


# ---------------------------------------------------------------------------
# EXACT OPENED-FOLDER PROPAGATION (no fallback to "." / engineRoot / app dir)
# ---------------------------------------------------------------------------


def test_session_create_echoes_exact_workspace(bridge):
    # The canonical acceptance path for the desktop vertical slice.
    ws = "D:\\pulse-ws"
    created = send(bridge, {"type": "session_create", "session_id": "s", "workspace": ws})
    assert created["type"] == "session_info"
    assert created["workspace"] == ws, "bridge must echo the exact opened folder"


def test_session_create_echoes_exact_tmp_workspace(bridge, tmp_path):
    ws = str(tmp_path)  # real absolute path on this OS
    created = send(bridge, {"type": "session_create", "session_id": "s", "workspace": ws})
    assert created["type"] == "session_info"
    assert created["workspace"] == ws


def test_prompt_carries_workspace_id_of_exact_folder(bridge, tmp_path):
    ws = str(tmp_path)
    send(bridge, {"type": "session_create", "session_id": "s", "workspace": ws})
    reply = send(bridge, {"type": "prompt", "session_id": "s", "workspace": ws, "text": "hi"})
    assert reply["type"] == "turn_started"
    # The turn identity's workspace_id is derived from the EXACT path (hashed),
    # proving the canonical folder reached the Python turn layer.
    assert reply["workspace_id"] == workspace_id(ws)


def test_no_silent_dot_fallback_on_missing_workspace(bridge):
    # "workspace" must never silently become "." or the engine root.
    reply = send(bridge, {"type": "prompt", "session_id": "s", "text": "hi"})
    assert reply["type"] == "error"
    assert reply["message"] != "."


def test_session_fork_and_load_require_workspace(bridge):
    for kind in ("session_load", "session_fork"):
        reply = send(bridge, {"type": kind, "session_id": "s"})
        assert reply["type"] == "error", f"{kind} must require a workspace"


# ---------------------------------------------------------------------------
# BINDING IS IMMUTABLE: follow-ups cannot silently switch an existing session
# ---------------------------------------------------------------------------


def test_existing_session_rejects_workspace_switch(bridge, tmp_path):
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    created = send(bridge, {"type": "session_create", "session_id": "s", "workspace": str(ws_a)})
    assert created["type"] == "session_info"
    assert created["workspace"] == str(ws_a)

    # A prompt that names a different folder must be REJECTED, not re-homed.
    reply = send(bridge, {"type": "prompt", "session_id": "s", "workspace": str(ws_b), "text": "hi"})
    assert reply["type"] == "error"
    assert "bound to workspace" in reply["message"]
    assert "cannot switch" in reply["message"]

    # The session record is untouched: it is still bound to ws_a.
    listed = send(bridge, {"type": "session_list"})
    entry = next(s for s in listed["sessions"] if s["session_id"] == "s")
    assert entry["workspace"] == str(ws_a)

    # Same-workspace follow-up still works (no false rejection).
    reply = send(bridge, {"type": "prompt", "session_id": "s", "workspace": str(ws_a), "text": "hi"})
    assert reply["type"] == "turn_started"
    assert reply["workspace_id"] == workspace_id(str(ws_a))
    # Drain the echo turn (token + turn_done) so later frames are not masked.
    while True:
        frame = json.loads(bridge.stdout.readline())
        if frame["type"] == "turn_done":
            break


def test_non_binding_frames_ignore_workspace_mismatch(bridge, tmp_path):
    """cancel/steer/events_replay do not bind, so a workspace-less follow-up
    on an existing session is fine (it cannot switch anything)."""
    ws = tmp_path / "a"
    ws.mkdir()
    send(bridge, {"type": "session_create", "session_id": "s", "workspace": str(ws)})
    reply = send(bridge, {"type": "cancel", "session_id": "s"})
    assert reply["type"] == "session_info"
    assert reply["cancel_requested"] is False
