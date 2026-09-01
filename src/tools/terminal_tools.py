import os
import platform
import re
import subprocess
import threading
import uuid
import time

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


# R3-1: POSIX-on-Windows guard. R3 (Test-3 retest) burned 25 identical calls
# sending POSIX shell (`mkdir -p /tmp/...`, `which npx`, `cp X /tmp`) against
# a Windows cmd/PowerShell shell — every one failed fast with "syntax
# incorrect" / "'which' is not recognized", yet the model retried the same
# shape. Hermes never sends a POSIX-only command to Windows; it translates
# paths (MSYS) and keeps temp dirs under its own cache, never /tmp. We detect
# the dialect mismatch BEFORE spawning and return a typed pivot so the loop
# learns the environment, not just the error.
_IS_WINDOWS = platform.system() == "Windows"

#: How long a cancelled foreground command may take to flush before we answer
#: anyway. Long enough for a well-behaved child to exit, short enough that a
#: grandchild holding the pipes cannot stall the turn.
_CANCEL_DRAIN_TIMEOUT_S = 2.0

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


# Stores currently known background processes
_processes = {}

# Protects _processes from simultaneous thread access
_process_lock = threading.Lock()


def _read_process_output(
    process_id: str,
    process: subprocess.Popen
):
    """Continuously collect output from a background process."""

    if process.stdout is None:
        return

    for line in iter(process.stdout.readline, ""):

        with _process_lock:
            process_data = _processes.get(process_id)

            if process_data is None:
                break

            process_data["output"].append(line)

    process.stdout.close()


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

        # Copy while holding the lock.
        output_lines = list(process_data["output"])

    total_lines = len(output_lines)

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

    selected_lines = output_lines[
        start_line - 1:actual_end
    ]

    output = "".join(selected_lines)

    return (
        f"Process ID: {process_id}\n"
        f"Total lines: {total_lines}\n"
        f"Showing lines: {start_line}-{actual_end}\n\n"
        f"{output}"
    )

@tool
def start_terminal(
    command: str,
    config: RunnableConfig
) -> str:
    """Start a long-running terminal command in the active workspace."""

    workspace = config["configurable"]["workspace"]

    process_id = str(uuid.uuid4())[:8]

    popen_kwargs = dict(
        cwd=workspace,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if _IS_WINDOWS:
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **popen_kwargs)

    # Store the process
    with _process_lock:
        _processes[process_id] = {
            "process": process,
            "command": command,
            "workspace": workspace,
            "output": [],
            "cursor": 0
        }

    # Start background output reader
    reader_thread = threading.Thread(
        target=_read_process_output,
        args=(process_id, process),
        daemon=True
    )

    reader_thread.start()

    return (
        f"Process started.\n"
        f"Process ID: {process_id}\n"
        f"Command: {command}"
    )
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

        start = process_data["cursor"]
        output_lines = process_data["output"][start:]

        process_data["cursor"] = len(
            process_data["output"]
    )

    return_code = process.poll()

    full_new_output = "".join(output_lines)

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


@tool
def run_terminal(
    command: str,
    config: RunnableConfig
) -> str:
    """
    Run a short terminal command inside the active workspace (shell).

    USE for quick commands: python scripts, tests, checks, environment
    inspection, verifying generated code. Inspect non-zero exit codes.

    DO NOT use for long-running installs/builds/servers (use
    start_terminal) or for reading known files (use read_file). Never run
    destructive commands unless explicitly requested and safe.
    """

    workspace = config["configurable"]["workspace"]

    # R3-1: POSIX-dialect guard. Detect POSIX-only verbs/paths being sent to a
    # Windows shell and pivot BEFORE spawning — R3's 25-command retry loop was
    # the SAME dialect error ("syntax incorrect" / "which not recognized")
    # repeated; each would otherwise spawn and fail fast, re-learning nothing.
    violations = _posix_violations(command)
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
    from src.tools.shadow_checkpoints import checkpoint_before_mutation
    _reason = "run_terminal: " + " ".join(command.split())[:80]
    checkpoint_before_mutation(workspace, _reason)

    # E2 guard: a blocking interactive CLI (e.g. `shadcn init` prompting
    # "Use arrow-keys") would otherwise hang forever in a headless agent.
    # Cap foreground time (default 120s, env-tunable) so a wedged subprocess
    # returns a parseable failure instead of eating a turn. 120s clears
    # legitimate first-run installs (E2's npm install took 36s) without
    # letting a dead interactive prompt block the loop forever.
    try:
        # Sized to real package installs (test5-2: npm install three on a
        # cold Windows cache legitimately runs minutes); env-overridable.
        timeout = int(os.environ.get("PULSEAI_TERMINAL_TIMEOUT", "300"))
    except (TypeError, ValueError):
        timeout = 120

    # E2 guard: non-interactive transport. Interactive prompts read a TTY
    # that does not exist here, so a command that NEEDS one is an
    # environment failure, not something retrying harder can fix (the E2
    # model piped `printf '1\n1\n'` 13x at the same dead prompt).
    env = dict(os.environ)
    env["CI"] = "1"
    env["NO_COLOR"] = "1"

    try:
        popen_kwargs = dict(
            cwd=workspace, shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", env=env,
        )
        if _IS_WINDOWS:
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **popen_kwargs)
        started = time.monotonic()
        stdout = stderr = ""
        session_id = str((config or {}).get("configurable", {}).get("thread_id", "default"))
        from src.runtime.turn_control import turn_controls
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if turn_controls.cancelled(session_id):
                    # TREE kill on both platforms: the same disease the timeout
                    # branch below already cures. process.terminate() stops only
                    # the shell wrapper on Windows, so the real child survives and
                    # keeps holding the stdout/stderr handles; the unguarded
                    # communicate() that followed then raised TimeoutExpired out of
                    # the loop and into the outer handler, which answered a
                    # cancellation with the TIMEOUT text (live round on a Windows
                    # host: the foreground-cancel contract never held there).
                    try:
                        if _IS_WINDOWS:
                            from src.context.git_context import _taskkill_tree
                            if not _taskkill_tree(process.pid):
                                process.kill()
                        else:
                            import signal
                            os.killpg(process.pid, signal.SIGTERM)
                    except Exception:
                        try:
                            process.kill()
                        except Exception:
                            pass
                    try:
                        # Bounded and never fatal. Orphaned grandchildren can keep
                        # the pipes open for their own lifetime, and a truthful
                        # "cancelled" beats whatever partial output we drop.
                        stdout, stderr = process.communicate(timeout=_CANCEL_DRAIN_TIMEOUT_S)
                    except Exception:
                        stdout, stderr = "", ""
                    return (
                        "⛔ Terminal command cancelled by the user before completion. "
                        f"Command: {command}"
                    )
                if time.monotonic() - started >= timeout:
                    # TREE kill, both platforms. process.kill() on Windows
                    # kills only the shell wrapper -- npm/node grandchildren
                    # survive, hold the stdout/stderr pipes, and the old
                    # unbounded communicate() then hung FOREVER (test5-2: no
                    # tool_call_end for 322s, watchdog kill on a healthy
                    # build). Same disease git_context's _taskkill_tree
                    # already cures; reuse it.
                    try:
                        if _IS_WINDOWS:
                            from src.context.git_context import _taskkill_tree
                            if not _taskkill_tree(process.pid):
                                process.kill()
                        else:
                            import signal
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except Exception:
                                process.kill()
                    except Exception:
                        process.kill()
                    try:
                        process.communicate(timeout=10)
                    except Exception:
                        pass  # pipes may be held by orphaned grandchildren; never hang here
                    raise subprocess.TimeoutExpired(command, timeout)

        output = ""
        if stdout:
            output += f"STDOUT:\n{stdout}"
        if stderr:
            output += f"\nSTDERR:\n{stderr}"
        output += f"\nExit code: {process.returncode}"
        final_output = output.strip()
        _record_verification_result(
            config, workspace, command, process.returncode, final_output
        )
        return final_output

    except subprocess.TimeoutExpired:
        return (
            "⛔ run_terminal timed out after "
            f"{timeout}s (blocking/interactive prompt detected or command "
            f"hung): {command}. TIP: this is an ENVIRONMENT failure — do "
            "NOT retry the same interactive command or pipe canned input. "
            "Pivot: use non-interactive flags (e.g. --yes, --no-input), "
            "write/place the files directly, or use start_terminal for a "
            "long-running process."
        )

    except Exception as error:
        return f"Terminal error: {error}"




@tool
def list_terminal_processes() -> str:
    """List terminal processes started by PulseCodeAI and show their current status."""

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
    """Stop a running terminal process started by PulseCodeAI."""

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
    """Remove completed terminal processes from PulseCodeAI's process registry."""

    removed = []

    with _process_lock:
        for process_id in list(_processes.keys()):

            process_data = _processes[process_id]
            process = process_data["process"]

            if process.poll() is not None:
                removed.append(process_id)
                del _processes[process_id]

    if not removed:
        return "No completed terminal processes to clean up."

    return (
        "Removed completed processes: "
        + ", ".join(removed)
    )







