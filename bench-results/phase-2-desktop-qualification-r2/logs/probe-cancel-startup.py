"""Runtime probe for the startup-cancellation contract.

Uses the real bridge with the provider-free echo runner plus the bounded
CRUSORAI_TURN_STARTUP_BARRIER_MS seam so the Stop lands inside the window
between the accepted prompt and turn_controls.begin().
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

REPO = Path(os.environ["CRUSORAI_REPO_ROOT"])
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    workspace = Path(sys.argv[1])
    sid = sys.argv[2]
    barrier_ms = sys.argv[3] if len(sys.argv) > 3 else "3000"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["CRUSORAI_BRIDGE_RUNNER"] = "echo"
    env["CRUSORAI_TURN_STARTUP_BARRIER_MS"] = barrier_ms
    env.pop("CRUSORAI_ALLOW_LIVE_AGENT_TEST", None)

    proc = subprocess.Popen(
        [str(PYTHON), "-m", "src.bridge"], cwd=str(REPO), env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    frames: "queue.Queue[dict]" = queue.Queue()
    stderr_lines: list[str] = []

    def read_out() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line:
                try:
                    frames.put(json.loads(line))
                except json.JSONDecodeError:
                    pass

    def read_err() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line.rstrip()[:300])

    threading.Thread(target=read_out, daemon=True).start()
    threading.Thread(target=read_err, daemon=True).start()

    def send(frame: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(frame) + "\n")
        proc.stdin.flush()

    send({"type": "hello", "protocol": 2})
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            if frames.get(timeout=0.5).get("type") == "hello":
                break
        except queue.Empty:
            continue

    send({"type": "session_create", "session_id": sid, "workspace": str(workspace)})
    send({"type": "prompt", "session_id": sid, "workspace": str(workspace),
          "text": "startup cancel probe", "mode": "agent"})

    # Stop inside the pending window (default barrier 3s).
    time.sleep(0.9)
    send({"type": "cancel", "session_id": sid})

    sequence: list[str] = []
    cancel_acks: list[dict] = []
    terminal = None
    token_texts: list[str] = []
    while time.monotonic() < deadline:
        try:
            frame = frames.get(timeout=0.5)
        except queue.Empty:
            continue
        kind = frame.get("type")
        sequence.append(kind)
        if kind == "session_info" and "cancel_requested" in frame:
            cancel_acks.append({
                "cancel_requested": frame.get("cancel_requested"),
            })
        elif kind == "token":
            token_texts.append(str(frame.get("text") or "")[:80])
        elif kind in {"turn_done", "turn_failed"}:
            terminal = frame
            break

    # Late cancel AFTER the turn ended must be rejected and harmless.
    send({"type": "cancel", "session_id": sid})
    late = None
    late_deadline = time.monotonic() + 20
    while time.monotonic() < late_deadline:
        try:
            frame = frames.get(timeout=0.5)
        except queue.Empty:
            continue
        if frame.get("type") == "session_info" and "cancel_requested" in frame:
            late = frame.get("cancel_requested")
            break

    report = {
        "session_id": sid,
        "barrier_ms": barrier_ms,
        "sequence": sequence,
        "cancel_acks": cancel_acks,
        "token_texts": token_texts,
        "terminal": {
            "type": (terminal or {}).get("type"),
            "completed": (terminal or {}).get("completed"),
            "cancelled": (terminal or {}).get("cancelled"),
            "message": (terminal or {}).get("message"),
        },
        "late_cancel_requested": late,
        "cancel_log": [ln for ln in stderr_lines if "cancel for" in ln],
        "bridge_exit": None,
    }
    send({"type": "shutdown"})
    time.sleep(0.3)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    report["bridge_exit"] = proc.returncode
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
