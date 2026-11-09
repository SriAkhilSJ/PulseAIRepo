"""Bridge-level proof: the default orchestrator asks a human before mutating.

Provider-free: CRUSORAI_ORCHESTRATOR_MOCK=1 selects the orchestrator's
deterministic local code generator. The graph, bridge, ApprovalQueue, protocol
safety_request/safety_reply, risk token and mutation broker are the production
paths.

Modes: approve | deny | timeout | cancel
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
    mode = sys.argv[1]
    workspace = Path(sys.argv[2])
    sid = sys.argv[3]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["CRUSORAI_ORCHESTRATOR_MOCK"] = "1"
    env["CRUSORAI_BRIDGE_APPROVAL_POLICY"] = "ask"
    env["CRUSORAI_PREVIEW_AUTOSTART"] = "0"
    if mode == "timeout":
        env["CRUSORAI_APPROVAL_TIMEOUT_S"] = "2"
    env.pop("CRUSORAI_BRIDGE_RUNNER", None)
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
            stderr_lines.append(line.rstrip()[:400])

    threading.Thread(target=read_out, daemon=True).start()
    threading.Thread(target=read_err, daemon=True).start()

    def send(frame: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(frame) + "\n")
        proc.stdin.flush()

    send({"type": "hello", "protocol": 2})
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if frames.get(timeout=0.5).get("type") == "hello":
                break
        except queue.Empty:
            continue

    send({"type": "session_create", "session_id": sid, "workspace": str(workspace)})
    send({"type": "prompt", "session_id": sid, "workspace": str(workspace),
          "text": "Create notes.md with a short greeting for the project.", "mode": "agent"})

    sequence: list[str] = []
    approvals: list[dict] = []
    terminal = None
    sent_cancel = False
    while time.monotonic() < deadline:
        try:
            frame = frames.get(timeout=0.5)
        except queue.Empty:
            continue
        kind = frame.get("type")
        sequence.append(kind)
        if kind == "safety_request":
            approvals.append({
                "tool_id": frame.get("tool_id"),
                "name": frame.get("name"),
                "arguments": frame.get("arguments"),
                "warning": frame.get("warning"),
            })
            if mode == "approve":
                send({"type": "safety_reply", "session_id": sid,
                      "tool_id": frame.get("tool_id"), "approved": True})
            elif mode in {"deny", "timeout"}:
                if mode == "deny":
                    send({"type": "safety_reply", "session_id": sid,
                          "tool_id": frame.get("tool_id"), "approved": False})
                # timeout: do not answer; the configured timeout resolves it
            elif mode == "cancel":
                send({"type": "cancel", "session_id": sid})
                sent_cancel = True
        elif kind in {"turn_done", "turn_failed"}:
            terminal = frame
            break

    report = {
        "mode": mode,
        "session_id": sid,
        "workspace": str(workspace),
        "sequence": sequence,
        "approvals": approvals,
        "terminal": {
            "type": (terminal or {}).get("type"),
            "completed": (terminal or {}).get("completed"),
            "cancelled": (terminal or {}).get("cancelled"),
            "message": (terminal or {}).get("message"),
            "error": (terminal or {}).get("error"),
        },
        "files": sorted(p.name for p in workspace.iterdir() if p.is_file()),
        "notes_exists": (workspace / "notes.md").exists(),
        "notes_head": (
            (workspace / "notes.md").read_text(encoding="utf-8", errors="replace")[:240]
            if (workspace / "notes.md").exists() else None
        ),
        "cancel_sent": sent_cancel,
        "approval_log": [ln for ln in stderr_lines if "orchestrator-approval" in ln or "approval" in ln][-12:],
        "stderr_tail": stderr_lines[-15:],
    }
    send({"type": "shutdown"})
    time.sleep(0.3)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    report["bridge_exit"] = proc.returncode
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
