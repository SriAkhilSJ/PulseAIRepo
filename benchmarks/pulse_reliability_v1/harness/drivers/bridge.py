"""Bridge driver: drives the PulseAI engine over Bridge Protocol v2 (stdio).

Speaks the newline-delimited JSON protocol implemented in ``src/bridge``.
Two modes:

- ``PULSEAI_BRIDGE_RUNNER=echo`` (the ``echo`` driver kind): deterministic
  test lane, zero model calls — proves the harness pipeline end-to-end.
- default (the ``bridge`` driver kind): the real engine. Requires the
  repository's own Python environment and a configured provider/key for
  model-backed tasks; workspace/context/cancel semantics need no key.

The driver only records frames; it never grades.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from benchmarks.pulse_reliability_v1.harness.drivers.base import (
    Driver,
    DriverCapabilities,
    DriverError,
    TurnSummary,
)
from benchmarks.pulse_reliability_v1.harness.recorder import Recorder, now_ms

HELLO_FRAME = {"type": "hello", "protocol": 2}
TERMINAL_TYPES = frozenset({
    "turn_done", "turn_failed", "error",
})


class BridgeDriver(Driver):
    """Protocol v2 client over a spawned ``python -m src.bridge`` process."""

    def __init__(self, recorder: Recorder, *, python_command: tuple[str, ...] = ("python",),
                 echo: bool = False, echo_delay_ms: int = 0, workspace: str = ""):
        super().__init__(recorder, python_command=python_command)
        self.echo = echo
        self.echo_delay_ms = echo_delay_ms
        self.workspace = workspace
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._lines: list[dict] = []
        self._line_lock = threading.Lock()
        self._session_id = "bench"
        self._greeted = False

    @property
    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            kind="echo" if self.echo else "bridge",
            dom=False,
            processes=False,
            network=False,
            commands=False,
            host_hashes=False,
            engine_events=not self.echo,  # echo emits no engine events
            real_model=not self.echo,
        )

    # -- lifecycle ---------------------------------------------------------

    def _spawn(self) -> None:
        env = dict(os.environ)
        if self.echo:
            env["PULSEAI_BRIDGE_RUNNER"] = "echo"
            if self.echo_delay_ms > 0:
                env["PULSEAI_ECHO_DELAY_MS"] = str(self.echo_delay_ms)
        cmd = (*self.python_command, "-m", "src.bridge")
        # Spawn from the repository root (derived from this file's location),
        # never from the caller's cwd — the harness may run anywhere.
        repo_root = str(Path(__file__).resolve().parents[4])
        self._proc = subprocess.Popen(
            cmd, cwd=repo_root,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_reader.start()

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for raw in self._proc.stdout:
            try:
                frame = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(frame, dict):
                continue
            with self._line_lock:
                self._lines.append(frame)

    def _drain_stderr(self) -> None:
        """Keep the tail of stderr for diagnostics; never blocks a turn."""
        assert self._proc is not None and self._proc.stderr is not None
        tail: list[bytes] = []
        total = 0
        for raw in self._proc.stderr:
            tail.append(raw)
            total += len(raw)
            while len(tail) > 8:
                total -= len(tail.pop(0))
        self._stderr_tail = b"".join(tail)

    def _stderr_preview(self) -> str:
        tail = getattr(self, "_stderr_tail", b"") or b""
        return tail.decode("utf-8", errors="replace")[-1200:]

    def _send(self, frame: dict) -> None:
        if self._proc is None or self._proc.stdin is None or self._proc.poll() is not None:
            raise DriverError("bridge process is not running")
        try:
            self._proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise DriverError(f"bridge stdin closed: {exc}") from exc

    def _collect(self, timeout_s: float, stop_types: frozenset[str] = TERMINAL_TYPES,
                 deadline_ms: int | None = None) -> list[dict]:
        """Drain frames until a stop type arrives or timeout."""
        deadline = time.monotonic() + timeout_s
        out: list[dict] = []
        while time.monotonic() < deadline:
            with self._line_lock:
                if self._lines:
                    out.extend(self._lines)
                    self._lines.clear()
            if out and out[-1].get("type") in stop_types:
                return out
            if deadline_ms is not None and out and any(
                f.get("type") in TERMINAL_TYPES for f in out
            ):
                return out
            time.sleep(0.01)
        if out:
            return out
        preview = self._stderr_preview()
        detail = f"; stderr: {preview}" if preview else ""
        raise DriverError(f"bridge timeout after {timeout_s}s (no frames){detail}")

    # -- Driver API --------------------------------------------------------

    def connect(self, timeout_s: float = 30.0) -> None:
        self.recorder.startup_ms = now_ms()
        self._spawn()
        # The bridge only speaks after the client initiates the handshake.
        self._send(HELLO_FRAME)
        frames = self._collect(timeout_s, stop_types=frozenset({"hello", "error"}))
        for f in frames:
            self.recorder.record_frame(f["type"], f)
        last = frames[-1]
        if last.get("type") == "error":
            raise DriverError(f"bridge handshake failed: {last.get('message')}")
        if last.get("type") != "hello":
            raise DriverError("bridge did not send hello")
        if last.get("protocol") != 2:
            raise DriverError(f"unexpected protocol {last.get('protocol')}")
        self._greeted = True

    def open_workspace(self, root: str) -> None:
        if not self._greeted:
            raise DriverError("connect() before open_workspace()")
        self.workspace = root
        self._send({"type": "session_create", "session_id": self._session_id, "workspace": root})
        frames = self._collect(10.0, stop_types=frozenset({"session_info", "error"}))
        for f in frames:
            self.recorder.record_frame(f["type"], f)
        last = frames[-1]
        if last.get("type") == "error":
            raise DriverError(f"session_create failed: {last.get('message')}")
        if last.get("type") != "session_info":
            raise DriverError("no session_info after session_create")

    def wait_for_frame(self, frame_type: str, timeout_s: float) -> bool:
        """Block until a frame of ``frame_type`` arrives (recorded); used to
        time cancellations mid-turn. Returns True when seen, False on timeout."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._line_lock:
                if self._lines:
                    # Copy-then-clear: batch must not alias the shared list.
                    batch = list(self._lines)
                    self._lines.clear()
                else:
                    batch = []
            for f in batch:
                self.recorder.record_frame(f["type"], f, cancelled=bool(f.get("cancelled")))
                if f.get("type") == "turn_started" and self.recorder.first_progress_ms is None:
                    self.recorder.first_progress_ms = now_ms()
                if f.get("type") == "token" and self.recorder.first_token_ms is None:
                    self.recorder.first_token_ms = now_ms()
                if f.get("type") == frame_type:
                    return True
            time.sleep(0.01)
        return False

    def send_prompt(self, text: str) -> None:
        # Record the client-side prompt frame so checks like
        # ``prompt_count_before_selection`` and ``absent_types`` see the
        # harness's own traffic — evidence of what was sent, not just received.
        self.recorder.record_frame("prompt", {"text": text[:200]})
        # The bridge enforces a workspace on every prompt frame (P0 contract:
        # a session is only ever bound to a real project folder).
        self._send({
            "type": "prompt", "session_id": self._session_id,
            "text": text, "workspace": self.workspace,
        })

    def wait_turn(self, timeout_s: float) -> TurnSummary:
        summary = TurnSummary(started=True)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._line_lock:
                if self._lines:
                    # Copy-then-clear: batch must not alias the shared list.
                    batch = list(self._lines)
                    self._lines.clear()
                else:
                    batch = []
            for f in batch:
                ftype = f.get("type")
                self.recorder.record_frame(ftype, f, cancelled=bool(f.get("cancelled")))
                summary.frames_since.append(f)
                if ftype == "turn_started":
                    summary.started = True
                    if self.recorder.first_progress_ms is None:
                        self.recorder.first_progress_ms = now_ms()
                elif ftype == "token":
                    if summary.first_token_ms is None:
                        summary.first_token_ms = now_ms()
                        self.recorder.first_token_ms = summary.first_token_ms
                elif ftype == "turn_done":
                    summary.completed = bool(f.get("completed"))
                    summary.cancelled = bool(f.get("cancelled"))
                    summary.completion_ms = now_ms()
                    self.recorder.completion_ms = summary.completion_ms
                    return summary
                elif ftype == "turn_failed":
                    raise DriverError(f"turn failed: {f.get('error')}")
                elif ftype == "error":
                    raise DriverError(f"bridge error frame: {f.get('message')}")
            time.sleep(0.01)
        raise DriverError(f"turn did not complete within {timeout_s}s")

    def cancel(self) -> None:
        self.recorder.cancelled_at_ms = now_ms()
        self._send({"type": "cancel", "session_id": self._session_id})
        # The bridge answers cancel with a session_info frame; drain it without
        # blocking the turn's own frames.
        with self._line_lock:
            self._lines.clear()

    def observe_dom(self, selector: str) -> None:
        raise DriverError(
            f"{self.kind} driver cannot observe DOM (needs the desktop CDP lane); "
            f"selector={selector!r}"
        )

    def collect_processes(self) -> None:
        # Host-process observation lives in the desktop lane.
        return

    def shutdown(self, timeout_s: float = 10.0) -> None:
        if self._proc is None:
            return
        try:
            self._send({"type": "shutdown"})
        except DriverError:
            pass
        try:
            self._proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5.0)
        self.recorder.shutdown_ms = now_ms()
        self._proc = None


def driver_from_kind(kind: str, recorder: Recorder, *, python_command: tuple[str, ...] = ("python",),
                     echo_delay_ms: int = 0, workspace: str = "") -> BridgeDriver:
    """Factory: ``echo`` and ``bridge`` both use the BridgeDriver."""
    if kind not in ("echo", "bridge"):
        raise DriverError(f"unknown bridge driver kind {kind!r}")
    return BridgeDriver(
        recorder, python_command=python_command,
        echo=(kind == "echo"), echo_delay_ms=echo_delay_ms, workspace=workspace,
    )
