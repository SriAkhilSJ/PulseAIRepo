"""Drive the real bridge + Agent Core with the scripted model seam.

Provider-free: no model API. The graph, SafeToolNode approval policy, tool
execution, bridge protocol and persistence are the production path; only the
chat-model client is scripted (CRUSORAI_TEST_MODE=1 + CRUSORAI_TEST_LLM_SCRIPT).

Modes:
  approve  -> answer the real safety_request with approved=true
  deny     -> answer with approved=false
  replay   -> no prompt; ask session_messages for an existing session id
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
    session_id = sys.argv[3] if len(sys.argv) > 3 else "probe-approval-session"

    script = json.dumps([
        {
            "tool_calls": [{
                "name": "write_file",
                "args": {
                    "path": "notes.md",
                    "content": "# Notes\n\nApproval target file.\napproved line\n",
                },
                "id": "call-approved-write-1",
            }]
        },
        {"content": "Wrote notes.md with the approved line."},
    ])

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["CRUSORAI_TEST_MODE"] = "1"
    env["CRUSORAI_TEST_LLM_SCRIPT"] = script
    env["CRUSORAI_TEST_LLM_DEBUG"] = "1"
    env["CRUSORAI_BRIDGE_APPROVAL_POLICY"] = "ask"
    env.pop("CRUSORAI_ORCHESTRATOR_ENGINE", None)
    env.pop("CRUSORAI_BRIDGE_RUNNER", None)
    env.pop("CRUSORAI_ALLOW_LIVE_AGENT_TEST", None)
    env.pop("CRUSORAI_ECHO_DELAY_MS", None)

    proc = subprocess.Popen(
        [str(PYTHON), "-m", "src.bridge"],
        cwd=str(REPO), env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    frames: "queue.Queue[dict]" = queue.Queue()
    stderr_lines: list[str] = []

    def read_out() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                frames.put(json.loads(line))
            except json.JSONDecodeError:
                frames.put({"type": "_unparsed", "line": line[:200]})

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

    report: dict = {"mode": mode, "session_id": session_id, "workspace": str(workspace)}
    send({"type": "hello", "protocol": 2})
    deadline = time.monotonic() + 240
    hello = None
    while time.monotonic() < deadline:
        try:
            frame = frames.get(timeout=0.5)
        except queue.Empty:
            continue
        if frame.get("type") == "hello":
            hello = frame
            break
    report["hello"] = {"protocol": (hello or {}).get("protocol"), "engine": (hello or {}).get("engine")}

    if mode == "replay":
        send({"type": "session_messages", "session_id": session_id, "order": "oldest", "limit": 200})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                frame = frames.get(timeout=0.5)
            except queue.Empty:
                continue
            if frame.get("type") in {"session_messages", "error"}:
                report["session_messages"] = frame
                break
        report["file_content"] = (workspace / "notes.md").read_text(encoding="utf-8") if (workspace / "notes.md").exists() else None
    else:
        send({"type": "session_create", "session_id": session_id, "workspace": str(workspace)})
        send({"type": "prompt", "session_id": session_id, "workspace": str(workspace),
              "text": "Write the approval target line into notes.md", "mode": "agent"})
        approvals = []
        terminal = None
        while time.monotonic() < deadline:
            try:
                frame = frames.get(timeout=0.5)
            except queue.Empty:
                continue
            kind = frame.get("type")
            report.setdefault("frame_types", []).append(kind)
            if kind == "safety_request":
                approvals.append({
                    "tool_id": frame.get("tool_id"),
                    "name": frame.get("name"),
                    "diff": (frame.get("diff") or "")[:400],
                })
                send({"type": "safety_reply", "session_id": session_id,
                      "tool_id": frame.get("tool_id"),
                      "approved": mode == "approve"})
            elif kind in {"turn_done", "turn_failed"}:
                terminal = frame
                break
        report["approvals"] = approvals
        report["terminal"] = {
            "type": (terminal or {}).get("type"),
            "completed": (terminal or {}).get("completed"),
            "cancelled": (terminal or {}).get("cancelled"),
            "message": (terminal or {}).get("message"),
        }
        report["file_content"] = (workspace / "notes.md").read_text(encoding="utf-8") if (workspace / "notes.md").exists() else None
        send({"type": "session_messages", "session_id": session_id, "order": "oldest", "limit": 200})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                frame = frames.get(timeout=0.5)
            except queue.Empty:
                continue
            if frame.get("type") == "session_messages":
                messages = frame.get("messages") or []
                report["messages"] = [
                    {"role": m.get("role"), "text": str(m.get("content") or "")[:160]}
                    for m in messages
                ]
                break

    send({"type": "shutdown"})
    time.sleep(0.4)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    report["bridge_exit"] = proc.returncode
    report["stderr_tail"] = stderr_lines[-30:]
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
