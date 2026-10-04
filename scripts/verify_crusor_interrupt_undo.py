#!/usr/bin/env python3
"""Keyless host check for the 2026-10-04 interrupt/undo round.

Run it on your laptop right after the pull, BEFORE you launch: it proves the
thing you are about to test is (a) the commit that was pushed, (b) present in
the *shipped* panel under `desktop/vscode/out/` — the tree the running app
actually loads, not just the TypeScript sources — and (c) free of the
vocabulary this round deliberately removed.

What it cannot prove: that the UI renders. Only your eyes in the app can do
that (see CRUSOR_INTERRUPT_UNDO_HOST_TEST.md §5). This script answers the
question that comes first: "am I looking at the right build?"

    python scripts/verify_crusor_interrupt_undo.py

Stdlib only; any Python 3.9+. Exit 0 = every check passed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORK = ROOT / "desktop" / "vscode"
OUTB = FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai" / "browser"
SRCB = FORK / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "browser"

# The two commits this round shipped. The tip may move; these must stay
# ancestors, so a later local commit on top does not turn this check red.
ROUND_COMMITS = ("226d742c", "47bcdf6e")

# New feature classes the renderer builds AND the stylesheet styles. A class
# in one but not the other is the classic "shipped half the feature" shape.
CLASSES = [
    "crusorai-send-brake",
    "crusorai-brake-glyph",
    "crusorai-cut",
    "crusorai-checkpoint-line",
    "crusorai-checkpoint-hair",
    "crusorai-checkpoint-action",
    "crusorai-checkpoint-actions",
    "crusorai-checkpoint-hash",
    "crusorai-checkpoint-restored",
    "crusorai-checkpoint-log",
    "crusorai-checkpoint-log-row",
    "crusorai-checkpoint-log-head",
    "crusorai-checkpoint-log-note",
    "crusorai-checkpoint-log-reason",
    "crusorai-checkpoint-log-time",
    "crusorai-inline-confirm",
    "crusorai-inline-confirm-yes",
    "crusorai-inline-confirm-no",
    "crusorai-queued-chip",
    "crusorai-queued-note",
    "crusorai-turn-ledger",
    "crusorai-ledger-action",
    "crusorai-file-undo",
    "crusorai-changed-file-new",
    "crusorai-workingset",
    "crusorai-workingset-label",
    "crusorai-verdict-square",
    "crusorai-request-row",
]

# Copy the user dictated, and the string the pane chip must read out loud.
RENDERER_TOKENS = [
    "Interrupt — stops now",
    "Esc to interrupt",
    "Interrupted.",  # the label the instant the pull lands
    "Undo turn",
    "Put it back",
    "Fork from here",
    "Undo All Edits",
    "CRUSORAI_UI_STAMP = '2026-10-04'",
]

# Words this round removed on purpose. If any is back, the wind-down has
# crept into the brake and the round is not the one that was pushed.
REJECTED = ["stopping", "safely", "Run cancelled"]

failures: list[str] = []
warnings: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout or p.stderr).strip()


print(f"checkout: {ROOT}\n")

# --- 1. the pull landed ------------------------------------------------------
print("1. git")
for sha in ROUND_COMMITS:
    code, _ = git("merge-base", "--is-ancestor", sha, "HEAD")
    check(code == 0, f"commit {sha} is in your history", "run: git pull --ff-only")
code, branch = git("rev-parse", "--abbrev-ref", "HEAD")
print(f"  branch: {branch}")
code, dirty = git("status", "--porcelain", "--", "desktop/vscode/out")
check(not dirty, "desktop/vscode/out is exactly the committed panel (no local rebuild on top)",
      f"local rebuilds present:\n{dirty}\n         fix: git checkout -- desktop/vscode/out")
code, _ = git("diff", "--quiet", "HEAD")
if code != 0:
    warnings.append("working tree has tracked modifications outside out/ — keep them, but say so when you report")

# --- 2. the sources are this round's ----------------------------------------
print("\n2. sources (src/)")
renderer_ts = read(SRCB / "crusorAIRenderer.ts")
css_ts = read(SRCB / "media" / "crusorAI.css")
for token in RENDERER_TOKENS:
    check(token in renderer_ts, f"renderer has {token!r}")
for word in REJECTED:
    check(word not in renderer_ts, f"renderer is free of {word!r} (removed on purpose)")
for cls in CLASSES:
    check(cls in renderer_ts and cls in css_ts, f"class {cls} built and styled")

# --- 3. the panel the app loads is the same round ----------------------------
print("\n3. shipped panel (desktop/vscode/out/)")
js = read(OUTB / "crusorAIRenderer.js")
svc = read(OUTB / "crusorAIRendererService.js")
css = read(OUTB / "media" / "crusorAI.css")
check(bool(js), "crusorAIRenderer.js is present in out/")
for token in RENDERER_TOKENS:
    check(token in js, f"shipped JS has {token!r}")
for word in REJECTED:
    check(word not in js, f"shipped JS is free of {word!r}")
for cls in CLASSES:
    check(cls in js and cls in css, f"shipped class {cls} present in JS and CSS")
check("checkpoint_restore" in svc, "shipped service knows the checkpoint_restore frame")

h = read(OUTB / "SOURCES_HASH").strip()
try:
    manifest = json.loads(read(OUTB / "SOURCES_MANIFEST.json") or "{}")
except json.JSONDecodeError:
    manifest = {}
check(bool(h), f"SOURCES_HASH present ({h[:12]}…)")
check(manifest.get("sourcesHash") == h, "manifest agrees with SOURCES_HASH")

# --- 4. the engine side of the round ----------------------------------------
print("\n4. engine (src/)")
check("checkpoint_restore" in read(ROOT / "src" / "bridge" / "__main__.py"), "bridge handles checkpoint_restore")
check("turn_undo_point" in read(ROOT / "src" / "tools" / "shadow_checkpoints.py"), "shadow checkpoints expose turn_undo_point")
check("[new file]" in read(ROOT / "src" / "tools" / "file_tools.py"), "write receipt marks a created file")

# --- summary -----------------------------------------------------------------
print()
for w in warnings:
    print(f"  WARN  {w}")
if failures:
    print(f"RESULT: {len(failures)} FAILED — do not launch yet; send the FAIL lines back.")
    sys.exit(1)
print("RESULT: all checks passed — out/ is this round's panel. Now run the pytest gate, then launch.")
print("        Full-thickness hash proof: python -m pytest src/tests/test_desktop_renderer_architecture.py"
      "::test_engine_hash_matches_the_shipped_panel_on_this_repo -q")
