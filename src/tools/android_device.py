"""Reach `agent-device` from inside the agent — safely, and with a receipt.

Until this existed the agent could scaffold an app and verify a build, but had
no path at all to the device layer: no MCP server was registered, and nothing
shelled out to `agent-device` except `verify_android_app`'s batch `replay`. So
the interactive loop — open, snapshot, tap the ref, snapshot again — was simply
unreachable. This tool is that path.

Four rules, all deliberate:

1. **Arguments are passed as a list, never through a shell.** There is no
   `shell=True` and no string interpolation into a command line, so there is no
   injection surface regardless of what the model puts in `args`.
2. **The subcommand is checked against the real command registry.** Anything
   else is refused, so this tool cannot be used as a general command runner.
3. **Read-only steps and mutating steps are labelled.** The receipt says which
   one it was. That distinction is what lets the evidence be trusted later, and
   it is what an approval gate needs.
4. **This tool never installs anything.** agent-device's own skill states that
   installation is user-owned; auto-running `npm i -g` on someone's machine is
   not the agent's call. A missing binary reports UNAVAILABLE and stops.

Every invocation is appended to `<workspace>/.crusorai/android-evidence/
device-log.jsonl` and the full output is saved, so a snapshot's `@refs` can be
re-read later instead of being lost when the conversation scrolls.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

# Snapshots are large and mostly repetitive; the model needs the refs, not the
# whole tree. The full text is always on disk.
_MAX_OUTPUT_CHARS = 16000
_DEFAULT_TIMEOUT_S = 120

# Verbatim from callstack/agent-device packages/command-registry/src/registry.ts.
# Anything not in this set is refused, which is what makes rule 2 real.
_KNOWN_COMMANDS = frozenset("""
action-button alert app-switcher apps appstate artifacts audio auth back batch
boot capabilities cdp click clipboard close connect connection daemon debug
device devices diff disconnect doctor events fill find focus fold gesture get
home hover install install-from-source is keyboard logs longpress mcp metro
network open orientation perf plugins prepare press proxy push react-devtools
react-native record reinstall replay runtime screenshot scroll session settings
shutdown snapshot swipe takeover test trace trigger-app-event tv-remote type
viewport wait web
""".split())

# Pure inspection: cannot change what is on the device or its state.
_READ_ONLY = frozenset("""
apps appstate artifacts capabilities connection devices diff doctor events find
get is logs network perf plugins runtime screenshot snapshot viewport
""".split())

# Commands whose read/write nature depends on their first argument. Conservative
# default is mutating; the listed sub-verbs are provably read-only.
_AMBIGUOUS = {
    "device": {"status", "list", "info"},
    "session": {"status", "list", "info", "show"},
    "daemon": {"status", "info"},
    "orientation": {"get", "show"},
    "settings": {"list", "get", "show"},
    "debug": {"status", "info"},
    "cdp": {"status"},
    "react-devtools": {"status"},
    "metro": {"status"},
}

# These end sessions, move the device out from under another agent, or replace
# an installed app. Worth saying out loud before doing them.
_CONSEQUENTIAL = frozenset({
    "shutdown", "disconnect", "takeover", "reinstall", "install",
    "install-from-source", "boot", "record", "trace", "proxy", "web",
})

_SHELL_METACHARS = re.compile(r"[;&|`$<>]")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _evidence_root(workspace: str) -> Path:
    return Path(workspace) / ".crusorai" / "android-evidence"


def classify(subcommand: str, args: list[str]) -> str:
    """read-only | mutating | consequential — the honest label for a step."""
    sub = subcommand.strip().lower()
    if sub in _READ_ONLY:
        return "read-only"
    first = (args[0].strip().lower() if args else "")
    if sub in _AMBIGUOUS:
        if first in _AMBIGUOUS[sub]:
            return "read-only"
        return "mutating"
    if sub in _CONSEQUENTIAL:
        return "consequential"
    return "mutating"


def _append_device_log(workspace: str, entry: dict) -> Path:
    root = _evidence_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "device-log.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def _unavailable(workspace: str, reason: str, fix: str) -> str:
    _append_device_log(workspace, {
        "ts": _now(), "status": "unavailable", "reason": reason,
    })
    return (
        f"⛔ UNAVAILABLE — agent-device\n\n{reason}\n\n→ {fix}\n\n"
        "Nothing was attempted and nothing on the device changed. This is not a "
        "failure of your app. Do not report a UI result from this call."
    )


@tool
def android_device(
    subcommand: str,
    config: RunnableConfig,
    arguments: list[str] | None = None,
    platform: str = "android",
    timeout: int = _DEFAULT_TIMEOUT_S,
) -> str:
    """Run one agent-device command against a phone and return its real output.

    This is the interactive half of Android UI testing — `snapshot` to read the
    screen as accessibility refs, `click`/`fill`/`type` to act on a ref,
    `open` to launch an app. Use `verify_android_app` instead when you want a
    whole build-and-prove receipt in one call.

    Args:
        subcommand: one agent-device command, e.g. "snapshot", "click", "open".
            Checked against agent-device's real command registry; anything else
            is refused, so this is not a general command runner.
        arguments: args and flags for it, one string each, e.g. ["@e12"] or
            ["down", "--until", "text:Submit"]. No shell is involved, so shell
            metacharacters are rejected rather than interpreted.
        platform: appended as --platform when not already present. Pass "" to
            omit it.
        timeout: seconds to wait. Snapshots are quick; `replay` is not.

    Start with `open <package-id> --foreground` — it returns the first snapshot
    with refs, so you do not need a separate probing call. Copy refs
    byte-for-byte; they are only valid in the latest output. When a command
    fails, follow the corrective hint in its output instead of re-planning.
    """
    # NB: `config` must be annotated as a bare RunnableConfig. Optional[...]
    # is not recognised as config injection and silently becomes a normal
    # input argument, so the workspace falls back to os.getcwd() and the
    # evidence lands in the wrong project.
    workspace = str((config or {}).get("configurable", {}).get("workspace") or os.getcwd())
    argv_args = [str(a) for a in (arguments or [])]

    binary = shutil.which("agent-device")
    if not binary:
        return _unavailable(
            workspace,
            "agent-device is not on PATH, so there is no way to reach a device.",
            "Have the user run `npm install -g agent-device@latest` (Node 22.12+), "
            "then `agent-device doctor`. Do not install it yourself.",
        )

    sub = (subcommand or "").strip().lower().lstrip("-")
    if not sub:
        return "❌ REFUSED — no subcommand given."
    if sub in {"mcp", "daemon"} and sub == "mcp":
        # `agent-device mcp` starts a server that never exits. Registering it as
        # an MCP server is the right path; running it as a one-shot is a hang.
        return (
            "❌ REFUSED — `mcp` starts a long-lived server, not a one-shot "
            "command. Attach it as an MCP server instead (command "
            "`agent-device`, args `[\"mcp\"]`) rather than running it here."
        )
    if sub not in _KNOWN_COMMANDS:
        known = ", ".join(sorted(_KNOWN_COMMANDS))
        return (
            f"❌ REFUSED — '{sub}' is not an agent-device command. Refusing "
            f"rather than passing it through, because an unchecked subcommand "
            f"would make this a general command runner.\n\nKnown commands: {known}"
        )

    # We exec a list, so these cannot be interpreted. Rejecting them anyway keeps
    # a piped or chained command from being *requested* — the failure mode this
    # whole feature exists to avoid.
    for token in argv_args:
        if _SHELL_METACHARS.search(token):
            return (
                f"❌ REFUSED — argument {token!r} contains a shell metacharacter. "
                "This tool runs agent-device directly with an argument list, so "
                "pipes, `&&`, `;`, backticks and redirection are not available "
                "and would not have been interpreted anyway. Split it into "
                "separate calls."
            )

    argv = [binary, sub, *argv_args]
    plat = (platform or "").strip()
    if plat and f"--platform" not in " ".join(argv_args):
        argv += ["--platform", plat]

    kind = classify(sub, argv_args)
    label = {"read-only": "🔍", "mutating": "✏️", "consequential": "⚠️"}[kind]
    started = _now()
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=int(timeout),
            check=False,
        )
    except subprocess.TimeoutExpired:
        _append_device_log(workspace, {
            "ts": started, "cmd": argv[1:], "kind": kind, "status": "timeout",
            "timeout": int(timeout),
        })
        return (
            f"⏱️ TIMEOUT — `agent-device {' '.join(argv[1:])}` exceeded "
            f"{int(timeout)}s. It was killed. Nothing here proves success or "
            f"failure; re-run with a larger `timeout` if the command is "
            f"legitimately slow (a `replay` flow often is)."
        )
    except OSError as exc:  # binary vanished, not executable, etc.
        return _unavailable(workspace, f"agent-device could not be started: {exc}",
                            "Check the installation with `agent-device doctor`.")

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    full = stdout + ("\n--- stderr ---\n" + stderr if stderr.strip() else "")
    run_dir = _evidence_root(workspace) / f"device-{datetime.now(timezone.utc).strftime('%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{sub}.log").write_text(full, encoding="utf-8")
    _append_device_log(workspace, {
        "ts": started, "cmd": argv[1:], "kind": kind, "status": "ran",
        "exit": proc.returncode, "artifact": str(run_dir / f"{sub}.log"),
    })

    header = f"{label} {kind} · exit={proc.returncode} · `agent-device {' '.join(argv[1:])}`"
    if proc.returncode != 0:
        body = (stderr.strip() or stdout.strip() or "(no output)")
        verdict = "❌ FAILED"
        note = (
            "\n\nFollow the corrective hint above if there is one — agent-device "
            "says what to do next, and re-planning from scratch usually "
            "reproduces the same failure."
        )
    else:
        verdict = "✅"
        note = ""

    shown = full if len(full) <= _MAX_OUTPUT_CHARS else (
        full[: _MAX_OUTPUT_CHARS]
        + f"\n\n[… {len(full) - _MAX_OUTPUT_CHARS} more chars saved to "
        f"{run_dir / f'{sub}.log'} — read it there if the refs you need were cut]"
    )
    return f"{verdict} {header}\n\n{shown.strip()}{note}"
