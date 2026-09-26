#!/usr/bin/env python3
"""CrusorAI — run a Crusor Preview fix batch through the REAL agent.

The preview window's last step is a prompt: the batch of clicked-element fixes is rendered by
:mod:`src.preview.prompt` and sent as an ordinary bridge v2 ``prompt`` frame. The desktop app does
that from the window; this script does it from a terminal, so the *prompt itself* can be tested
without launching the IDE — and, more to the point, so the question "does the agent find the element
the user clicked, or does it repaint the page?" has an answer that is not a hope.

What it does, in order:

1. builds the batch (``--batch file.json``, or ``--demo`` for a batch drawn from the lab fixture);
2. prints the exact prompt text the agent will receive — that text is the whole feature;
3. spawns ``python -m src.bridge`` exactly as the workbench does (cwd = engine root, env inherited);
4. sends ``hello`` → ``session_create`` → the prompt frame, and streams what comes back, including
   every tool call, so you can watch it grep for the fingerprints;
5. prints the final answer and, with ``--diff``, what changed in the workspace.

Costs a real model call. Run ``scripts/check_provider.py --live`` first; a missing key fails here as
a classified provider error rather than a silent stall.

    python scripts/preview_batch_turn.py --demo            # safe: edits a temp copy of the fixture
    python scripts/preview_batch_turn.py --workspace C:\\path\\to\\scratch-project --batch batch.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROTOCOL_VERSION = 2
#: A real turn can legitimately take minutes; this is a ceiling, not an expectation.
DEFAULT_TIMEOUT_S = 900.0
FIXTURE = REPO_ROOT / "preview-lab" / "demo-app"


def demo_batch() -> dict:
    """A batch shaped like one the window produces from the lab fixture.

    Two fixes, chosen to exercise both mapping paths the prompt supports: one element the fixture
    stamps with ``data-crusor-source`` (precise), and one that carries only fingerprints (the
    heuristic path — the one that has to work in the user's own project).
    """
    return {
        "sessionId": "preview-batch-turn",
        "target": "http://localhost:5173/",
        "targetLabel": "aurora-landing (lab fixture) · dev server",
        "kind": "url",
        "viewport": "desktop",
        "createdAt": "2026-01-01T00:00:00Z",
        "fixes": [
            {
                "id": "fix_1", "order": 1,
                "instruction": "make this button rounded, blue, and a bit bigger",
                "label": '<button> "Get started"',
                "element": {
                    "selector": "header nav-actions > button.btn.btn-primary",
                    "tag": "button", "classes": ["btn", "btn-primary"], "text": "Get started",
                    "outerHtml": '<button class="btn btn-primary" type="button" data-testid="nav-cta">Get started</button>',
                    "styles": {"background-color": "rgb(60, 60, 60)", "color": "rgb(255, 255, 255)",
                               "border-radius": "10px", "font-size": "14px", "padding": "8px 16px"},
                    "fingerprint": {
                        "tag": "button", "classes": ["btn", "btn-primary"], "text": "Get started",
                        "attrs": [{"name": "data-testid", "value": "nav-cta"}],
                    },
                    "rect": {"x": 1180, "y": 14, "width": 108, "height": 38},
                    "viewport": {"width": 1440, "height": 900},
                },
            },
            {
                "id": "fix_2", "order": 2,
                "instruction": "the hero heading is too close to the paragraph below it — add breathing room",
                "label": '<h1> "Ship your product faster…"',
                "element": {
                    "selector": "main section.hero > h1.hero-title",
                    "tag": "h1", "classes": ["hero-title"],
                    "text": "Ship your product faster, without the busywork",
                    "outerHtml": '<h1 class="hero-title">Ship your product faster, without the busywork</h1>',
                    "styles": {"font-size": "48px", "margin": "0px 0px 4px", "color": "rgb(255, 255, 255)"},
                    "fingerprint": {"tag": "h1", "classes": ["hero-title"],
                                    "text": "Ship your product faster", "attrs": []},
                    "rect": {"x": 120, "y": 220, "width": 520, "height": 58},
                    "viewport": {"width": 1440, "height": 900},
                },
            },
        ],
    }


class Bridge:
    """Minimal protocol v2 client — the same handshake the workbench performs.

    Two things here are not optional, and both come from the repo's own transport tests
    (``src/tests/test_bridge_transport.py``):

    * **stderr is drained by a thread.** The engine writes diagnostics to stderr continuously; with
      nobody reading it the OS pipe buffer fills at ~64 KB and the child blocks on write, so stdout
      goes quiet forever. The first version of this script hung exactly that way.
    * **pipes are binary**, and lines are decoded here. Text-mode pipes were measured to drop frames
      on Windows when children are spawned and killed repeatedly.
    """

    def __init__(self, workspace: Path) -> None:
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env["PYTHONUNBUFFERED"] = "1"
        self.workspace = workspace
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "src.bridge"],
            cwd=str(REPO_ROOT), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self._frames: queue.Queue = queue.Queue()
        self._stderr: list[str] = []
        threading.Thread(target=self._read_stdout, name="bridge-stdout", daemon=True).start()
        threading.Thread(target=self._drain_stderr, name="bridge-stderr", daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        try:
            for raw in self.proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    self._frames.put(json.loads(line))
                except json.JSONDecodeError:
                    # A diagnostic that leaked onto stdout: keep it for the failure report.
                    self._stderr.append(f"(stdout) {line}")
        finally:
            self._frames.put(None)  # end of stream

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            text = raw.decode("utf-8", errors="replace").rstrip()
            if text:
                self._stderr.append(text)

    def send(self, frame: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def read(self, timeout: float = 120.0) -> dict | None:
        """Next frame, or None at end of stream. Raises ``queue.Empty`` on timeout."""
        return self._frames.get(timeout=timeout)

    @property
    def diagnostics(self) -> list[str]:
        return self._stderr

    def stop(self) -> None:
        try:
            self.proc.kill()
        except Exception:  # pragma: no cover
            pass


def _short(value: object, limit: int = 160) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def render(frame: dict, *, show_tools: bool = True) -> str | None:
    """One readable line per frame, or None for frames worth ignoring."""
    kind = frame.get("type")
    if kind == "reasoning":
        return f"  [reasoning] {_short(frame.get('text'), 120)}"
    if kind == "token":
        return f"  [text] {_short(frame.get('text'), 200)}"
    if kind == "tool_call_start" and show_tools:
        args = frame.get("arguments")
        if isinstance(args, dict):
            args = ", ".join(f"{k}={_short(v, 60)}" for k, v in list(args.items())[:4])
        return f"  [tool] {frame.get('name')}({_short(args, 140)})"
    if kind == "tool_call_end" and show_tools:
        return f"  [tool done] {frame.get('name')} → {_short(frame.get('result'), 120)}"
    if kind == "safety_request":
        return f"  [APPROVAL NEEDED] {_short(frame.get('reason') or frame, 200)}"
    if kind == "runtime_degraded":
        return f"  [degraded] {_short(frame.get('reason'), 200)}"
    if kind in {"error", "turn_failed"}:
        return f"  [ERROR] {_short(frame.get('message') or frame, 300)}"
    if kind == "turn_done":
        return f"  [done] {_short(frame.get('message'), 400)}"
    return None


def run_turn(bridge: Bridge, frame: dict, session_id: str, timeout: float, show_tools: bool) -> dict:
    """Send the prompt and stream until the turn ends. Returns the terminal frame."""
    bridge.send({"type": "hello", "protocol": PROTOCOL_VERSION})
    bridge.send({"type": "session_create", "session_id": session_id, "workspace": str(bridge.workspace)})
    bridge.send(frame)

    deadline = time.monotonic() + timeout
    terminal: dict = {}
    started = False
    while time.monotonic() < deadline:
        try:
            incoming = bridge.read(timeout=min(120.0, max(1.0, deadline - time.monotonic())))
        except queue.Empty:
            print(f"\n... still waiting ({timeout:.0f}s budget) ...")
            continue
        if incoming is None:
            print("\nThe engine closed its output — the process ended.")
            break
        kind = incoming.get("type")
        if kind == "turn_started":
            started = True
            print("\n--- turn started ---")
        line = render(incoming, show_tools=show_tools)
        if line:
            print(line)
        if kind in {"turn_done", "turn_failed", "error"} and started:
            terminal = incoming
            break
    else:
        print(f"\nTimed out after {timeout:.0f}s with no terminal frame.")
    return terminal


def git_diff_stat(workspace: Path) -> str:
    try:
        done = subprocess.run(
            ["git", "diff", "--stat"], cwd=str(workspace),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        return done.stdout.strip() or "(git reported no changes)"
    except Exception as exc:  # pragma: no cover
        return f"(could not run git diff: {exc})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path,
                        help="project the agent should edit. Use a scratch copy — this edits files.")
    parser.add_argument("--batch", type=Path, help="a preview batch JSON (as the window would send it)")
    parser.add_argument("--demo", action="store_true",
                        help="copy the lab fixture to a temp dir and use that (nothing in the repo is touched)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--no-tools", action="store_true", help="hide tool traffic, show only the answer")
    parser.add_argument("--diff", action="store_true", help="print `git diff --stat` in the workspace afterwards")
    args = parser.parse_args()

    if not args.workspace and not args.demo:
        parser.error("give --workspace or --demo (the agent edits files in whatever you point it at)")

    if args.batch:
        batch = json.loads(args.batch.read_text(encoding="utf-8"))
        if not isinstance(batch, dict):
            parser.error("the batch file must contain a JSON object")
    else:
        batch = demo_batch()

    cleanup: Path | None = None
    if args.demo:
        cleanup = Path(tempfile.mkdtemp(prefix="crusor-preview-agent-"))
        workspace = cleanup / "project"
        shutil.copytree(FIXTURE, workspace)
        print(f"workspace: {workspace}  (temp copy of the lab fixture — safe to edit)")
    else:
        workspace = args.workspace.expanduser().resolve()
        if not workspace.is_dir():
            parser.error(f"not a directory: {workspace}")
        print(f"workspace: {workspace}")

    if (os.environ.get("CRUSORAI_BRIDGE_RUNNER") or "").strip().lower() == "echo":
        print("\nCRUSORAI_BRIDGE_RUNNER=echo is set: the agent will ECHO this prompt instead of acting on")
        print("it. That tests the transport, not the prompt. Remove it and set a provider key to test")
        print("the real thing (scripts/check_provider.py --live proves the key first).")

    from src.preview.prompt import build_prompt_frame

    session_id = "preview-batch-turn"
    frame = build_prompt_frame(batch, session_id=session_id, workspace=str(workspace), mode="agent")

    print("\n" + "=" * 78)
    print("THE PROMPT THE AGENT RECEIVES (this text is the feature)")
    print("=" * 78)
    print(frame["text"])
    print("=" * 78)
    print(f"frames: prompt + preview_batch receipt ({frame['preview_batch']['count']} fixes)")

    bridge = Bridge(workspace)
    try:
        terminal = run_turn(bridge, frame, session_id, args.timeout, show_tools=not args.no_tools)
    except KeyboardInterrupt:
        print("\nInterrupted — stopping the engine.")
        terminal = {}
    finally:
        bridge.stop()

    if args.diff:
        print("\n--- what changed in the workspace ---")
        print(git_diff_stat(workspace))
    if cleanup is not None:
        print(f"\n(the edited copy is still at {cleanup} if you want to look at it)")

    if terminal.get("type") != "turn_done" and bridge.diagnostics:
        print("\n--- engine diagnostics (stderr, last 20 lines) ---")
        for line in bridge.diagnostics[-20:]:
            print("  " + line)

    if terminal.get("type") == "turn_done":
        print("\nRESULT: the turn completed.")
        return 0
    if terminal:
        print(f"\nRESULT: the turn ended as {terminal.get('type')} — see the message above.")
        return 1
    print("\nRESULT: no terminal frame — the engine never finished. Check scripts/check_provider.py --live.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
