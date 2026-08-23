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
import tempfile
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
    """Spawn the real sidecar with stderr drained by a dedicated thread.

    The stdout reader thread is created eagerly at spawn (not lazily on the
    first read): probing showed a lazy reader combined with a single blocking
    queue.get() intermittently loses frames on Windows text-mode pipes, while
    an eager reader with short polling timeouts is stable across many runs.

    stderr is drained into a tempfile.TemporaryFile() so the suite has no
    dependency on local scratch directories like .freebuff/ (gitignored, and
    absent from a clean checkout). _stop_bridge() must be called to reap the
    process, close the pipes, and discard the temp stderr sink.
    """
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    if env_extra:
        env.update(env_extra)
    # Binary pipes: probing showed text-mode (TextIOWrapper) pipes on Windows
    # intermittently lose frames the child provably wrote when children are
    # spawned/killed repeatedly, while binary pipes were stable across many
    # runs. The reader decodes UTF-8 lines itself.
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.bridge"],
        cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    err_file = tempfile.TemporaryFile()
    err_drain = threading.Thread(
        target=lambda: [err_file.write(line) for line in proc.stderr],
        daemon=True,
        name="bridge-stderr-drain",
    )
    err_drain.start()
    _READERS[proc] = _FrameReader(proc)
    _SPAWNS[proc] = {"err_file": err_file, "err_drain": err_drain}
    return proc


def _stop_bridge(proc) -> None:
    """Reap a spawned bridge and release every resource it holds.

    Kills the child if needed, waits for exit, joins the stderr drain thread,
    closes the stdin/stdout/stderr handles, drops the reader/spawn state, and
    discards the temporary stderr sink. Safe to call twice.
    """
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    _READERS.pop(proc, None)
    state = _SPAWNS.pop(proc, None)
    if state:
        state["err_drain"].join(timeout=2)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass
        try:
            state["err_file"].close()
        except OSError:
            pass


def _send(proc, frame: dict) -> None:
    proc.stdin.write(json.dumps(frame).encode("utf-8") + b"\n")
    proc.stdin.flush()


class _FrameReader:
    """Dedicated stdout reader thread feeding a queue.

    subprocess pipes cannot use select() on Windows, so the blocking
    readline() must run on its own thread; _read_frames() then waits with a
    real queue timeout that is actually enforceable.
    """

    def __init__(self, proc):
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._drain, args=(proc,), daemon=True,
            name="bridge-stdout-reader",
        )
        self._thread.start()

    def _drain(self, proc):
        try:
            for line in proc.stdout:
                self._q.put(line.decode("utf-8", errors="backslashreplace"))
        except Exception as exc:
            self._q.put(exc)
            raise
        finally:
            self._q.put(None)  # EOF sentinel

    def get(self, timeout: float) -> str:
        try:
            line = self._q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"no stdout line within {timeout:.1f}s")
        if line is None:
            raise RuntimeError("bridge closed stdout early")
        if isinstance(line, BaseException):
            raise RuntimeError(f"stdout reader thread died: {type(line).__name__}: {line}")
        return line


# Keyed by the Popen object, not proc.pid: PIDs get recycled on Windows, and
# a stale reader bound to a dead process's pipes would silently swallow frames.
_READERS: dict[subprocess.Popen, _FrameReader] = {}

# Per-spawn stderr drain state (tempfile sink + drain thread), reaped by _stop_bridge.
_SPAWNS: dict[subprocess.Popen, dict] = {}


def _read_frames(proc, predicate, timeout: float = 20.0):
    """Read stdout lines until predicate(frame) is True; return all frames seen.

    Polls the reader queue in short slices (never one long blocking get):
    probing on Windows showed a single queue.get(timeout=remaining) with a
    lazily-started reader intermittently never delivers frames that the child
    provably wrote, while short-polling an eagerly-started reader is stable.

    NOTE: never use dict.setdefault(proc, _FrameReader(proc)) here. setdefault
    eagerly evaluates its default argument, so every call would construct a NEW
    _FrameReader -- spawning another thread draining the same pipe -- even when
    the dict already has one. Those discarded duplicate readers race the primary
    one for frames and silently swallow them (the root cause of the flake).
    """
    reader = _READERS.get(proc)
    if reader is None:
        reader = _FrameReader(proc)
        _READERS[proc] = reader
    deadline = time.time() + timeout
    frames = []
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(
                f"no matching frame within {timeout}s; saw: {[f.get('type') for f in frames]}"
            )
        try:
            line = reader.get(min(remaining, 0.25))
        except TimeoutError:
            continue
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

def test_echo_turn_emits_progress_then_turn_done(tmp_path):
    proc = _spawn_bridge({"PULSEAI_BRIDGE_RUNNER": "echo"})
    try:
        _send(proc, {"type": "hello", "protocol": PROTOCOL_VERSION})
        hello = _read_frames(proc, lambda f: f.get("type") == "hello")[-1]
        assert hello["protocol"] == PROTOCOL_VERSION

        _send(proc, {"type": "session_create", "session_id": "s-echo", "workspace": str(tmp_path)})
        _read_frames(proc, lambda f: f.get("type") == "session_info")
        # (the bind also emits an async workspace.bound frame — drain it)
        _read_frames(proc, lambda f: f.get("type") == "workspace.bound")

        _send(proc, {"type": "prompt", "session_id": "s-echo", "workspace": str(tmp_path), "text": "hello"})
        frames = _read_frames(proc, lambda f: f.get("type") == "turn_done")
        kinds = [f["type"] for f in frames if f["type"] != "workspace.bound"]
        assert kinds[0] == "turn_started", kinds
        assert "token" in kinds, kinds
        assert kinds[-1] == "turn_done", kinds
        assert frames[-1]["completed"] is True
    finally:
        _stop_bridge(proc)


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


# ------------------------------------------------- 7. timeout is enforceable

def test_read_frames_enforces_timeout_when_child_is_silent():
    """A child that never emits a frame must TimeoutError within the bound.

    Regression: the old _read_frames() called proc.stdout.readline() which
    blocks indefinitely past the deadline, so timeouts were cosmetic.
    """
    proc = _spawn_bridge({"PULSEAI_BRIDGE_RUNNER": "echo"})
    try:
        t0 = time.time()
        with pytest.raises(TimeoutError):
            _read_frames(proc, lambda f: f.get("type") == "never", timeout=3.0)
        elapsed = time.time() - t0
        assert elapsed < 6.0, f"timeout not enforced; took {elapsed:.1f}s"
    finally:
        _stop_bridge(proc)


# ------------------------------------------------- 8. watchdog cancelled after a successful turn

def test_watchdog_is_cancelled_after_successful_echo_turn(monkeypatch):
    """A successful short turn must cancel the scheduled faulthandler dump.

    Regression: faulthandler.dump_traceback_later() returns None, so the old
    `if watchdog is not None: cancel(...)` never ran, leaking a scheduled dump
    that could fire later on unrelated stacks. Track the flag explicitly.
    """
    calls: list[str] = []

    import faulthandler

    monkeypatch.setattr(faulthandler, "dump_traceback_later", lambda *a, **k: calls.append("arm"))
    monkeypatch.setattr(faulthandler, "cancel_dump_traceback_later", lambda: calls.append("cancel"))
    monkeypatch.setenv("PULSEAI_BRIDGE_DIAGNOSTICS", "1")
    monkeypatch.setenv("PULSEAI_BRIDGE_RUNNER", "echo")

    emitted: list[dict] = []
    server = object.__new__(BridgeServer)
    server.emit = emitted.append
    server._shutdown = threading.Event()

    server._run_turn("s-wd", "hi", ".")

    assert calls == ["arm", "cancel"], f"watchdog must be armed then cancelled: {calls}"
    assert emitted[-1]["type"] == "turn_done"


def test_watchdog_is_cancelled_after_successful_real_turn(monkeypatch, tmp_path):
    """Same guarantee for the real (non-echo) path, with a stubbed graph."""
    calls: list[str] = []

    import faulthandler

    monkeypatch.setattr(faulthandler, "dump_traceback_later", lambda *a, **k: calls.append("arm"))
    monkeypatch.setattr(faulthandler, "cancel_dump_traceback_later", lambda: calls.append("cancel"))
    monkeypatch.setenv("PULSEAI_BRIDGE_DIAGNOSTICS", "1")
    monkeypatch.delenv("PULSEAI_BRIDGE_RUNNER", raising=False)

    # Avoid the real model call: stub stream_agent inside the real module.
    import src.graphs.chat_graph as chat_graph

    original = chat_graph.stream_agent

    def fake_stream_agent(*args, **kwargs):
        return {"content": "stub-ok", "role": "assistant"}

    chat_graph.stream_agent = fake_stream_agent
    try:
        emitted: list[dict] = []
        server = object.__new__(BridgeServer)
        server.emit = emitted.append
        server._shutdown = threading.Event()
        server._run_turn("s-wd-real", "hi", str(tmp_path))
    finally:
        chat_graph.stream_agent = original

    assert calls == ["arm", "cancel"], f"watchdog must be armed then cancelled: {calls}"
    assert emitted[-1]["type"] == "turn_done"


# ------------------------------------------------- watchdog env gate (no 60 s wait)

def test_diagnostics_watchdog_env_does_not_break_bridge(tmp_path):
    # With PULSEAI_BRIDGE_DIAGNOSTICS=1 the bridge arms faulthandler around a
    # real turn. The echo runner returns instantly, so we only verify the env
    # wiring is harmless on the transport level (no 60 s wait here).
    proc = _spawn_bridge({"PULSEAI_BRIDGE_RUNNER": "echo", "PULSEAI_BRIDGE_DIAGNOSTICS": "1"})
    try:
        _send(proc, {"type": "hello", "protocol": PROTOCOL_VERSION})
        hello = _read_frames(proc, lambda f: f.get("type") == "hello")[-1]
        assert hello["protocol"] == PROTOCOL_VERSION
        _send(proc, {"type": "session_create", "session_id": "s-wd", "workspace": str(tmp_path)})
        _read_frames(proc, lambda f: f.get("type") == "session_info")
        _send(proc, {"type": "prompt", "session_id": "s-wd", "workspace": str(tmp_path), "text": "hi"})
        frames = _read_frames(proc, lambda f: f.get("type") == "turn_done")
        assert frames[-1]["completed"] is True
    finally:
        _stop_bridge(proc)
