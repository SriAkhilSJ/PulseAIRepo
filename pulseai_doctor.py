#!/usr/bin/env python3
"""PulseAI delivery doctor — answers ONE question:

    "Is the pushed build actually running on this machine, and which layer
     is holding it back?"

Field context (2026-09-04): four fixes sat on origin while the owner's log
kept showing an older build. Probe lines in stderr are not enough; this
checks every layer of the delivery chain and prints the exact command for
the first broken link.

Run from anywhere:
    python pulseai_doctor.py
"""

from __future__ import annotations

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
BRANCH = "arena/01a06408-pulseairepo"

MARKERS = [
    ("src/graphs/chat_graph.py", "finalize update received", "d1b6c88e (turn probes)"),
    ("src/graphs/chat_graph.py", "journal_mode=WAL", "d1b6c88e (WAL checkpointer)"),
    ("src/bridge/__main__.py", "_engine_build", "6573fe29 (build banner)"),
    ("src/bridge/__main__.py", "_apply_memory_policy", "baf4b332 (memory OFF default)"),
]

RENDERER_OUT = os.path.join(
    "desktop", "vscode", "out", "vs", "workbench", "contrib", "pulseai",
    "browser", "pulseAIRendererService.js",
)
RENDERER_SRC = os.path.join(
    "desktop", "vscode", "src", "vs", "workbench", "contrib", "pulseai",
    "browser", "pulseAIRendererService.ts",
)


def git(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, timeout=30,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except Exception:
        return ""


def main() -> int:
    print("=" * 62)
    print("PulseAI delivery doctor")
    print("=" * 62)

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    head = git("rev-parse", "--short", "HEAD")
    print(f"[1] repo:            {REPO}")
    print(f"    branch:          {branch or '??'}")
    print(f"    HEAD:            {head or '??'}")

    dirty = "\n".join(
        line for line in git("status", "--short").splitlines()
        if "pulseai_doctor.py" not in line
    )
    if dirty:
        print("[2] working tree:    DIRTY (git pull will REFUSE):")
        for line in dirty.splitlines()[:10]:
            print(f"      {line}")
        print("    -> fix:  git stash   (then pull, then: git stash pop)")
    else:
        print("[2] working tree:    clean")

    print(f"[3] fetching origin/{BRANCH} ...")
    git("fetch", "origin", BRANCH)
    origin = git("rev-parse", "--short", f"FETCH_HEAD")
    print(f"    origin tip:      {origin or '?? (offline?)'}")
    need_pull = bool(origin) and origin != head
    if need_pull:
        print(f"    -> YOUR REPO IS {head}, ORIGIN HAS {origin}. PULL REQUIRED:")
        print("       git stash  (only if step [2] said DIRTY)")
        print("       git pull")
    else:
        print("    -> repo is up to date with origin")

    print("[4] code markers on disk (which commits your FILES contain):")
    missing_files = False
    for rel, needle, label in MARKERS:
        path = os.path.join(REPO, rel)
        try:
            hit = needle in open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            hit = False
        state = "OK    " if hit else "MISSING"
        if not hit:
            missing_files = True
        print(f"    [{state}] {label}")

    print("[5] renderer compile state:")
    out_path = os.path.join(REPO, RENDERER_OUT)
    src_path = os.path.join(REPO, RENDERER_SRC)
    if not os.path.exists(out_path):
        print("    [MISSING] compiled renderer not found — run: cd desktop\\vscode && npm run compile")
    else:
        compiled_new = "hardWatchdog" in open(out_path, encoding="utf-8", errors="replace").read()
        out_mtime = os.path.getmtime(out_path)
        src_mtime = os.path.getmtime(src_path)
        stale = out_mtime < src_mtime
        if stale:
            print("    [MISSING] out/ is OLDER than src/ — run: cd desktop\\vscode && npm run compile")
        elif not compiled_new:
            print("    [MISSING] out/ predates baf4b332 (no hardWatchdog) — run: cd desktop\\vscode && npm run compile")
        else:
            print("    [OK    ] compiled renderer includes the latest desktop fixes")

    print("=" * 62)
    if need_pull or missing_files:
        print("VERDICT: the pushed fixes are NOT on this disk yet.")
        print("  1) git stash        (only if step [2] said DIRTY)")
        print(f"  2) git pull origin {BRANCH}")
        print("  3) cd desktop\\vscode && npm run compile")
        print("  4) close ALL VS Code windows (kills the Python engine), reopen")
        print("  5) Pulse panel chip must read: Pulse ready · 544ca201 (or later)")
    else:
        print("VERDICT: disk is current. If the engine STILL shows old behavior,")
        print("  the engine process predates the pull — close ALL VS Code")
        print("  windows and reopen. The panel chip shows the sha of the")
        print("  engine that is actually running.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
