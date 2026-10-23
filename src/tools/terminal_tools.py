import os
import platform
import re
import subprocess
import threading
import uuid
import time

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.runtime.windows_shell import select_shell


# R3-1: POSIX-on-Windows guard. R3 (Test-3 retest) burned 25 identical calls
# sending POSIX shell (`mkdir -p /tmp/...`, `which npx`, `cp X /tmp`) against
# a Windows cmd/PowerShell shell — every one failed fast with "syntax
# incorrect" / "'which' is not recognized", yet the model retried the same
# shape. Hermes never sends a POSIX-only command to Windows; it translates
# paths (MSYS) and keeps temp dirs under its own cache, never /tmp. We detect
# the dialect mismatch BEFORE spawning and return a typed pivot so the loop
# learns the environment, not just the error.
_IS_WINDOWS = platform.system() == "Windows"

#: Timeout/cancellation cleanup is a single wall-clock budget shared by all
#: reader threads and the process reap, not one timeout per stream.
_TERMINAL_DRAIN_TIMEOUT_S = 2.0
#: Once the shell exits, let both output readers finish within one shared
#: budget before taking the final snapshot.
_TERMINAL_OUTPUT_DRAIN_TIMEOUT_S = 10.0

# A command is treated as POSIX-dialect when it reaches a POSIX-only verb or
# a /tmp (or Unix-style) path. Words are split on whitespace and shell
# metachars so `mkdir -p` inside quotes is still caught, but a legit Windows
# path like `C:\Program Files` is not (it contains a backslash, not /tmp).
_POSIX_ONLY_VERBS = frozenset({
    "mkdir", "mv", "cp", "rm", "chmod", "chown", "which", "pwd",
    "touch", "ls", "find", "head", "tail", "wc", "grep", "sed", "awk",
    "cat", "tar", "unzip",
})
_POSIX_FLAGS = ("-p", "-rf", "-R", "-f", "+x")
_POSIX_TMP_RE = re.compile(
    r"(?:^|\s)(?:/tmp/|/var/tmp/|~/?|\.?/\.{1,2}(?:\s|$)|/mnt/[a-z]/)",
    re.IGNORECASE,
)
_WINDOWS_SHELL_BAD_RE = re.compile(r"mkdir\s+-p\b|\bwhich\b|\bchmod\b|\bsudo\b|\brm\s+-")


def _posix_violations(command: str) -> list[str]:
    """Return a list of POSIX-dialect violations in `command`, or [] when the
    command is shell-dialect-agnostic (safe to run on this platform)."""
    if not _IS_WINDOWS:
        return []
    if not command or not command.strip():
        return []
    violations: list[str] = []
    # Strip quoted segments for the verb scan so strings don't false-positive,
    # but keep them for the /tmp scan (a quoted /tmp path is still POSIX).
    stripped = re.sub(r'["\'][^"\']*["\']', "", command)
    words = re.findall(r"[^\s;&|()<>]+", stripped)
    for i, w in enumerate(words):
        verb = w.lstrip("([{").rstrip(")]};,")
        if verb in _POSIX_ONLY_VERBS:
            flags = [x for x in words[i + 1:i + 3] if x.startswith("-")]
            # `mkdir` without POSIX flags is a native cmd.exe command. The old
            # broad verb rule rejected the exact Windows scaffold command the
            # runtime guidance recommends (`mkdir temp_app && cd temp_app`).
            if verb == "mkdir" and not flags:
                continue
            if verb in ("mkdir", "cp", "mv", "rm") and flags and flags[0] in _POSIX_FLAGS:
                violations.append(
                    f"{verb} with POSIX flag `{flags[0]}` has no Windows equivalent "
                    f"(use PowerShell: New-Item -ItemType Directory, Copy-Item, "
                    f"Move-Item, Remove-Item — or cmd: mkdir/copy/move/del)."
                )
            elif verb in _POSIX_ONLY_VERBS or verb == "sudo":
                # The old detector listed ls/pwd/find-style verbs but only
                # emitted a violation for which/chmod/etc. Test5-5 therefore
                # spawned bare `ls -la` and `pwd` on cmd.exe and paid for the
                # predictable failures. Every listed POSIX-only verb must
                # produce the typed platform pivot before process spawn.
                violations.append(
                    f"`{verb}` is a POSIX-only command in this cmd.exe runtime. "
                    "Use cmd/PowerShell equivalents (dir, cd, where, Get-ChildItem, "
                    "Get-Content, Select-String)."
                )
    if _POSIX_TMP_RE.search(command):
        violations.append(
            "The command references a POSIX path (/tmp, /var/tmp, ~, ./..). On "
            "Windows, use a directory INSIDE the workspace (e.g. temp_app\\ or "
            ".\\temp_app\\) — /tmp does not exist here."
        )
    return violations


# Stores tracked foreground and background processes while their logs are useful.
_processes = {}

# Protects _processes and each process's output log from simultaneous access.
_process_lock = threading.Lock()
_STARTUP_PREVIEW_CHARS = 8_192


def _create_terminal_log(process_id: str):
    """Create a private, persistent output log for one tracked process."""
    root = os.path.join(os.path.expanduser("~"), ".crusorai", "terminal-logs")
    os.makedirs(root, mode=0o700, exist_ok=True)
    path = os.path.join(root, f"{process_id}.log")
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    return path, os.fdopen(fd, "w", encoding="utf-8", errors="replace", newline="")


def _discard_terminal_log(process_id: str) -> None:
    """Close and remove a completed process log when no paged reread is needed."""
    with _process_lock:
        process_data = _processes.pop(process_id, None)
        if process_data is None:
            return
        writer = process_data.get("output_file")
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
        output_path = process_data.get("output_path")
    if output_path:
        try:
            os.remove(output_path)
        except OSError:
            pass


def _read_process_output(
    process_id: str,
    process: subprocess.Popen
):
    """Spool background output to disk and keep only a bounded startup preview."""
    try:
        if process.stdout is None:
            return
        for line in iter(process.stdout.readline, ""):
            with _process_lock:
                process_data = _processes.get(process_id)
                if process_data is None:
                    break
                writer = process_data.get("output_file")
                if writer is None:
                    break
                writer.write(line)
                writer.flush()
                process_data["line_count"] += 1
                remaining = _STARTUP_PREVIEW_CHARS - len(process_data["startup_output"])
                if remaining > 0:
                    process_data["startup_output"] += line[:remaining]
    finally:
        if process.stdout is not None:
            try:
                process.stdout.close()
            except Exception:
                pass
        with _process_lock:
            process_data = _processes.get(process_id)
            writer = process_data.get("output_file") if process_data else None
            if writer is not None:
                try:
                    writer.flush()
                    writer.close()
                except Exception:
                    pass
                process_data["output_file"] = None


@tool
def read_terminal_output(
    process_id: str,
    start_line: int = 1,
    end_line: int = 200,
) -> str:
    """Read a specific line range from the stored output of a terminal process."""

    if start_line < 1:
        return "Error: start_line must be at least 1."

    if end_line < start_line:
        return "Error: end_line must be greater than or equal to start_line."

    # Protect LLM context from huge requests.
    max_lines = 500

    if end_line - start_line + 1 > max_lines:
        return (
            f"Error: Maximum {max_lines} lines can be read at once. "
            f"Request a smaller range."
        )

    with _process_lock:
        process_data = _processes.get(process_id)

        if process_data is None:
            return f"Unknown process ID: {process_id}"

        total_lines = process_data.get("line_count", len(process_data.get("output", [])))
        output_path = process_data.get("output_path")
        if output_path:
            selected_lines = []
            try:
                with open(output_path, "r", encoding="utf-8", errors="replace") as output_file:
                    for line_number, line in enumerate(output_file, start=1):
                        if line_number >= start_line:
                            selected_lines.append(line)
                        if line_number >= end_line:
                            break
            except OSError as exc:
                return f"Could not read output for process {process_id}: {exc}"
        else:
            # Compatibility for process records created before file-backed logs.
            selected_lines = list(process_data.get("output", []))[start_line - 1:end_line]

    if total_lines == 0:
        return (
            f"Process ID: {process_id}\n"
            f"Total lines: 0\n"
            f"No terminal output has been captured yet."
        )

    if start_line > total_lines:
        return (
            f"Process ID: {process_id}\n"
            f"Total lines: {total_lines}\n"
            f"Requested start line {start_line} is beyond the available output."
        )

    actual_end = min(
        end_line,
        total_lines,
    )

    output = "".join(selected_lines)

    return (
        f"Process ID: {process_id}\n"
        f"Total lines: {total_lines}\n"
        f"Showing lines: {start_line}-{actual_end}\n\n"
        f"{output}"
    )

def _spawn_tracked_background(command: str, config: RunnableConfig) -> str:
    """The tracked-background spawn start_terminal serves (hermes
    terminal_tool.py:1216-1229: the foreground->background promotion uses
    the SAME spawn path as the background tool). Returns the spawn receipt;
    a _hardline_refusal passes through unchanged (hermes attaches the
    promoted note only to a successful spawn)."""
    workspace = config["configurable"]["workspace"]

    _bg_floor = _hardline_refusal(command)
    if _bg_floor:
        return _bg_floor

    process_id = str(uuid.uuid4())[:8]

    _bg_argv, _bg_shell, _ = select_shell(command)
    popen_kwargs = dict(
        cwd=workspace,
        shell=_bg_shell,
        # stdin=DEVNULL, never inherited: under the bridge, fd 0 is the client's
        # JSON-RPC pipe. A child that inherits it can read the parent's protocol
        # frames — stealing turns and desynchronizing the stream — and on Windows
        # the inherited write end also keeps cmd.exe's own stdin read blocked, so
        # even `python hello.py` never returns. (live round: 4-process chain
        # bridge->cmd->python->python alive at 25s, every child waiting on stdin.)
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if _IS_WINDOWS:
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) \
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        popen_kwargs["start_new_session"] = True
    output_path, output_file = _create_terminal_log(process_id)
    try:
        process = subprocess.Popen(_bg_argv if _bg_argv is not None else command, **popen_kwargs)
    except Exception:
        try:
            output_file.close()
            os.remove(output_path)
        except OSError:
            pass
        raise

    # Store the process and its disk-backed output cursor.
    with _process_lock:
        _processes[process_id] = {
            "process": process,
            "command": command,
            "workspace": workspace,
            "output_path": output_path,
            "output_file": output_file,
            "startup_output": "",
            "line_count": 0,
            "cursor": 0,
        }

    # Start background output reader
    reader_thread = threading.Thread(
        target=_read_process_output,
        args=(process_id, process),
        daemon=True
    )

    reader_thread.start()

    # Fast startup window probe (Hermes / Claude Code pattern): probe initial output up to 2.5s
    # so the agent immediately receives the listening URL / port without wasting 6+ check_terminal turns.
    time.sleep(0.8)
    for _ in range(6):
        with _process_lock:
            proc_info = _processes.get(process_id, {})
            current_out = proc_info.get("startup_output", "")
        if any(term in current_out.lower() for term in ("ready", "listening", "http://", "localhost:", "compiled", "failed", "error", "vite", "next")):
            break
        time.sleep(0.3)

    with _process_lock:
        proc_info = _processes.get(process_id, {})
        initial_output = proc_info.get("startup_output", "").strip()
        output_file = proc_info.get("output_file")
        if output_file is not None:
            output_file.flush()
            proc_info["cursor"] = output_file.tell()
        else:
            try:
                with open(proc_info.get("output_path", ""), "r", encoding="utf-8", errors="replace") as logged_output:
                    logged_output.seek(0, os.SEEK_END)
                    proc_info["cursor"] = logged_output.tell()
            except OSError:
                proc_info["cursor"] = 0

    out_preview = f"\n\nInitial startup output:\n{initial_output[:800]}" if initial_output else ""

    return (
        f"Process started.\n"
        f"Process ID: {process_id}\n"
        f"Command: {command}{out_preview}"
    )

@tool
def start_terminal(
    command: str,
    config: RunnableConfig
) -> str:
    """Start a long-running terminal command in the active workspace."""
    return _spawn_tracked_background(command, config)

@tool
def run_terminal(
    command: str,
    config: RunnableConfig,
    timeout: int | str | None = None,
) -> str:
    """
    Legacy crusor name of `terminal` (hermes tool-name parity, 2026-09-09;
    the 2026-09-05 alias direction flipped). Executes the full terminal
    contract: timeout honored (default 300s, foreground max 600s,
    above-cap promoted to a tracked background process).

    Hermes tool-name parity (field run 2026-09-05): models trained on
    hermes emit the tool name `terminal` — the unknown-name rejection
    ended a listing turn as "Tool failed: terminal". This alias makes the
    hermes name EXECUTE with run_terminal's full contract: timeout
    honored (default 300s, foreground max 600s, above-cap promoted to a
    tracked background process), cmd.exe dialect on Windows.

    Do NOT use cat/head/tail (use read_file), grep/rg/find/ls
    (use list_files or search_files), sed/awk (use edit_file), or
    echo/heredoc file creation (use write_file). Reserve the terminal
    for: builds, installs, git, processes, scripts, network, package
    managers — anything that needs a shell.
    """
    return terminal.func(command, config, timeout)


def _limit_terminal_output(
    output: str,
    max_chars: int = 12_000,
) -> str:
    """Limit terminal output while preserving both the beginning and end."""

    total_chars = len(output)
    total_lines = len(output.splitlines()) if output else 0

    if total_chars <= max_chars:
        return output

    # Give more space to the tail because errors and build
    # summaries usually appear near the end.
    head_chars = max_chars // 3
    tail_chars = max_chars - head_chars

    head = output[:head_chars]
    tail = output[-tail_chars:]

    omitted_chars = total_chars - max_chars

    return (
        f"[Terminal output truncated]\n"
        f"Total lines: {total_lines}\n"
        f"Total characters: {total_chars}\n"
        f"Omitted characters: {omitted_chars}\n\n"
        f"--- BEGINNING OF OUTPUT ---\n"
        f"{head}\n\n"
        f"--- OUTPUT OMITTED ---\n\n"
        f"--- END OF OUTPUT ---\n"
        f"{tail}"
    )

@tool
def check_terminal(
    process_id: str,
    wait_seconds: int = 0
) -> str:
    """
    Check a background process started by start_terminal. Use wait_seconds
    (up to 300) on later checks instead of polling immediately; wait only
    waits for status, it does not limit the process. Do not restart a
    command merely because it is still running.
    """

    # Prevent unreasonable single-check waits
    wait_seconds = max(0, min(wait_seconds, 300))

    with _process_lock:
        process_data = _processes.get(process_id)

        if process_data is None:
            return f"Unknown process ID: {process_id}"

        process = process_data["process"]

    # Wait up to wait_seconds, but return immediately if process finishes
    if wait_seconds > 0:
        try:
            process.wait(timeout=wait_seconds)
        except subprocess.TimeoutExpired:
            pass

    # Get output produced since the previous check
    with _process_lock:
        process_data = _processes.get(process_id)

        if process_data is None:
            return f"Unknown process ID: {process_id}"

        start = process_data.get("cursor", 0)
        output_path = process_data.get("output_path")
        if output_path:
            try:
                with open(output_path, "r", encoding="utf-8", errors="replace") as logged_output:
                    logged_output.seek(start)
                    full_new_output = logged_output.read()
                    process_data["cursor"] = logged_output.tell()
            except OSError as exc:
                full_new_output = f"[Could not read process output log: {exc}]"
        else:
            output_lines = process_data.get("output", [])[start:]
            full_new_output = "".join(output_lines)
            process_data["cursor"] = len(process_data.get("output", []))

    return_code = process.poll()

    new_output = _limit_terminal_output(
        full_new_output
    )   

    if return_code is None:
        status = "RUNNING"
    else:
        status = "COMPLETED"

    result = (
        f"Status: {status}\n"
        f"Process ID: {process_id}"
    )

    if new_output:
        result += f"\n\nNew output:\n{new_output}"

    if return_code is not None:
        result += f"\nExit code: {return_code}"

    return result


def _failure_hint(command: str, returncode: int, output: str, exit_note) -> str | None:
    """hermes tools/terminal_tool_result.py::_failure_hint, verbatim shape: on
    rc=0, warn when a pipeline tail / `|| echo` may mask an upstream failure
    and the output carries strong failure indicators (advisory only — the exit
    code itself is NEVER rewritten); on rc!=0, one recovery hint from
    tools/terminal_hints.py. ``exit_note`` stays None until crusor ports
    hermes' ``_interpret_exit_code`` semantics table."""
    from src.tools.terminal_hints import annotate_failure, annotate_masked_success

    if returncode == 0:
        return annotate_masked_success(command, output)
    if not exit_note:
        return annotate_failure(command, returncode, output)
    return None


def _record_verification_result(
    config: RunnableConfig, workspace: str, command: str, exit_code: int, output: str
) -> None:
    try:
        session_id = str((config or {}).get("configurable", {}).get("thread_id", "default"))
        from src.runtime.factory import get_runtime_services
        evidence = get_runtime_services().verification.record_command(
            session_id=session_id, workspace=workspace, command=command,
            exit_code=exit_code, output=output,
        )
        if evidence:
            from src.dashboard.event_bus import event_bus
            event_bus.emit("verification.updated", {**evidence, "thread_id": session_id})
    except Exception as exc:
        try:
            from src.dashboard.event_bus import event_bus
            event_bus.emit("runtime.degraded", {
                "thread_id": str((config or {}).get("configurable", {}).get("thread_id", "default")),
                "component": "verification_ledger", "error": str(exc),
            })
        except Exception:
            pass


FOREGROUND_MAX_TIMEOUT_DEFAULT = 600  # hermes TERMINAL_MAX_FOREGROUND_TIMEOUT


# PURE read verbs only. Executing tools (python/node/npm/pip/pytest) are
# DELIBERATELY absent — code can write, and execute_code already snapshots.
# ---------------------------------------------------------------------------
# Hermes foreground/background guard (tools/terminal_tool_guards.py,
# _foreground_background_guidance) — a TOOL contract: a foreground terminal
# call cannot serve long-lived servers/watchers or shell backgrounding, so
# the tool refuses BEFORE the wait and teaches the exact re-send. Field
# tuition otherwise: every `npm run dev` in run_terminal burned the full
# foreground timeout (316.5s on 2026-09-07 10:28, again 2026-09-07 2:19 PM)
# before the exit-124 pivot. Hermes refuses in zero seconds. Guidance names
# crusor's real tools (start_terminal / read_terminal_output).
# ---------------------------------------------------------------------------
_SHELL_LEVEL_BACKGROUND_RE = re.compile(
    r"(?:^|[;&|]\s*|&&\s*|\|\|\s*|\$\(\s*)(?:nohup|disown|setsid)\b", re.IGNORECASE | re.MULTILINE
)
_INLINE_BACKGROUND_AMP_RE = re.compile(r"\s&\s")
_TRAILING_BACKGROUND_AMP_RE = re.compile(r"\s&\s*(?:#.*)?$")

_LONG_LIVED_FOREGROUND_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:dev|start|serve|watch)\b",
    r"\bdocker\s+compose\s+up\b",
    r"\bnext\s+dev\b",
    r"\bvite(?:\s|$)",
    r"\bnodemon\b",
    r"\buvicorn\b",
    r"\bgunicorn\b",
    r"\bpython(?:3)?\s+-m\s+http\.server\b",
    # ── crusor additions to hermes' list (2026-09-26), from a measured field failure ──
    # `npx <pkg>` bypasses the npm|pnpm|yarn|bun pattern above, and that is how run 7 of the preview
    # harness ended: the agent ran `npx serve . -p 4444` foreground to verify its edit, the call
    # blocked, and the turn died on the harness timeout with the fix unproven ("recovery proven,
    # completion not"). These package names bind a port and never exit; `--help`/`--version` remain
    # exempt above, and a longer timeout is promoted to a tracked background process below rather
    # than refused, so only the genuinely unbounded foreground server is refused here.
    r"(?:^|[|&;]\s*)(?:serve|http-server|live-server)\b",
    r"\bnpx\s+(?:-y\s+|--yes\s+)?(?:serve|http-server|live-server|sirv|vite|nodemon|webpack-dev-server)(?:@[\w.]+)?\b",
    r"\bphp\s+-S\b",
    r"\bflask\s+run\b",
    r"\bmanage\.py\s+runserver\b",
))


def _strip_quotes(command: str) -> str:
    """hermes terminal_tool_guards._strip_quotes (minus heredoc masking,
    which is a hermes shell_heredoc module crusor does not carry): blank
    quoted/backtick content so keywords inside strings can't match."""
    result = re.sub(r"'[^']*'", "''", command)
    result = re.sub(r'"(?:[^"\\]|\\.)*"', '""', result)
    return re.sub(r"`[^`]*`", "``", result)


def _looks_like_help_or_version_command(command: str) -> bool:
    """hermes: informational invocations are never blocked."""
    normalized = " ".join(command.lower().split())
    return (
        " --help" in normalized
        or normalized.endswith(" -h")
        or " --version" in normalized
        or normalized.endswith(" -v")
    )


def _foreground_background_guidance(command: str) -> str | None:
    """hermes _foreground_background_guidance, verbatim logic; guidance text
    adapted to crusor's tool names (terminal(background=true) -> start_terminal)."""
    if _looks_like_help_or_version_command(command):
        return None
    unquoted = _strip_quotes(command)
    if _SHELL_LEVEL_BACKGROUND_RE.search(unquoted):
        return (
            "Foreground command uses shell-level background wrappers "
            "(nohup/disown/setsid). Re-send WITHOUT the wrapper as "
            "start_terminal(command=\"<cmd>\") so the process is tracked, "
            "then run readiness checks and tests in separate commands "
            "(read_terminal_output / check_terminal)."
        )
    if _INLINE_BACKGROUND_AMP_RE.search(unquoted) or _TRAILING_BACKGROUND_AMP_RE.search(unquoted):
        return (
            "Foreground command uses '&' backgrounding — this shell cannot run "
            "it that way. Re-send WITHOUT the '&' as start_terminal(command="
            "\"<cmd>\"), then poll readiness with read_terminal_output and run "
            "tests in follow-up commands."
        )
    if any(p.search(unquoted) for p in _LONG_LIVED_FOREGROUND_PATTERNS):
        return (
            "This foreground command starts a long-lived server/watch process "
            "and would hang until the timeout (it never exits). Run it with "
            "start_terminal(command=\"<cmd>\"), wait for the port/log signal "
            "with read_terminal_output, then execute tests in a separate "
            "command — browser tools for UI proof."
        )
    return None


def _hardline_refusal(command: str) -> str | None:
    """The never-run floor (hermes HARDLINE_PATTERNS): refused BEFORE spawn,
    unconditionally — the approval dock must never be able to approve a
    root wipe, a block-device write, or a shutdown. Pure classification
    lives in src/context/approval_detection.py; this wrapper keeps the
    refusal text with the tools that enforce it."""
    from src.context.approval_detection import detect_hardline_command
    finding = detect_hardline_command(command)
    if not finding:
        return None
    return (
        f"⛔ refused: {finding}. This command is on the never-run floor — "
        "it cannot be executed or approved in any mode. State a different "
        "approach."
    )


_READONLY_FIRST_TOKENS = frozenset({
    "dir", "ls", "type", "cat", "head", "tail", "findstr", "grep", "rg",
    "where", "which", "pwd", "tree", "wc", "stat", "file", "whoami", "hostname",
    "get-childitem", "gci", "test-path", "select-string", "sls",
    "get-content", "gc", "get-item", "gi", "get-command", "gcm", "echo",
})
_READONLY_GIT_SUBCOMMANDS = frozenset({
    "status", "log", "diff", "show", "branch", "remote", "rev-parse",
    "ls-files", "config", "describe", "blame", "shortlog", "tag",
})
_MUTATION_MARKERS = (">>", "set-content", "add-content", "new-item",
                     "remove-item", "out-file")


def _looks_mutating(command: str) -> bool:
    """True unless the command is recognizably read-only (D31 scope).

    Conservative both ways: a known read verb skips the 24s-class snapshot;
    anything unrecognized or carrying a redirect still snapshots. `/` in cmd
    is a FLAG not a redirect, so `dir /b` is clean; a lone `>` (with the
    cmd no-op `2>$null`/`2>nul` tolerated) is a write.
    """
    text = command.strip()
    if not text:
        return False
    if ">" in text.replace("2>$null", "").replace("2>nul", ""):
        return True
    lowered = text.lower()
    if any(marker in lowered for marker in _MUTATION_MARKERS):
        return True
    words = re.findall(r"[^\s;&|()<>]+", text)
    if not words:
        return False
    first = words[0].strip("([{\"'").rstrip(")]}\"',;").lower()
    if first == "git":
        second = words[1].lower() if len(words) > 1 else ""
        return second not in _READONLY_GIT_SUBCOMMANDS
    return first not in _READONLY_FIRST_TOKENS


def _foreground_max_timeout() -> int:
    """hermes TERMINAL_MAX_FOREGROUND_TIMEOUT (terminal_tool.py:74, default
    600), read PER CALL, clamped to the 30..3600 band."""
    try:
        raw_max = os.environ.get("CRUSORAI_TERMINAL_MAX_FOREGROUND_TIMEOUT", "")
        max_cap = int(raw_max) if raw_max else FOREGROUND_MAX_TIMEOUT_DEFAULT
    except (TypeError, ValueError):
        max_cap = FOREGROUND_MAX_TIMEOUT_DEFAULT
    return max(30, min(max_cap, 3600))


def _foreground_timeout(value) -> tuple[int, str | None]:
    """Hermes terminal contract (tools/terminal_tool.py:943-957), ported:
    the MODEL owns foreground timeout — honored, coerced (models send
    strings), rejected when non-positive. The CAP is not a rejection here:
    hermes :966-971 PROMOTES an over-cap request to a tracked background
    process (454-refusal receipt) — run_terminal owns that decision.
    Env default still sizes ordinary runs; the env default applies only
    when the model passed nothing.
    Returns (effective_seconds, rejection_message_or_None).
    """
    raw_env = os.environ.get("CRUSORAI_TERMINAL_TIMEOUT", "300")
    try:
        default = int(raw_env)
    except (TypeError, ValueError):
        default = 300

    if value is None or (isinstance(value, str) and not value.strip()):
        return max(1, default), None
    try:
        requested = int(str(value).strip())
    except (TypeError, ValueError):
        return max(1, default), None
    if requested <= 0:
        return 0, (
            f"timeout must be a positive number of seconds (got {requested})."
        )
    return requested, None


def _capture_foreground_process(
    process,
    started: float,
    timeout: float,
    is_cancelled,
    emit,
    process_id: str | None = None,
    capture_limit: int | None = None,
):
    """Observe process exit and timeout as competing, first-wins outcomes.

    This mirrors OpenCode's shell lifecycle: process/output ownership is
    separate, exit and timeout race to settle once, killing is detached, and
    the final output snapshot is taken only after readers drain (or the
    bounded drain budget expires for a pipe held open by an escaped child).
    """
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    output_lock = threading.Lock()
    outcome_lock = threading.Lock()
    outcome_ready = threading.Event()
    process_done = threading.Event()
    output_done = threading.Event()
    outcome: dict = {"value": None}
    reader_count = sum(stream is not None for stream in (process.stdout, process.stderr))
    readers_left = {"count": reader_count}
    readers_lock = threading.Lock()
    streamed = {"chars": 0}
    captures = {
        "stdout": {"parts": [], "buffer_chars": 0, "head": "", "tail": "", "total": 0, "truncated": False},
        "stderr": {"parts": [], "buffer_chars": 0, "head": "", "tail": "", "total": 0, "truncated": False},
    }

    if reader_count == 0:
        output_done.set()

    def finish(status: str, *, exit_code=None) -> bool:
        with outcome_lock:
            if outcome["value"] is not None:
                return False
            outcome["value"] = {"status": status, "exit": exit_code}
            outcome_ready.set()
            return True

    def capture_line(name: str, parts: list[str], line: str) -> None:
        state = captures[name]
        if process_id is None or capture_limit is None:
            parts.append(line)
            return
        state["total"] += len(line)
        if not state["truncated"]:
            state["parts"].append(line)
            state["buffer_chars"] += len(line)
            if state["buffer_chars"] > capture_limit:
                buffered = "".join(state["parts"])
                head_chars = max(1, capture_limit // 3)
                tail_chars = max(1, capture_limit - head_chars)
                state["head"] = buffered[:head_chars]
                state["tail"] = buffered[-tail_chars:]
                state["parts"].clear()
                state["buffer_chars"] = 0
                state["truncated"] = True
        else:
            tail_chars = max(1, capture_limit - max(1, capture_limit // 3))
            state["tail"] = (state["tail"] + line)[-tail_chars:]

    def render_capture(name: str, parts: list[str]) -> str:
        state = captures[name]
        if process_id is None or capture_limit is None:
            return "".join(parts)
        if not state["truncated"]:
            return "".join(state["parts"])
        omitted = max(0, state["total"] - len(state["head"]) - len(state["tail"]))
        return (
            f"{state['head']}\n[... {name} output clipped; {omitted} characters omitted, "
            f"full log available by process ID ...]\n{state['tail']}"
        )

    def pump(stream, parts: list[str], stream_name: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                with output_lock:
                    capture_line(stream_name, parts, line)
                    streamed["chars"] += len(line)
                    should_emit = streamed["chars"] <= 65_536
                    if process_id is not None:
                        with _process_lock:
                            process_data = _processes.get(process_id)
                            writer = process_data.get("output_file") if process_data else None
                            if writer is not None:
                                try:
                                    writer.write(line)
                                    writer.flush()
                                    process_data["line_count"] += 1
                                    process_data["capture_truncated"] = any(
                                        capture["truncated"] for capture in captures.values()
                                    )
                                    process_data["captured_chars"] = sum(
                                        capture["total"] for capture in captures.values()
                                    )
                                except Exception:
                                    pass  # output capture remains authoritative
                if should_emit:
                    try:
                        emit(line)
                    except Exception:
                        pass  # streaming is best-effort; capture remains authoritative
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass
            with readers_lock:
                readers_left["count"] -= 1
                if readers_left["count"] == 0:
                    output_done.set()

    pumps = []
    for stream, parts, stream_name in (
        (process.stdout, stdout_parts, "stdout"),
        (process.stderr, stderr_parts, "stderr"),
    ):
        if stream is None:
            continue
        thread = threading.Thread(target=pump, args=(stream, parts, stream_name), daemon=True)
        thread.start()
        pumps.append(thread)

    def watch_exit() -> None:
        try:
            finish("exited", exit_code=process.wait())
        except Exception:
            finish("exited", exit_code=getattr(process, "returncode", None))
        finally:
            process_done.set()

    threading.Thread(target=watch_exit, daemon=True).start()

    def kill_tree_with_grace() -> None:
        try:
            if _IS_WINDOWS:
                from src.context.git_context import _taskkill_tree
                if not _taskkill_tree(process.pid):
                    process.kill()
                return
            import signal
            os.killpg(process.pid, signal.SIGTERM)
            if not process_done.wait(3.0):
                os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    while not outcome_ready.wait(0.05):
        if is_cancelled():
            if finish("cancelled"):
                threading.Thread(target=kill_tree_with_grace, daemon=True).start()
            break
        if timeout > 0 and time.monotonic() - started >= timeout:
            if finish("timeout"):
                # Like OpenCode, recording timeout is immediate; killing must
                # not block the caller or be cancelled with the timer fiber.
                threading.Thread(target=kill_tree_with_grace, daemon=True).start()
            break

    settled = outcome["value"] or {"status": "exited", "exit": getattr(process, "returncode", None)}
    if settled["status"] == "exited":
        output_done.wait(_TERMINAL_OUTPUT_DRAIN_TIMEOUT_S)
    else:
        # Reap and both output readers share one monotonic deadline. A leaked
        # descendant cannot grant each pipe a fresh timeout.
        deadline = time.monotonic() + _TERMINAL_DRAIN_TIMEOUT_S
        process_done.wait(max(0.0, deadline - time.monotonic()))
        output_done.wait(max(0.0, deadline - time.monotonic()))

    if process_id is not None:
        with _process_lock:
            process_data = _processes.get(process_id)
            writer = process_data.get("output_file") if process_data else None
            if writer is not None:
                try:
                    writer.flush()
                    writer.close()
                except Exception:
                    pass
                process_data["output_file"] = None

    with output_lock:
        stdout = render_capture("stdout", stdout_parts)
        stderr = render_capture("stderr", stderr_parts)
    return settled["status"], stdout, stderr


@tool
def terminal(
    command: str,
    config: RunnableConfig,
    timeout: int | str | None = None,
) -> str:
    """
    Run a short terminal command inside the active workspace (shell).

    Hermes tool-name parity (2026-09-09): hermes binds this tool as
    `terminal` (tools/terminal_tool.py); `run_terminal` was crusor's
    invention and remains bound below as the legacy alias.

    USE for quick commands: python scripts, tests, checks, environment
    inspection, verifying generated code. Inspect non-zero exit codes.
    The output envelope ends with "Exit code: N" — read it before
    claiming success.

    Hermes timeout contract: max seconds to wait (default 300,
    foreground max 600). Returns the moment the command finishes — set
    a generous timeout for long tasks; you will NOT wait unnecessarily.
    A foreground timeout above the 600s cap is PROMOTED (hermes
    terminal_tool.py:966-971 — refusing only bought a mechanical retry):
    the command starts as a tracked background process instead. The
    receipt carries the process_id — poll it with check_terminal, do NOT
    re-run the command.

    Do NOT use cat/head/tail (use read_file), grep/rg/find/ls
    (use list_files or search_code), sed/awk (use edit_file), or
    echo/heredoc file creation (use write_file). Reserve the terminal
    for: builds, installs, git, processes, scripts, network, package
    managers — anything that needs a shell.
    Output is auto-truncated — never pipe through tail/head to shorten
    it. (hermes terminal_tool.py's sentence names the spill file its
    full-text save produces; crusor has not yet ported that spill, so
    only the truthful half of the sentence is bound here.)

    DO NOT use for long-running installs/builds/servers (use
    start_terminal) or for reading known files (use read_file). Never run
    destructive commands unless explicitly requested and safe.
    """

    workspace = config["configurable"]["workspace"]

    # Hermes terminal contract (tools/terminal_tool.py): the model's
    # timeout is HONORED — coerced, validated. Silently ignoring it (the
    # old behavior) taught the model nothing and read as "life long" when
    # it asked for 30000s.
    timeout, timeout_rejection = _foreground_timeout(timeout)
    if timeout_rejection:
        return f"⛔ terminal rejected: {timeout_rejection}"

    # Hermes foreground/background guard (terminal_tool.py :965 — the guard
    # fires BEFORE the deadline math): a command the foreground transport
    # cannot serve is refused in zero seconds with the exact re-send, not
    # after burning the whole timeout. Hermes order matters (:956-971):
    # this guidance STAYS A REFUSAL even over-cap — `&`/nohup/server
    # commands need the command itself rewritten, which the tool cannot
    # do safely — so the check precedes the promotion branch.
    _fb_guidance = _foreground_background_guidance(command)
    if _fb_guidance:
        return f"⛔ run_terminal refused: {_fb_guidance}"

    # Hermes promotion (terminal_tool.py:966-971 + _PROMOTED_NOTE_POLL_ONLY):
    # an over-cap foreground timeout is a bounded job the caller wants to
    # wait for (test suites, builds). Refusing it only bought a mechanical
    # retry — "454 refusals in one run, every one re-sent lower/split/
    # background". Start it through the SAME tracked-background spawn the
    # start_terminal tool serves and tell the caller in the result.
    if timeout > _foreground_max_timeout():
        spawn = _spawn_tracked_background(command, config)
        if not spawn.startswith("Process started."):
            return spawn  # _hardline_refusal pass-through: note only on success
        return (
            f"{spawn}\n"
            f"Requested foreground timeout {timeout}s exceeds the "
            f"{_foreground_max_timeout()}s cap, so this command was started "
            "as a tracked background process instead of being refused. "
            "Do NOT re-run it. This session cannot receive completion "
            "notifications, so poll it with check_terminal (pass the "
            "Process ID above, wait_seconds as needed) and read its output "
            "with read_terminal_output until it exits."
        )

    # R3-1 POSIX-dialect guard — cmd.exe-fallback ONLY. Hermes' Windows
    # backend runs bash (git-bash/MSYS): there, POSIX IS the dialect and the
    # gate is obsolete by construction (field 2026-09-05: PowerShell cmdlets
    # into cmd.exe -> exit 255 twice -> recovery limit; the gate blocked
    # POSIX while the block taught PowerShell, and cmd runs NEITHER).
    _floor = _hardline_refusal(command)
    if _floor:
        return _floor
    violations = [] if select_shell(command)[2] == "bash" else _posix_violations(command)
    if violations:
        return (
            "⛔ run_terminal: this command uses POSIX-only shell that does not "
            "exist on this Windows environment — refusing to run it. Do NOT "
            "retry this command. "
            + " ".join(violations)
            + " Pivot: use the PowerShell/cmd equivalents shown, or keep all "
            "temp paths inside the workspace. Windows temp/fixtures belong under "
            "the workspace folder, e.g. .\\temp_app\\."
        )

    # D31: shadow snapshot BEFORE shell commands — `rm`, `git reset --hard`,
    # move/rename accidents are the #1 destruction vector. Per-turn dedup
    # makes this a no-op after the first mutation of the turn.
    # Read-only commands skip the snapshot entirely (field 2026-09-05:
    # `dir /b /s` paid a 24.3s checkpoint before a listing — hermes
    # checkpoints MUTATIONS, not reads). Unknown shapes still snapshot:
    # the safe default is pay-for-safety, not guess-read-only.
    if _looks_mutating(command):
        from src.tools.shadow_checkpoints import checkpoint_before_mutation
        _reason = "run_terminal: " + " ".join(command.split())[:80]
        checkpoint_before_mutation(workspace, _reason)

    # (timeout resolved above — hermes contract: model-owned, env-defaulted,
    # hard-capped. The old env-only re-read here silently discarded the
    # model's request.)

    # E2 guard: non-interactive transport. Interactive prompts read a TTY
    # that does not exist here, so a command that NEEDS one is an
    # environment failure, not something retrying harder can fix (the E2
    # model piped `printf '1\n1\n'` 13x at the same dead prompt).
    env = dict(os.environ)
    env["CI"] = "1"
    env["NO_COLOR"] = "1"

    try:
        argv, shell_flag, _dialect = select_shell(command)
        popen_kwargs = dict(
            cwd=workspace, shell=shell_flag, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=env,
        )
        if _IS_WINDOWS:
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True
        process_id = f"fg-{uuid.uuid4().hex[:8]}"
        output_path, output_file = _create_terminal_log(process_id)
        try:
            process = subprocess.Popen(argv if argv is not None else command, **popen_kwargs)
        except Exception:
            try:
                output_file.close()
                os.remove(output_path)
            except OSError:
                pass
            raise
        with _process_lock:
            _processes[process_id] = {
                "process": process,
                "command": command,
                "workspace": workspace,
                "output_path": output_path,
                "output_file": output_file,
                "startup_output": "",
                "line_count": 0,
                "cursor": 0,
                "capture_truncated": False,
                "captured_chars": 0,
                "foreground": True,
            }
        try:
            _raw = os.environ.get("CRUSORAI_TERMINAL_MAX_OUTPUT_CHARS", "12000")
            _max_chars = max(1_000, min(int(str(_raw).strip()), 1_000_000))
        except Exception:
            _max_chars = 12_000
        started = time.monotonic()
        session_id = str((config or {}).get("configurable", {}).get("thread_id", "default"))
        from src.runtime.turn_control import turn_controls
        from src.runtime.tool_middleware import current_tool_emitter
        status, stdout, stderr = _capture_foreground_process(
            process,
            started,
            timeout,
            is_cancelled=lambda: turn_controls.cancelled(session_id),
            emit=current_tool_emitter(),
            process_id=process_id,
            capture_limit=_max_chars,
        )
        if status == "cancelled":
            return (
                "⛔ Terminal command cancelled by the user before completion. "
                f"Command: {command}\nOutput log process ID: {process_id}. "
                "Use read_terminal_output with this ID to inspect captured output."
            )

        output = ""
        if stdout:
            output += f"STDOUT:\n{stdout}"
        if stderr:
            output += f"\nSTDERR:\n{stderr}"
        # The capture limit was applied while streaming; the complete output
        # remains available in the per-process log when capture was clipped.
        with _process_lock:
            process_data = _processes.get(process_id, {})
            capture_truncated = bool(process_data.get("capture_truncated"))
        if status == "timeout":
            partial = _limit_terminal_output(output.strip(), _max_chars) if output.strip() else ""
            message = (
                f"⛔ run_terminal timed out after {timeout}s (command may be blocked or hung): {command}. "
                "Retry only with a justified longer timeout, or use start_terminal for a long-running process. "
                f"Captured output remains available with read_terminal_output(process_id='{process_id}')."
            )
            return f"{message}\n\nPartial output:\n{partial}" if partial else message
        output += f"\nExit code: {process.returncode}"
        is_truncated = capture_truncated or len(output.strip()) > _max_chars
        final_output = _limit_terminal_output(output.strip(), _max_chars)
        if is_truncated:
            final_output += (
                f"\n\nFull output is available with read_terminal_output "
                f"(process_id='{process_id}', start_line=1, end_line=200)."
            )
        else:
            _discard_terminal_log(process_id)
        _record_verification_result(
            config, workspace, command, process.returncode, final_output
        )
        # hermes finalize_foreground_result (tools/terminal_tool_result.py):
        # the hint is computed from the same output the model sees and is
        # advisory only — the exit code above is NEVER rewritten. Field
        # 2026-09-10: `npm run build 2>&1 | tail -40` on a broken build
        # reports tail's exit 0 and the model read the run as Passed.
        hint = _failure_hint(command, process.returncode, final_output, None)
        if hint:
            final_output = f"{final_output}\n\nhint: {hint}"
        return final_output

    except subprocess.TimeoutExpired:
        return (
            "⛔ run_terminal timed out after "
            f"{timeout}s (blocking/interactive prompt detected or command "
            f"hung): {command}. TIP: this is an ENVIRONMENT failure — do "
            "NOT retry the same interactive command or pipe canned input. "
            "Pivot: use non-interactive flags (e.g. --yes, --no-input), "
            "write/place the files directly, or use start_terminal for a "
            "long-running process. "
            "(Exit 124 semantics: the command hit its timeout. Raise "
            "timeout= (foreground max 600s) or run it with start_terminal "
            "and read_terminal_output.)"
        )

    except Exception as error:
        return f"Terminal error: {error}"




@tool
def list_terminal_processes() -> str:
    """List terminal processes started by CrusorCodeAI and show their current status."""

    with _process_lock:
        if not _processes:
            return "No terminal processes found."

        lines = []

        for process_id, process_data in _processes.items():
            process = process_data["process"]
            return_code = process.poll()

            if return_code is None:
                status = "RUNNING"
            else:
                status = f"COMPLETED (exit code {return_code})"

            command = process_data["command"]

            lines.append(
                f"{process_id} | {status} | {command}"
            )

    return "\n".join(lines)


@tool
def stop_terminal(process_id: str) -> str:
    """Stop a running terminal process started by CrusorCodeAI."""

    with _process_lock:
        process_data = _processes.get(process_id)

        if process_data is None:
            return f"Unknown process ID: {process_id}"

        process = process_data["process"]

    return_code = process.poll()

    if return_code is not None:
        return (
            f"Process {process_id} is already completed "
            f"with exit code {return_code}."
        )

    try:
        if _IS_WINDOWS:
            process.terminate()
        else:
            import signal
            os.killpg(process.pid, signal.SIGTERM)

        try:
            process.wait(timeout=5)

        except subprocess.TimeoutExpired:
            if _IS_WINDOWS:
                process.kill()
            else:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()

        return (
            f"Process {process_id} stopped. "
            f"Exit code: {process.returncode}"
        )

    except Exception as error:
        return (
            f"Failed to stop process {process_id}: {error}"
        )




@tool
def cleanup_terminal_processes() -> str:
    """Remove completed terminal processes from CrusorCodeAI's process registry."""

    removed = []

    with _process_lock:
        for process_id in list(_processes.keys()):

            process_data = _processes[process_id]
            process = process_data["process"]

            if process.poll() is not None:
                removed.append(process_id)
                writer = process_data.get("output_file")
                if writer is not None:
                    try:
                        writer.flush()
                        writer.close()
                    except Exception:
                        pass
                output_path = process_data.get("output_path")
                del _processes[process_id]
                if output_path:
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass

    if not removed:
        return "No completed terminal processes to clean up."

    return (
        "Removed completed processes: "
        + ", ".join(removed)
    )







