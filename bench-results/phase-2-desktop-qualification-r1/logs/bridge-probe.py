"""Bounded protocol-v2 probe against the real Python bridge.

Spawns `python -m src.bridge` with the provider-free echo runner, performs the
v2 handshake, creates a session bound to a disposable workspace, runs one
deterministic turn, then requests replay + transcript and reports duplicate
event ids. No provider calls, no production source changes.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

REPO = Path(r"<REPO>")
WORKSPACE = Path(sys.argv[1])
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["CRUSORAI_BRIDGE_RUNNER"] = "echo"
    env.pop("CRUSORAI_ALLOW_LIVE_AGENT_TEST", None)
    proc = subprocess.Popen(
        [str(PYTHON), "-m", "src.bridge"],
        cwd=str(REPO),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    frames: "queue.Queue[dict]" = queue.Queue()
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                frames.put(json.loads(line))
            except json.JSONDecodeError:
                frames.put({"type": "_unparsed", "line": line[:400]})

    def read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line.rstrip()[:400])

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()

    def send(frame: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(frame) + "\n")
        proc.stdin.flush()

    def collect(until_types: set[str], timeout: float) -> list[dict]:
        got: list[dict] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                frame = frames.get(timeout=0.25)
            except queue.Empty:
                continue
            got.append(frame)
            if frame.get("type") in until_types:
                break
        return got

    sid = "probe-" + uuid.uuid4().hex[:16]
    report: dict = {"session_id": sid, "workspace": str(WORKSPACE)}

    send({"type": "hello", "protocol": 2})
    hello = collect({"hello"}, 180)
    report["hello"] = next((f for f in hello if f.get("type") == "hello"), None)

    send({"type": "session_create", "session_id": sid, "workspace": str(WORKSPACE)})
    created = collect({"session_info", "error"}, 60)
    report["session_create"] = [f for f in created if f.get("type") in {"session_info", "error"}][:2]

    send({"type": "prompt", "session_id": sid, "workspace": str(WORKSPACE), "text": "bridge protocol probe", "mode": "agent"})
    turn = collect({"turn_done", "turn_failed"}, 180)
    report["turn_types"] = [f.get("type") for f in turn if isinstance(f.get("type"), str)]
    report["turn_done"] = next((f for f in turn if f.get("type") in {"turn_done", "turn_failed"}), None)
    report["errors"] = [f for f in created + turn if f.get("type") == "error"]
    bound = [f for f in turn + created if f.get("type") == "workspace.bound"]
    report["workspace_bound"] = bound[-1] if bound else None
    tokens = [f for f in turn if f.get("type") == "token"]
    report["token_count"] = len(tokens)
    report["token_text"] = tokens[0].get("text") if tokens else None

    send({"type": "events_replay", "session_id": sid})
    replay = collect({"events_replay", "error"}, 60)
    replay_frame = next((f for f in replay if f.get("type") == "events_replay"), None)
    events = (replay_frame or {}).get("events") or []
    ids = [e.get("event_id") for e in events if isinstance(e, dict) and e.get("event_id")]
    report["replay_event_count"] = len(events)
    report["replay_event_id_count"] = len(ids)
    report["replay_duplicate_event_ids"] = len(ids) - len(set(ids))

    send({"type": "session_messages", "session_id": sid, "order": "oldest", "limit": 100})
    msgs = collect({"session_messages", "error"}, 60)
    msg_frame = next((f for f in msgs if f.get("type") == "session_messages"), None)
    messages = (msg_frame or {}).get("messages") or []
    report["session_message_count"] = len(messages)
    report["session_message_roles"] = [m.get("role") for m in messages if isinstance(m, dict)]

    send({"type": "shutdown"})
    time.sleep(0.5)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    report["bridge_exit_code"] = proc.returncode
    report["stderr_tail"] = stderr_lines[-12:]
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
