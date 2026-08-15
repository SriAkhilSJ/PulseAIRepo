#!/usr/bin/env python
"""
Lab harness — Test 3 retest (R3) after the P0 gate/CLI-guard fixes.

A fresh copy of the E2 scenario run against the FIXED engine:
  - component sources live in _provided/ (outside the repo, sibling dir),
    so the agent's natural deliverable is copy_file, not 13 shadcn retries;
  - run_terminal has the CI/NO_COLOR env + 120s timeout pivot guard;
  - the finish gate no longer counts terminal/execute_code as "work" and
    nudges with the E2-specific copy_file instruction.

Launch with a raised budget (clamp is now 50):
    AGENT_ITERATION_BUDGET=50 <uv-python> lab/run_eval_test3_retest.py
"""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import sys
import threading
import time
import traceback

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
os.chdir(REPO)

from src.dashboard.event_bus import event_bus  # noqa: E402
from src.graphs.chat_graph import graph, get_agent_status, stream_agent  # noqa: E402

THREAD = "lab-test4-retest-final"
# Sandbox lives OUTSIDE the repo (sibling folder) so the repo map / chunk
# index never sees the PulseAIRepo tree — the agent only sees the sandbox.
WORKSPACE = os.path.abspath(os.path.join(REPO, "..", "test4_ws_retest"))
OUT = os.path.join(os.path.dirname(__file__), "report_test4_retest.json")
LIVE = os.path.join(os.path.dirname(__file__), "test4_retest_live.log")

TASK = """Create four premium full-screen Video Hero showcase routes in a fresh Next.js 16 + React 19 + TypeScript + Tailwind v4 project:
- `/nature`: forest/ocean immersion
- `/still-life`: ceramics/glassware
- `/materials`: leather/fabric textures
- `/metal-parts`: cinematic gears/machined metal

Use the approved six-step plan already attached. Follow the current runtime phase exactly; do not inspect generated boilerplate or package metadata.

Architecture and design:
- A data-driven `src/lib/themes.ts` with four distinct real high-quality remote MP4 sources and theme content.
- A reusable client `src/components/VideoHero.tsx` with premium shared navigation, current-theme state, editorial label, minimalist title, supporting copy, and primary/secondary CTA treatments.
- A dynamic `src/app/[theme]/page.tsx` validating exactly those four slugs, plus a premium `src/app/page.tsx` theme index.
- Distinct palettes, typography treatment, overlays, texture/light/shadow art direction, and responsive compositions. Avoid generic template styling and avoid external web fonts.
- Every route loads only its own video and uses autoPlay, muted, loop, playsInline, preload="metadata", poster/loading fallback, aria-label, and prefers-reduced-motion behavior. The fallback must remain visually rich while video loads.
- Tailwind v4 is already available after scaffold. Do not install icon libraries; use restrained inline SVG/CSS if needed.

Efficiency and verification:
- Delivery responses are intentionally limited to two files; continue to the next plan step without narration.
- Run typecheck_workspace once after all six source files land; use one targeted repair batch only if diagnostics require it.
- Call verify_ui_routes exactly once with command `npm run dev -- --hostname 0.0.0.0 --port 3000`, base_url `http://127.0.0.1:3000`, routes [`/nature`,`/still-life`,`/materials`,`/metal-parts`], screenshot_prefix `test4-video-hero`, required_selector `video`.
- Finish only on 4/4 playback-ready videos, non-empty snapshots, and four VISUAL QUALITY PASSED screenshots.
"""

INITIAL_PLAN = [
    {"id": 1, "description": "Scaffold a fresh Next.js TypeScript Tailwind project with scaffold_nextjs", "status": "in_progress"},
    {"id": 2, "description": "Create `src/lib/themes.ts` and `src/components/VideoHero.tsx`", "status": "pending"},
    {"id": 3, "description": "Create `src/app/[theme]/page.tsx` and `src/app/page.tsx`", "status": "pending"},
    {"id": 4, "description": "Update `src/app/globals.css` and `src/app/layout.tsx`", "status": "pending"},
    {"id": 5, "description": "Run typecheck_workspace and fix every error", "status": "pending"},
    {"id": 6, "description": "Verify all four browser routes and screenshots with verify_ui_routes", "status": "pending"},
]


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
    stop = threading.Event()

    def drain() -> None:
        with open(LIVE, "a", encoding="utf-8") as lf:
            while not stop.is_set():
                try:
                    ev = q.get(timeout=0.25)
                except Exception:
                    continue
                events.append(ev)
                try:
                    lf.write(json.dumps({
                        "t_since_start": round(ev.get("timestamp", time.time()) - t0, 3),
                        "type": ev["type"],
                        "payload": ev.get("payload"),
                    }, default=str)[:4000] + "\n")
                    lf.flush()
                except Exception:
                    pass

    t0 = time.perf_counter()
    d = threading.Thread(target=drain, daemon=True)
    d.start()

    # Sandbox cwd: the agent's tools must see the workspace, never the repo root.
    os.chdir(WORKSPACE)

    buf = io.StringIO()
    error = None
    try:
        with contextlib.redirect_stdout(buf):
            final = stream_agent(TASK, thread_id=THREAD, workspace=WORKSPACE, initial_plan=INITIAL_PLAN)
    except Exception:
        error = traceback.format_exc()
        final = ""
    wall = time.perf_counter() - t0
    stop.set()
    d.join(timeout=3)
    event_bus.unsubscribe(q)

    status = get_agent_status(THREAD)
    post = snapshot_workspace(WORKSPACE)

    try:
        snap = graph.get_state({"configurable": {"thread_id": THREAD}})
    except Exception:
        snap = None
    msgs = []
    for m in ((snap.values or {}).get("messages", []) if snap else []):
        dct = {"type": type(m).__name__, "name": getattr(m, "name", None)}
        c = m.content
        if isinstance(c, str):
            dct["content"] = c[:1200] + ("…[TRUNC]" if len(c) > 1200 else "")
        else:
            dct["content"] = str(c)[:1200]
        tcs = getattr(m, "tool_calls", None) or []
        dct["tool_calls"] = [
            {"name": tc["name"], "args": json.dumps(tc.get("args", {}))[:400]}
            for tc in tcs
        ]
        msgs.append(dct)

    report = {
        "thread": THREAD,
        "task": TASK,
        "wall_seconds": round(wall, 2),
        "final_response": (final or "")[:3000],
        "error": error,
        "status": status,
        "iteration_budget_env": os.environ.get("AGENT_ITERATION_BUDGET"),
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