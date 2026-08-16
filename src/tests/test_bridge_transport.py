"""No-credit bridge transport tests.

These pin the Protocol v2 transport contract that the P0 investigation
established: stdout carries JSON frames only, ordinary Python print() output
must be routed to stderr, a filled stderr pipe must never block the child,
and the event forwarder must survive projection/encoding failures.

Every test here is deterministic — no LLM calls, no API keys, no network.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.bridge.__main__ import BridgeServer
from src.bridge.protocol import PROTOCOL_VERSION
from src.runtime.identity import TurnIdentity

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------- helpers

def _run_script(script: str, env_extra: dict | None = None, timeout: float = 30.0):
    """Run a python snippet as a child, capturing stdout and stderr separately."""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    if env_extra:
        env.update(env_extra)
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    out, err = proc.communicate(timeout=timeout)
    assert proc.returncode == 0, f"child failed rc={proc.returncode}\nstdout:\n{out}\nstderr:\n{err}"
    return out, err


def _spawn_bridge(env_extra: dict | None = None):
    """Spawn the real sidecar with stderr drained by a dedicated thread."""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    if env_extra:
        env.update(env_extra)
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.bridge"],
        cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    err_drain = threading.Thread(target=lambda: [None for _ in proc.stderr], daemon=True)
    err_drain.start()
    return proc


def _send(proc, frame: dict) -> None:
    proc.stdin.write(json.dumps(frame) + "\n")
    proc.stdin.flush()


def _read_frames(proc, predicate, timeout: float = 20.0):
    """Read stdout lines until predicate(frame) is True; return all frames seen."""
    deadline = time.time() + timeout
    frames = []
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(
                f"no matching frame within {timeout}s; saw: {[f.get('type') for f in frames]}"
            )
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"bridge closed stdout early; saw: {[f.get('type') for f in frames]}")
        frame = json.loads(line)
        frames.append(frame)
        if predicate(frame):
            return frames


# ------------------------------------------------- 1. stdout purity

def test_regular_print_never_reaches_protocol_stdout():
    script = """
import sys
from src.bridge.__main__ import BridgeServer
b = BridgeServer()
print("GRAPH-DIAGNOSTIC-LINE", flush=True)
b.emit({"type": "session_info", "session_id": "purity"})
"""
    out, err = _run_script(script)
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1, f"stdout must carry exactly one JSON frame, got {len(lines)}: {lines!r}"
    frame = json.loads(lines[0])
    assert frame["type"] == "session_info" and frame["session_id"] == "purity"
    assert "GRAPH-DIAGNOSTIC-LINE" not in out, "print() output leaked onto protocol stdout"
    assert "GRAPH-DIAGNOSTIC-LINE" in err, "print() output must land on stderr"


# ------------------------------------------------- 2. stderr cannot block child

def test_large_stderr_cannot_block_child_when_drained():
    script = """
import sys
from src.bridge.__main__ import BridgeServer
b = BridgeServer()
for i in range(40000):
    print("x" * 200, flush=True)
b.emit({"type": "session_info", "session_id": "big-stderr"})
"""
    # Parent never reads this child's stderr directly; the helper captures it.
    # If the pipe filled, the child would block on print() before the emit.
    out, err = _run_script(script, timeout=60.0)
    frame = json.loads(out.strip().splitlines()[-1])
    assert frame["type"] == "session_info" and frame["session_id"] == "big-stderr"
    assert len(err) > 1_000_000, "sanity: the child really wrote a lot of stderr"


# ------------------------------------------------- 3. frames valid under concurrent diagnostics

def test_frames_stay_valid_while_another_thread_writes_diagnostics():
    script = """
import sys, threading, time
from src.bridge.__main__ import BridgeServer
b = BridgeServer()
def diag():
    for i in range(2000):
        print("noise " + str(i), flush=True)
threading.Thread(target=diag, daemon=True).start()
for i in range(100):
    b.emit({"type": "session_info", "session_id": "s", "i": i})
time.sleep(0.3)
"""
    out, _ = _run_script(script)
    frames = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert len(frames) == 100, f"expected 100 frames, got {len(frames)}"
    assert all(f["type"] == "session_info" for f in frames)
    assert [f["i"] for f in frames] == list(range(100))


# ------------------------------------------------- 4. fake delayed turn emits progress + turn_done

def test_echo_turn_emits_progress_then_turn_done():
    proc = _spawn_bridge({"PULSEAI_BRIDGE_RUNNER": "echo"})
    try:
        _send(proc, {"type": "hello", "protocol": PROTOCOL_VERSION})
        hello = _read_frames(proc, lambda f: f.get("type") == "hello")[-1]
        assert hello["protocol"] == PROTOCOL_VERSION

        _send(proc, {"type": "session_create", "session_id": "s-echo"})
        _read_frames(proc, lambda f: f.get("type") == "session_info")

        _send(proc, {"type": "prompt", "session_id": "s-echo", "text": "hello"})
        frames = _read_frames(proc, lambda f: f.get("type") == "turn_done")
        kinds = [f["type"] for f in frames]
        assert kinds[0] == "turn_started", kinds
        assert "token" in kinds, kinds
        assert kinds[-1] == "turn_done", kinds
        assert frames[-1]["completed"] is True
    finally:
        proc.kill()


# ------------------------------------------------- 5. fake approval: safety_request + exact-tool_id safety_reply

def test_fake_approval_request_reply_round_trip(tmp_path):
    from src.dashboard.event_bus import approval_queue, event_bus

    identity = TurnIdentity.create(session_id="s-approve", workspace=str(tmp_path))
    q = event_bus.subscribe(thread_id="s-approve")
    try:
        item = approval_queue.request(
            "tool-abc", "write_file", {"path": "x.txt"},
            session_id="s-approve", diff={"old_text": "a", "new_text": "b"},
        )
        event_bus.emit("tool.approval.request", {**item, "thread_id": "s-approve"})

        event = q.get(timeout=5)
        frame = BridgeServer._project_event(event, identity)
        assert frame["type"] == "safety_request"
        assert frame["tool_id"] == "tool-abc"
        assert frame["diff"] == {"old_text": "a", "new_text": "b"}

        # Exact tool_id resolves; a wrong tool_id must not.
        assert approval_queue.resolve("wrong-id", True, session_id="s-approve") is False
        assert approval_queue.resolve("tool-abc", True, session_id="s-approve") is True
        decision = approval_queue.wait_for_decision("tool-abc", timeout=5)
        assert decision and decision["decision"] is True
    finally:
        event_bus.unsubscribe(q)


# ------------------------------------------------- 6. forwarder survives projection failure

def test_forwarder_survives_projection_exception_and_emits_runtime_degraded(tmp_path):
    class BrokenProject(BridgeServer):
        @staticmethod
        def _project_event(event: dict, identity: TurnIdentity) -> dict | None:
            if event.get("type") == "tool.call":
                raise ValueError("boom")
            return BridgeServer._project_event(event, identity)

    # Build a bare instance without touching process-global sys.stdout.
    server = object.__new__(BrokenProject)
    server._write_lock = threading.Lock()
    emitted: list[dict] = []
    server.emit = emitted.append

    identity = TurnIdentity.create(session_id="s-fwd", workspace=str(tmp_path))
    q: queue.Queue = queue.Queue()
    done = threading.Event()
    thread = threading.Thread(
        target=server._forward_events, args=(q, identity, done), daemon=True
    )
    thread.start()
    try:
        q.put({"type": "tool.call", "payload": {"tool_id": "t1"}})
        deadline = time.time() + 5
        while time.time() < deadline and not any(
            e.get("type") == "runtime_degraded" for e in emitted
        ):
            time.sleep(0.02)
        degraded = [e for e in emitted if e.get("type") == "runtime_degraded"]
        assert degraded, f"expected runtime_degraded frame, got {emitted}"
        assert thread.is_alive(), "forwarder thread must not die on projection failure"

        # Forwarder still works for subsequent good events.
        good = {"type": "message.agent.chunk", "payload": {"text": "hi", "thread_id": "s-fwd"}}
        q.put(good)
        deadline = time.time() + 5
        while time.time() < deadline and not any(
            e.get("type") == "token" for e in emitted
        ):
            time.sleep(0.02)
        assert any(e.get("type") == "token" for e in emitted)
    finally:
        done.set()
        thread.join(timeout=2)


# ------------------------------------------------- watchdog env gate (no 60 s wait)

def test_diagnostics_watchdog_env_does_not_break_bridge():
    # With PULSEAI_BRIDGE_DIAGNOSTICS=1 the bridge arms faulthandler around a
    # real turn. The echo runner returns instantly, so we only verify the env
    # wiring is harmless on the transport level (no 60 s wait here).
    proc = _spawn_bridge({"PULSEAI_BRIDGE_RUNNER": "echo", "PULSEAI_BRIDGE_DIAGNOSTICS": "1"})
    try:
        _send(proc, {"type": "hello", "protocol": PROTOCOL_VERSION})
        hello = _read_frames(proc, lambda f: f.get("type") == "hello")[-1]
        assert hello["protocol"] == PROTOCOL_VERSION
        _send(proc, {"type": "session_create", "session_id": "s-wd"})
        _read_frames(proc, lambda f: f.get("type") == "session_info")
        _send(proc, {"type": "prompt", "session_id": "s-wd", "text": "hi"})
        frames = _read_frames(proc, lambda f: f.get("type") == "turn_done")
        assert frames[-1]["completed"] is True
    finally:
        proc.kill()
