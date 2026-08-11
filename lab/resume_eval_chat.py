#!/usr/bin/env python
"""
Durability + behavior test: resume thread lab-chat-2 in a NEW process with a
hard push. The agent twice declared the task finished without executing any
tool (workspace still empty). This resume must force real execution.
"""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import sys
import time
import traceback

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
os.chdir(REPO)

from src.dashboard.event_bus import event_bus  # noqa: E402
from src.graphs.chat_graph import graph, get_agent_status, stream_agent  # noqa: E402

THREAD = os.environ.get("LAB_THREAD", "lab-chat-2")
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), "workspace_c"))
OUT = os.path.join(os.path.dirname(__file__), os.environ.get("LAB_OUT", "report_chat_resume2.json"))

TASK = os.environ.get("LAB_RESUME_MSG", "") or (

    "You declared the previous task Finished, but you did NOT do the work: "
    "the workspace is STILL EMPTY — no package.json, no source files, nothing "
    "was built. Declaring done without delivering is a hard failure. "
    "Continue the original task RIGHT NOW and do not finish until real files "
    "exist and the app runs:\n"
    "1. Scaffold the Next.js + TypeScript + Tailwind app yourself (write "
    "package.json, tsconfig.json, next.config.mjs, tailwind.config.ts, "
    "postcss.config.js by hand; npm install the deps).\n"
    "2. Write every component: ChatLayout, MessageList, PromptInput, "
    "ChatSidebar, EmptyState, the markdown renderer, and the streaming mock.\n"
    "3. Run the build, start the dev server, and verify the UI in the browser "
    "with the browser tools (browser_navigate, browser_snapshot, "
    "browser_screenshot).\n"
    "Do not ask questions. Do not summarize. Execute tools immediately, "
    "starting with a terminal command or file write."
)


def snapshot_workspace(ws: str) -> dict:
    out = {}
    for p in sorted(pathlib.Path(ws).glob("**/*")):
        if p.is_file() and "node_modules" not in str(p) and "__pycache__" not in str(p):
            out[str(p.relative_to(ws))] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    return out


def main() -> None:
    pre = snapshot_workspace(WORKSPACE)
    events = []
    q = event_bus.subscribe()

    def drain():
        while not q.empty():
            events.append(q.get_nowait())

    buf = io.StringIO()
    t0 = time.perf_counter()
    error = None
    try:
        with contextlib.redirect_stdout(buf):
            final = stream_agent(TASK, thread_id=THREAD, workspace=WORKSPACE)
    except Exception:
        error = traceback.format_exc()
        final = ""
    wall = time.perf_counter() - t0
    drain()
    event_bus.unsubscribe(q)

    status = get_agent_status(THREAD)
    post = snapshot_workspace(WORKSPACE)

    snap = graph.get_state({"configurable": {"thread_id": THREAD}})
    msgs = []
    for m in (snap.values or {}).get("messages", []):
        d = {"type": type(m).__name__, "name": getattr(m, "name", None)}
        c = m.content
        if isinstance(c, str):
            d["content"] = c[:1200] + ("…[TRUNC]" if len(c) > 1200 else "")
        else:
            d["content"] = str(c)[:1200]
        tcs = getattr(m, "tool_calls", None) or []
        d["tool_calls"] = [{"name": tc["name"], "args": json.dumps(tc.get("args", {}))[:400]} for tc in tcs]
        msgs.append(d)

    report = {
        "thread": THREAD,
        "task": TASK,
        "wall_seconds": round(wall, 2),
        "final_response": (final or "")[:3000],
        "error": error,
        "events": [{"type": e["type"], "t_since_start": round(e["timestamp"] - t0, 3), "payload": e["payload"]} for e in events],
        "status": status,
        "workspace_before": pre,
        "workspace_after": post,
        "transcript": msgs,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print("=" * 60)
    print("AGENT STDOUT (live stream capture)")
    print("=" * 60)
    print(buf.getvalue())
    print("=" * 60)
    print(f"WALL TIME: {wall:.2f}s   report -> {OUT}")
    if error:
        print("RUN ERROR:\n", error)


if __name__ == "__main__":
    main()
