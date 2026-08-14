#!/usr/bin/env python
"""
Resume driver for Test 3 E2 (thread lab-test3-e2).

The first pass exhausted its iteration budget after scaffolding the Next/TS/
Tailwind project and installing three/@react-three/drei/@react-three/fiber,
but before placing the components (it burned iterations on the interactive
shadcn CLI). This resumes the SAME thread with a targeted tester nudge; the
checkpointer preserves the whole context (plan, scaffold, deps).

Run with a raised iteration budget so the exhausted counter (30/30) gets
headroom: AGENT_ITERATION_BUDGET=45.
"""
import contextlib
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

from src.graphs.chat_graph import get_agent_status, stream_agent  # noqa: E402

THREAD = "lab-test3-e2"
WORKSPACE = os.path.abspath(os.path.join(REPO, "..", "test3_ws_e2"))
OUT = os.path.join(os.path.dirname(__file__), "report_test3_e2_resume.json")

NUDGE = (
    "[Tester] Your iteration budget was exhausted before the integration "
    "finished — the Next.js/TypeScript/Tailwind scaffold is complete and the "
    "three.js deps (three, @react-three/drei, @react-three/fiber) are already "
    "installed. The shadcn CLI cannot run interactively in this headless "
    "environment (it prompts for a component library), so do NOT retry it. "
    "Finish the task now: (1) create src/components/ui/, (2) use copy_file to "
    "copy _provided/hero-futuristic.tsx and _provided/demo.tsx into "
    "src/components/ui/ byte-for-byte, (3) run typecheck_workspace and fix "
    "what is reasonably fixable, (4) finish with a short summary. Do NOT "
    "re-scaffold, do NOT re-run npm install, do NOT touch node_modules."
)


def main() -> None:
    buf = io.StringIO()
    t0 = time.perf_counter()
    error = None
    # Sandbox cwd: .env already loaded at import (cwd was the repo); now make
    # execute_code/run_terminal see the workspace, never the repo root.
    os.chdir(WORKSPACE)
    try:
        with contextlib.redirect_stdout(buf):
            final = stream_agent(NUDGE, thread_id=THREAD, workspace=WORKSPACE)
    except Exception:
        error = traceback.format_exc()
        final = ""
    wall = time.perf_counter() - t0

    status = get_agent_status(THREAD)
    report = {
        "thread": THREAD,
        "wall_seconds": round(wall, 2),
        "final_response": (final or "")[:4000],
        "error": error,
        "status": status,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print("=" * 60)
    print("RESUME STDOUT")
    print("=" * 60)
    print(buf.getvalue())
    print("=" * 60)
    print(f"WALL: {wall:.2f}s  -> {OUT}")
    if error:
        print("ERROR:\n", error)


if __name__ == "__main__":
    main()
