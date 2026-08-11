#!/usr/bin/env python
"""
Test-2 retest (workspace_d) — fresh sandbox, fresh thread.
The agent must build an EaseMize-style chat app from an EMPTY workspace and
NOT declare Finished until the app builds AND is browser-verified.
Exercises: scaffolding pivot, verify gate (typecheck_workspace), browser
verification, and the D-round durability stack on the FreeLLM custom provider.
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

# Autonomous eval: there is no human to answer approval prompts, so
# ordinary file overwrites must be allowed (the agent needs to fix its
# own files). Critical paths (.env, secrets) and dangerous commands
# still block — the guard's real safety rails. D9: without this, every
# tsconfig.json fix was intercepted, the model looped through ask_user
# (no reader), and declared "Finished" on a broken app.
os.environ.setdefault("PULSEAI_AUTO_APPROVE_WRITES", "1")

from src.dashboard.event_bus import event_bus  # noqa: E402
from src.graphs.chat_graph import graph, get_agent_status, stream_agent  # noqa: E402

THREAD = os.environ.get("LAB_THREAD", "lab-chat-d")
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), "workspace_d"))
OUT = os.path.join(os.path.dirname(__file__), os.environ.get("LAB_OUT", "report_chat_runD.json"))

TASK = os.environ.get("LAB_TASK", "") or (
    "Build an EaseMize-style chat application from scratch in this empty "
    "workspace. Deliver a working, browser-verified app — do not declare "
    "Finished until it runs and you have verified it in a real browser.\n"
    "1. Scaffold a Next.js 14 + TypeScript + Tailwind app by writing the "
    "configs yourself (package.json, tsconfig.json, next.config.mjs, "
    "tailwind.config.ts, postcss.config.js, app/globals.css) and run npm "
    "install. (Env note: npx shims are fixed machine-wide now, but writing "
    "files with write_file is always safest — it creates parent dirs.)\n"
    "2. Implement the chat UI: app/layout.tsx, app/page.tsx and components "
    "ChatLayout, MessageList, PromptInput, ChatSidebar, EmptyState, a "
    "markdown renderer, and a streaming mock assistant reply.\n"
    "3. Run the workspace's own type check (typecheck_workspace) and fix "
    "every reported error — syntax and type errors are a hard failure.\n"
    "4. Start the dev server, then verify with the browser tools "
    "(browser_navigate, browser_snapshot, browser_screenshot): the empty "
    "state must render, a typed message must appear, and the assistant "
    "reply must stream.\n"
    "Do not ask questions. Do not summarize. Execute tools immediately. "
    "You may use execute_code to batch steps."
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
