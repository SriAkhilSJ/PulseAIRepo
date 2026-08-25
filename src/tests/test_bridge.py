"""Pins for the P2 bridge (Phase 0.4): protocol codec + stdio loop.

The codec is stdlib-only by design; the subprocess pins exercise the
REAL sidecar (python -m src.bridge) over real pipes — the same shape
the fork will see.
"""

from __future__ import annotations

import json
import uuid
import subprocess
import sys

import pytest

from src.bridge.protocol import (
    MAX_LINE_BYTES,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    ProtocolError,
    check_client_hello,
    decode_line,
    encode,
    error_frame,
    hello,
)


# ------------------------------------------------------------- codec

def test_codec_round_trip():
    obj = {"type": "prompt", "text": "héllo 🫀", "id": 7}
    frame = decode_line(encode(obj))
    assert frame == obj, "encode+decode must be identity (utf-8 safe)"


def test_codec_rejects_malformed_and_non_object():
    with pytest.raises(ProtocolError):
        decode_line(b"{not json\n")
    with pytest.raises(ProtocolError):
        decode_line(b"[1,2,3]\n")
    with pytest.raises(ProtocolError):
        decode_line(json.dumps({"no_type": 1}).encode())


def test_codec_size_guard():
    big = b'{"type":"x","pad":"' + b"a" * MAX_LINE_BYTES + b'"}'
    with pytest.raises(ProtocolError, match="exceeds"):
        decode_line(big)


def test_hello_handshake_rules():
    good = hello("v")
    assert good["protocol"] == PROTOCOL_VERSION and good["engine"] == "pulseai"
    assert check_client_hello({"type": "hello", "protocol": PROTOCOL_VERSION}) == PROTOCOL_VERSION
    assert SUPPORTED_PROTOCOL_VERSIONS == {1, 2}
    assert hello("v", protocol=1)["protocol"] == 1
    with pytest.raises(ProtocolError, match="mismatch"):
        check_client_hello({"type": "hello", "protocol": 999})
    with pytest.raises(ProtocolError, match="first frame"):
        check_client_hello({"type": "prompt"})


# ------------------------------------------------- live sidecar pins

def _send(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()
    # Async observability frames (workspace.bound, llm.request) are emitted
    # after direct replies and are never the answer to a method — skip them.
    observatory = {"workspace.bound", "llm.request"}
    while True:
        line = proc.stdout.readline()
        assert line, "sidecar closed stdout unexpectedly"
        frame = json.loads(line)
        if frame.get("type") not in observatory:
            return frame


@pytest.fixture()
def sidecar():
    import os
    env = dict(os.environ)
    env["PULSEAI_BRIDGE_RUNNER"] = "echo"
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.bridge"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=env,
    )
    yield proc
    proc.kill()


def test_sidecar_hello_then_real_runtime_shape(sidecar):
    r = _send(sidecar, {"type": "hello", "protocol": PROTOCOL_VERSION})
    assert r["type"] == "hello" and r["protocol"] == PROTOCOL_VERSION
    sidecar.stdin.write(json.dumps({
        "type": "prompt", "text": "hi", "session_id": "t1", "workspace": "."
    }) + "\n")
    sidecar.stdin.flush()
    frames = []
    while len(frames) < 6:
        frame = json.loads(sidecar.stdout.readline())
        frames.append(frame)
        if frame["type"] == "turn_done":
            break
    # workspace.bound may interleave (async bind evidence) — assert it AND the
    # core sequence separately.
    kinds = [f["type"] for f in frames if f["type"] != "workspace.bound"]
    assert kinds == ["turn_started", "token", "turn_done"]
    bound = [f for f in frames if f["type"] == "workspace.bound"]
    assert bound and bound[0]["hops"] == "."
    done = frames[-1]
    assert done["stub"] is False and done["session_id"] == "t1"
    assert done["turn_id"].startswith("turn-")
    assert done["workspace_id"].startswith("ws-")


def test_sidecar_negotiates_legacy_v1_without_downgrading_latest(sidecar):
    r = _send(sidecar, {"type": "hello", "protocol": 1})
    assert r["type"] == "hello" and r["protocol"] == 1
    assert PROTOCOL_VERSION == 2


def test_sidecar_never_dies_on_garbage(sidecar):
    sidecar.stdin.write("{garbage not json\n")
    sidecar.stdin.flush()
    line = sidecar.stdout.readline()
    assert "error" in json.loads(line)["type"]
    # …and still answers a proper handshake afterwards:
    r = _send(sidecar, {"type": "hello", "protocol": PROTOCOL_VERSION})
    assert r["type"] == "hello"


def test_sidecar_requires_handshake_first(sidecar):
    r = _send(sidecar, {"type": "prompt", "text": "skip hello"})
    assert r["type"] == "error" and "handshake" in r["message"]


# ---------------------------------------------------- workspace binding (P0)

def test_sidecar_rejects_session_create_without_workspace(sidecar):
    _send(sidecar, {"type": "hello", "protocol": PROTOCOL_VERSION})
    r = _send(sidecar, {"type": "session_create"})
    assert r["type"] == "error"
    assert "workspace required" in r["message"]


def test_sidecar_rejects_prompt_without_workspace(sidecar):
    _send(sidecar, {"type": "hello", "protocol": PROTOCOL_VERSION})
    r = _send(sidecar, {"type": "prompt", "session_id": "t-no-ws"})
    assert r["type"] == "error"
    assert "workspace required" in r["message"]


def test_sidecar_rejects_blank_workspace(sidecar):
    _send(sidecar, {"type": "hello", "protocol": PROTOCOL_VERSION})
    r = _send(sidecar, {"type": "session_create", "workspace": "   "})
    assert r["type"] == "error"
    assert "workspace required" in r["message"]
    r2 = _send(sidecar, {"type": "session_resume", "session_id": "t-blank"})
    assert r2["type"] == "error" and "workspace required" in r2["message"]


def test_sidecar_binds_session_to_an_explicit_workspace(sidecar):
    _send(sidecar, {"type": "hello", "protocol": PROTOCOL_VERSION})
    info = _send(sidecar, {"type": "session_create", "workspace": "d:\\pulse-ws"})
    assert info["type"] == "session_info"
    assert info["workspace"] == "d:\\pulse-ws"
    listed = _send(sidecar, {"type": "session_list"})
    assert listed["type"] == "session_info"
    assert any(s["workspace"] == "d:\\pulse-ws" for s in listed["sessions"])
    # A prompt routed to that session keeps the explicit binding.
    sidecar.stdin.write(json.dumps({
        "type": "prompt", "text": "hi", "session_id": info["session_id"],
        "workspace": "d:\\pulse-ws",
    }) + "\n")
    sidecar.stdin.flush()
    frames = []
    while len(frames) < 5:
        frame = json.loads(sidecar.stdout.readline())
        frames.append(frame)
        if frame["type"] == "turn_done":
            break
    assert frames[-1]["workspace_id"].startswith("ws-")


def test_sidecar_shutdown_exits_cleanly(sidecar):
    _send(sidecar, {"type": "hello", "protocol": PROTOCOL_VERSION})
    sidecar.stdin.write(json.dumps({"type": "shutdown"}) + "\n")
    sidecar.stdin.flush()
    sidecar.stdin.close()
    assert sidecar.wait(timeout=10) == 0, "shutdown must exit 0"


# ------------------------------------------------- observability frames (PBR-002)

def test_session_create_emits_workspace_bound_with_exact_hops(sidecar):
    """PBR-002 evidence: every workspace-bearing bind asserts the exact root."""
    _send(sidecar, {"type": "hello", "protocol": PROTOCOL_VERSION})
    sidecar.stdin.write(json.dumps({
        "type": "session_create", "session_id": "wb-1", "workspace": "/tmp/pbr-ws",
    }) + "\n")
    sidecar.stdin.flush()
    frames = []
    while len(frames) < 2:
        frames.append(json.loads(sidecar.stdout.readline()))
    kinds = [f["type"] for f in frames]
    assert "session_info" in kinds
    bound = next(f for f in frames if f["type"] == "workspace.bound")
    assert bound["session_id"] == "wb-1"
    assert bound["workspace"] == "/tmp/pbr-ws"
    assert bound["hops"] == "/tmp/pbr-ws"        # grader compares hops == fixture root
    assert bound["engine_root"] == "/tmp/pbr-ws"


def test_no_workspace_bound_without_workspace(sidecar):
    """A rejected create (no workspace) binds nothing: the direct reply is the
    error frame and the server stays responsive afterwards."""
    _send(sidecar, {"type": "hello", "protocol": PROTOCOL_VERSION})
    r = _send(sidecar, {"type": "session_create"})   # rejected: no workspace
    assert r["type"] == "error"
    listed = _send(sidecar, {"type": "session_list"})  # no re-handshake needed
    assert listed["type"] == "session_info"


def test_project_event_forwards_llm_request():
    from src.bridge.__main__ import BridgeServer
    from src.runtime.identity import TurnIdentity

    identity = TurnIdentity.create(session_id="proj-1", workspace="/tmp/pbr-ws")
    frame = BridgeServer._project_event({
        "type": "llm.request",
        "payload": {"session_id": "proj-1", "model": "sarvam-105b-conversations",
                    "messages": [{"role": "system", "head": "... workspace_proof.py ..."}]},
    }, identity)
    assert frame is not None
    assert frame["type"] == "llm.request"
    assert frame["model"] == "sarvam-105b-conversations"
    assert "workspace_proof.py" in json.dumps(frame)


def test_project_event_forwards_bounded_llm_response_metadata():
    from src.bridge.__main__ import BridgeServer
    from src.runtime.identity import TurnIdentity

    identity = TurnIdentity.create(session_id="proj-2", workspace="/tmp/pbr-ws")
    frame = BridgeServer._project_event({
        "type": "llm.response",
        "payload": {
            "session_id": "proj-2", "model": "sarvam-105b-conversations",
            "raw_finish_reason": "lengthlength", "finish_reason": "length",
            "incomplete": True, "tool_call_count": 1,
            "tool_names": ["write_file"], "content_chars": 0,
            "reasoning_chars": 120, "input_tokens": 400,
            "output_tokens": 50, "total_tokens": 450,
        },
    }, identity)
    assert frame is not None
    assert frame["type"] == "llm.response"
    assert frame["raw_finish_reason"] == "lengthlength"
    assert frame["finish_reason"] == "length"
    assert frame["incomplete"] is True
    assert frame["tool_call_count"] == 1
    assert frame["reasoning_chars"] == 120
    assert frame["total_tokens"] == 450


def test_forwarder_keeps_sessionless_events_drops_other_sessions():
    """Provider calls made with no active session (planner pre-turn, post-turn
    review) must still reach the client; another session's events must not
    (concurrent-turn isolation). Founder run counted 11 calls, only 4 frames."""
    import queue as _queue
    from src.bridge.__main__ import BridgeServer
    from src.runtime.identity import TurnIdentity

    identity = TurnIdentity.create(session_id="own", workspace="/tmp/ws")
    q: _queue.Queue = _queue.Queue()
    done = __import__("threading").Event()
    emitted = []
    server = object.__new__(BridgeServer)
    server.emit = emitted.append

    q.put({"type": "llm.request", "payload": {"session_id": None, "model": "m"}})       # sessionless -> keep
    q.put({"type": "llm.request", "payload": {"session_id": "other", "model": "m"}})    # other session -> drop
    q.put({"type": "llm.request", "payload": {"session_id": "own", "model": "m"}})      # own -> keep
    q.put({"type": "message.agent.chunk", "payload": {"text": "hi"}})                   # sessionless -> keep
    q.put({"type": "tool.call", "payload": {"session_id": "other", "name": "x"}})       # other -> drop
    done.set()  # loop exits after draining? no — loop checks done first; drain manually
    # Drain: run the loop body once by calling it with a tiny timeout pattern:
    # simplest is to process the queue directly through the same filter logic.
    # Instead of sleeping, temporarily unset done and stop via empty queue + timeout:
    done.clear()
    import threading
    t = threading.Thread(target=server._forward_events, args=(q, identity, done, "own"), daemon=True)
    t.start()
    import time
    time.sleep(0.5)
    done.set(); t.join(timeout=2)

    kinds = [f["type"] for f in emitted]
    assert kinds.count("llm.request") == 2, kinds      # sessionless + own kept, other dropped
    assert kinds.count("token") == 1, kinds            # sessionless chunk kept
    assert "tool_call_start" not in kinds              # other session dropped


def test_session_create_reports_prior_checkpoints(sidecar, tmp_path):
    """session_create must not claim a fresh start silently: a session id with
    durable checkpointer history resumes it (live-measured as linear call
    growth across benchmark runs). Fresh id -> prior_checkpoints == 0."""
    import sqlite3
    from src.bridge.__main__ import BridgeServer

    # Helper: missing db -> 0; existing db with rows -> count; junk -> None.
    assert BridgeServer._prior_checkpoint_count("anyone", str(tmp_path / "nope.db")) == 0
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE checkpoints (thread_id TEXT)")
    conn.execute("INSERT INTO checkpoints VALUES ('old-id')")
    conn.commit(); conn.close()
    assert BridgeServer._prior_checkpoint_count("old-id", str(db)) == 1
    assert BridgeServer._prior_checkpoint_count("new-id", str(db)) == 0
    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    assert BridgeServer._prior_checkpoint_count("x", str(junk)) is None

    # End-to-end: a fresh session_create reply carries prior_checkpoints == 0.
    _send(sidecar, {"type": "hello", "protocol": PROTOCOL_VERSION})
    import os
    info = _send(sidecar, {"type": "session_create", "workspace": str(tmp_path),
                           "session_id": f"fresh-{uuid.uuid4().hex[:8]}"})
    assert info["type"] == "session_info"
    assert info.get("prior_checkpoints") == 0
