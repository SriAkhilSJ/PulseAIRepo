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
import difflib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Windows: give the direct child its own group so taskkill can address the tree; POSIX: a new
#: session, so killpg reaches grandchildren. Same technique as src/context/git_context.py, which
#: needs it because a killed parent does NOT take its children with it (measured field report: the
#: agent backgrounded `python -m http.server` in the workspace and the server outlived the turn).
_CREATION_FLAGS = 0x08000000 | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0


def kill_process_tree(proc: subprocess.Popen) -> str:
    """Kill the engine process AND everything it spawned. Returns what was used.

    ``proc.kill()`` reaps the direct child only: a backgrounded command the model started
    (`python -m http.server &`, a watcher, a dev server) survives it, and on a real ``--workspace``
    run that leaves a listening process behind after the harness exits. The tree is what has to go.
    """
    if proc.poll() is not None:
        return "already exited"
    if os.name == "nt":
        try:
            done = subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=20,
            )
            if done.returncode == 0:
                return "taskkill /T (whole tree)"
        except Exception:  # pragma: no cover - taskkill missing
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return "process group (whole tree)"
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
        return "direct child only (tree kill unavailable)"
    except Exception:  # pragma: no cover
        return "kill failed"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

def enable_unbuffered_output() -> None:
    """Make this script's own output appear as it happens.

    Piped through PowerShell, a tee, or a file, Python block-buffers stdout: a slow (or wedged) run
    shows *nothing* until it exits, which reads exactly like a hang carrying no information. The first
    live run of this script was reported that way — 600 seconds, zero lines. The child engine already
    gets ``PYTHONUNBUFFERED=1``; this is the same courtesy for the parent, and it runs at import so
    even an early failure is visible.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)  # type: ignore[union-attr]
        except (AttributeError, ValueError):  # pragma: no cover - non-standard stream
            pass


enable_unbuffered_output()

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
                    "selector": "header .nav-actions > button.btn.btn-primary",
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
            start_new_session=(os.name != "nt"),
            creationflags=_CREATION_FLAGS,
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

    def stop(self) -> str:
        """Tear down the engine and its children. Returns a description for the run log."""
        return kill_process_tree(self.proc)


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


def run_turn(bridge: Bridge, frame: dict, session_id: str, timeout: float, show_tools: bool) -> tuple[dict, list[str]]:
    """Send the prompt and stream until the turn ends. Returns (terminal frame, frames seen)."""
    bridge.send({"type": "hello", "protocol": PROTOCOL_VERSION})
    bridge.send({"type": "session_create", "session_id": session_id, "workspace": str(bridge.workspace)})
    bridge.send(frame)

    deadline = time.monotonic() + timeout
    terminal: dict = {}
    started = False
    seen: list[str] = []
    while time.monotonic() < deadline:
        try:
            incoming = bridge.read(timeout=min(30.0, max(1.0, deadline - time.monotonic())))
        except queue.Empty:
            # A quiet provider is normal. No frames at all is the thing worth telling apart, so the
            # heartbeat carries elapsed time, how much has arrived, and what the engine last sent.
            elapsed = timeout - max(0.0, deadline - time.monotonic())
            print(
                f"\n... waiting {elapsed:.0f}s of {timeout:.0f}s · frames: {len(seen)}"
                f" · last: {seen[-1] if seen else '(none)'} ..."
            )
            continue
        if incoming is None:
            print("\nThe engine closed its output — the process ended.")
            break
        kind = incoming.get("type")
        seen.append(str(kind))
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
    return terminal, seen


#: Directory names that are noise for "what did the agent change".
_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".next", ".cache", ".turbo", "dist", "build",
})
#: Files above this size are compared by size only, not read into memory.
_BIG_FILE_BYTES = 4 * 1024 * 1024


def snapshot(root: Path) -> dict[str, bytes]:
    """Relative path -> content for every file worth comparing.

    The first version of `--diff` shelled out to `git diff --stat`, which prints nothing and exits
    128 outside a repository — and because only the *exception* was caught, not the exit code, a
    `--demo` run (a temp copy, never a repo) reported "(git reported no changes)" while the agent had
    in fact edited the CSS. A diff that lies is worse than no diff, so the evidence is now taken from
    the filesystem: content in, content out, no VCS assumptions.
    """
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in relative.parts):
            continue
        try:
            size = path.stat().st_size
            files[relative.as_posix()] = path.read_bytes() if size <= _BIG_FILE_BYTES else b""
            if size > _BIG_FILE_BYTES:
                files[relative.as_posix()] = f"<{size} bytes>".encode("ascii")
        except OSError:
            continue
    return files


def _line_counts(before: bytes, after: bytes) -> tuple[int, int] | None:
    """(+added, -removed) for a text file, or None when it is binary."""
    if b"\0" in before or b"\0" in after:
        return None
    left = before.decode("utf-8", errors="replace").splitlines()
    right = after.decode("utf-8", errors="replace").splitlines()
    added = removed = 0
    for line in difflib.unified_diff(left, right, n=0, lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def describe_changes(before: dict[str, bytes], after: dict[str, bytes], *, preview_lines: int = 14) -> str:
    """What the turn actually edited, from the files themselves."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(path for path in set(before) & set(after) if before[path] != after[path])
    if not (added or removed or modified):
        return f"no file changed ({len(after)} file(s) compared)"

    lines: list[str] = []
    for path in modified:
        counts = _line_counts(before[path], after[path])
        lines.append(f"  M {path}" + (f"   +{counts[0]} -{counts[1]}" if counts else "   (binary)"))
        if counts:
            left = before[path].decode("utf-8", errors="replace").splitlines()
            right = after[path].decode("utf-8", errors="replace").splitlines()
            shown = 0
            for line in difflib.unified_diff(left, right, n=1, lineterm=""):
                if line.startswith(("+++", "---")):
                    continue
                lines.append("      " + line)
                shown += 1
                if shown >= preview_lines:
                    lines.append("      ...")
                    break
    lines.extend(f"  A {path}" for path in added)
    lines.extend(f"  D {path}" for path in removed)
    lines.append(f"  ({len(after)} file(s) compared)")
    return "\n".join(lines)


def git_diff_stat(workspace: Path) -> str | None:
    """`git diff --stat` when the workspace really is a repository, else None.

    The exit code is the point: outside a repo git prints nothing and exits non-zero, and reporting
    that as "no changes" is the bug this function used to have.
    """
    try:
        done = subprocess.run(
            ["git", "diff", "--stat"], cwd=str(workspace),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except Exception:  # pragma: no cover - no git on PATH
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


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

    before = snapshot(workspace) if args.diff else {}

    bridge = Bridge(workspace)
    try:
        terminal, seen = run_turn(bridge, frame, session_id, args.timeout, show_tools=not args.no_tools)
    except KeyboardInterrupt:
        print("\nInterrupted — stopping the engine.")
        terminal, seen = {}, []
    finally:
        teardown = bridge.stop()
        print(f"\nengine stopped: {teardown}")

    if args.diff:
        print("\n--- what changed in the workspace (read from the files, not from git) ---")
        print(describe_changes(before, snapshot(workspace)))
        git_stat = git_diff_stat(workspace)
        if git_stat:
            print("\n--- git diff --stat (extra context; the workspace is a repository) ---")
            print(git_stat)
    if cleanup is not None:
        print(f"\n(the edited copy is still at {cleanup} if you want to look at it)")

    if seen:
        tools = sum(1 for kind in seen if kind == "tool_call_start")
        print(f"\nframes: {len(seen)} · tool calls: {tools} · tokens: {seen.count('token')}")

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
    print("If the agent had started a long-running command (a dev server, a watcher), the tree was just")
    print("killed with the engine; if you ran --workspace, check that folder for leftover build output.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
