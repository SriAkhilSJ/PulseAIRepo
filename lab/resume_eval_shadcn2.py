#!/usr/bin/env python
"""Durability test: resume thread lab-shadcn-2 in a NEW process and try to finish."""
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

THREAD = "lab-shadcn-2"
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), "workspace_b"))
OUT = os.path.join(os.path.dirname(__file__), "report_shadcn_resume2.json")

TASK = (
    "Continue the task. You successfully wrote package.json and started npm "
    "install, but the machine's C: drive ran out of disk space and the "
    "session crashed (environment issue — space has been freed, and npm's "
    "cache plus the session checkpoints now point to the D: drive, so "
    "installs can proceed). Resume: finish installing dependencies with "
    "npm install, then create the remaining component files exactly as the "
    "task specified (/components/ui: splite.tsx, demo.tsx, card.tsx — "
    "spotlight.tsx and lib/utils.ts already exist), and verify what you can."
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
        d["tool_calls"] = [
            {"name": tc["name"], "args": json.dumps(tc.get("args", {}))[:400]}
            for tc in tcs
        ]
        msgs.append(d)

    report = {
        "thread": THREAD,
        "task": TASK,
        "resumed_from": "lab-shadcn-2 (prior process)",
        "wall_seconds": round(wall, 2),
        "final_response": (final or "")[:3000],
        "error": error,
        "events": [
            {"type": e["type"], "t_since_start": round(e["timestamp"] - t0, 3),
             "payload": e["payload"]}
            for e in events
        ],
        "status": status,
        "workspace_before": pre,
        "workspace_after": post,
        "transcript": msgs,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print("=" * 60)
    print("AGENT STDOUT")
    print("=" * 60)
    print(buf.getvalue())
    print("=" * 60)
    print(f"WALL TIME: {wall:.2f}s   report -> {OUT}")
    if error:
        print("RUN ERROR tail:\n", error[-800:])


if __name__ == "__main__":
    main()
