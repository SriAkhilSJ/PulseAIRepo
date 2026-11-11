"""Bridge lifecycle probe — real ``python -m src.bridge``, zero paid frames.

The probe speaks the repository's own newline-delimited JSON protocol
(``src/bridge/protocol.py``) to the REAL bridge process. It is a client, not a
second protocol implementation: frames are encoded/decoded with the shipped
codec and validated against the shipped frame sets.

Hard safety rule: the probe can only send frames on a small allowlist. Any
frame that could reach a model provider (``prompt``, ``oneshot``,
``subagent_launch``, inline completion, voice transcription, ...) is refused
BEFORE it touches the pipe, so an offline milestone cannot accidentally spend
money.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.bridge.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    decode_line,
    encode,
)


class BridgeProbeError(RuntimeError):
    pass


class PaidCallRefused(BridgeProbeError):
    """The probe was asked to send a frame that can reach a paid provider."""


#: Frames the probe may send. Everything else is refused.
PROBE_ALLOWED_FRAMES = frozenset({
    "hello",
    "session_create",
    "session_load",
    "session_resume",
    "session_list",
    "session_messages",
    "shutdown",
})

#: Frames known to (or able to) trigger a provider dispatch. Refused explicitly
#: so the failure message names the reason instead of "unknown frame".
PAID_FRAME_TYPES = frozenset({
    "prompt",
    "oneshot",
    "subagent_launch",
    "inline_completion",
    "next_edit_suggestions",
    "voice_transcribe",
    "skills_hub_op",
    "safety_reply",
    "clarify_reply",
})


def assert_frame_is_offline(frame: dict[str, Any]) -> None:
    """Fail closed before any frame is written to the bridge."""
    kind = str(frame.get("type") or "")
    if kind in PAID_FRAME_TYPES:
        raise PaidCallRefused(
            f"refusing to send {kind!r}: it can reach a paid model provider "
            "(P0.6.4 permits no provider calls)"
        )
    if kind not in PROBE_ALLOWED_FRAMES:
        raise PaidCallRefused(f"refusing to send {kind!r}: not on the offline probe allowlist")
    if "text" in frame and "prompt" == kind:
        raise PaidCallRefused("refusing prompt text in an offline probe")


def prompt_fingerprint(text: str) -> str:
    """Content hash for prompt correlation — the prompt itself is never stored."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


@dataclass
class BridgeProbeResult:
    python_executable: str = ""
    python_version: str = ""
    engine_root: str = ""
    pid: int = 0
    started_at: float = 0.0
    ended_at: float = 0.0
    exit_code: int | None = None
    frames_in: list[dict[str, Any]] = field(default_factory=list)
    frames_out: list[dict[str, Any]] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    handshake: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    workspace_bound: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "python_executable": self.python_executable,
            "python_version": self.python_version,
            "engine_root": self.engine_root,
            "pid": self.pid,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "runtime_seconds": round(self.ended_at - self.started_at, 3) if self.ended_at else None,
            "exit_code": self.exit_code,
            "frame_counts": {"in": len(self.frames_in), "out": len(self.frames_out)},
            "frames_in": self.frames_in,
            "frames_out": self.frames_out,
            "stderr_line_count": len(self.stderr_lines),
            "stderr_lines": self.stderr_lines[-80:],
            "handshake": self.handshake,
            "session": self.session,
            "workspace_bound": self.workspace_bound,
            "errors": self.errors,
        }


class BridgeProbe:
    """One supervised bridge process, driven over its real stdio protocol."""

    def __init__(self, engine_root: str | os.PathLike[str], *, python: str | None = None) -> None:
        self.engine_root = Path(engine_root).resolve()
        self.python = python or sys.executable
        self._proc: subprocess.Popen | None = None
        self._frames: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr: list[str] = []
        self._readers: list[threading.Thread] = []
        self.result = BridgeProbeResult(engine_root=str(self.engine_root))

    # -- lifecycle ---------------------------------------------------------

    def start(self, *, timeout_s: float = 90.0) -> None:
        bridge_main = self.engine_root / "src" / "bridge" / "__main__.py"
        if not bridge_main.exists():
            raise BridgeProbeError(f"no src/bridge/__main__.py under {self.engine_root}")
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("CRUSORAI_MEMORY", "off")
        self.result.started_at = time.time()
        self._proc = subprocess.Popen(
            [self.python, "-m", "src.bridge"],
            cwd=str(self.engine_root),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.result.pid = self._proc.pid
        self.result.python_executable = self.python
        self.result.python_version = sys.version.split()[0]
        self._readers = [
            threading.Thread(target=self._read_stdout, name="bridge-probe-out", daemon=True),
            threading.Thread(target=self._read_stderr, name="bridge-probe-err", daemon=True),
        ]
        for thread in self._readers:
            thread.start()

    def _read_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        for raw in self._proc.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                frame = decode_line(line)
            except ProtocolError as exc:
                self.result.errors.append(f"undecodable bridge frame: {exc}")
                continue
            self.result.frames_out.append(frame)
            self._frames.put(frame)

    def _read_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        for raw in self._proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self._stderr.append(line)

    # -- protocol ----------------------------------------------------------

    def send(self, frame: dict[str, Any]) -> None:
        assert_frame_is_offline(frame)
        if self._proc is None or self._proc.stdin is None:
            raise BridgeProbeError("bridge process is not running")
        payload = encode(frame)
        self.result.frames_in.append({"type": frame.get("type"), "bytes": len(payload), "at": time.time()})
        self._proc.stdin.write(payload)
        self._proc.stdin.flush()

    def expect(self, frame_type: str, *, timeout_s: float = 90.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            remaining = max(0.2, deadline - time.monotonic())
            try:
                frame = self._frames.get(timeout=remaining)
            except queue.Empty:
                break
            if frame.get("type") == frame_type:
                return frame
            if frame.get("type") == "error":
                self.result.errors.append(str(frame.get("message") or "bridge error frame"))
        raise BridgeProbeError(
            f"bridge never emitted {frame_type!r} within {timeout_s}s "
            f"(stderr tail: {self._stderr[-3:]})"
        )

    def handshake(self, *, timeout_s: float = 90.0) -> dict[str, Any]:
        self.send({"type": "hello", "protocol": PROTOCOL_VERSION})
        hello = self.expect("hello", timeout_s=timeout_s)
        self.result.handshake = hello
        return hello

    def create_session(self, workspace: str, *, timeout_s: float = 60.0) -> dict[str, Any]:
        self.send({"type": "session_create", "workspace": workspace})
        info = self.expect("session_info", timeout_s=timeout_s)
        self.result.session = info
        # workspace.bound is emitted around the first workspace-bearing frame.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                frame = self._frames.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                break
            if frame.get("type") == "workspace.bound":
                self.result.workspace_bound = frame
                break
        return info

    def shutdown(self, *, timeout_s: float = 30.0) -> int | None:
        if self._proc is None:
            return None
        try:
            self.send({"type": "shutdown"})
        except (BridgeProbeError, OSError):
            pass
        try:
            code = self._proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            code = self._proc.wait(timeout=10.0)
        self.result.exit_code = code
        self.result.ended_at = time.time()
        self.result.stderr_lines = list(self._stderr)
        return code

    def terminate(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait(timeout=10.0)
            self.result.ended_at = time.time()
        self.result.stderr_lines = list(self._stderr)

    # -- aggregate ---------------------------------------------------------

    def run_lifecycle(self, workspace: str) -> BridgeProbeResult:
        """Start -> handshake -> session_create -> shutdown. No prompt frames."""
        try:
            self.start()
            self.handshake()
            self.create_session(workspace)
        finally:
            self.shutdown()
        return self.result


def validate_probe_frames(result: BridgeProbeResult) -> dict[str, Any]:
    """Check the observed frames against the shipped protocol contract."""
    hello = result.handshake or {}
    session = result.session or {}
    checks = {
        "hello_engine_is_crusorai": hello.get("engine") == "crusorai",
        "hello_protocol_matches": hello.get("protocol") == PROTOCOL_VERSION,
        "hello_has_engine_version": bool(str(hello.get("engine_version") or "").strip()),
        "hello_capabilities_listed": isinstance(hello.get("capabilities"), list) and bool(hello.get("capabilities")),
        "session_id_minted": bool(str(session.get("session_id") or "").strip()),
        "no_error_frames": not result.errors,
        "no_prompt_frame_sent": not any(
            frame.get("type") in PAID_FRAME_TYPES for frame in result.frames_in
        ),
        "clean_shutdown": result.exit_code == 0,
    }
    return {"checks": checks, "passed": all(checks.values())}


def frame_schema_report(frame: dict[str, Any]) -> dict[str, Any]:
    """Minimal, honest shape report for one bridge frame."""
    return {
        "type": frame.get("type"),
        "has_session_id": bool(frame.get("session_id")),
        "has_turn_id": bool(frame.get("turn_id")),
        "fields": sorted(frame.keys()),
        "bytes": len(json.dumps(frame, ensure_ascii=False)),
    }
