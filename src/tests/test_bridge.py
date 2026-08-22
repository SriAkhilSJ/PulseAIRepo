"""Pins for the P2 bridge (Phase 0.4): protocol codec + stdio loop.

The codec is stdlib-only by design; the subprocess pins exercise the
REAL sidecar (python -m src.bridge) over real pipes — the same shape
the fork will see.
"""

from __future__ import annotations

import json
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
    line = proc.stdout.readline()
    assert line, "sidecar closed stdout unexpectedly"
    return json.loads(line)


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
    while len(frames) < 5:
        frame = json.loads(sidecar.stdout.readline())
        frames.append(frame)
        if frame["type"] == "turn_done":
            break
    assert [f["type"] for f in frames] == ["turn_started", "token", "turn_done"]
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
