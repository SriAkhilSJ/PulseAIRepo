import subprocess
import threading
import uuid
import time

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


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

    process = subprocess.Popen(
        command,
        cwd=workspace,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

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
    """Terminal process rules:
- Use run_terminal for short commands.
- Use start_terminal for builds, installs, servers, compilation, and long-running commands.
- Use check_terminal to monitor processes started by start_terminal.
- When a process is still running, use wait_seconds on later checks instead of repeatedly polling immediately.
- Choose a reasonable wait based on the task. Short tasks may use 5-10 seconds; builds or installs may use longer waits.
- A wait_seconds value controls only how long to wait for status; it does not limit or terminate the process.
- Do not restart a command merely because it is still running."""

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


@tool
def run_terminal(
    command: str,
    config: RunnableConfig
) -> str:
    """
    Run a short terminal command inside the active workspace.

    WHEN TO USE:
    - Running Python scripts: python script.py
    - Running quick tests or checks.
    - Inspecting environment state with short commands.
    - Verifying generated code works.

    WHEN NOT TO USE:
    - Do not use for long installs, builds, servers, or commands that keep running; use start_terminal.
    - Do not use for reading known files; use read_file for accuracy.
    - Do not run destructive commands unless explicitly requested and safe.

    RETURNS:
    - stdout/stderr plus exit code. Always inspect non-zero exit codes.
    """

    workspace = config["configurable"]["workspace"]

    # D31: shadow snapshot BEFORE shell commands — `rm`, `git reset --hard`,
    # move/rename accidents are the #1 destruction vector. Per-turn dedup
    # makes this a no-op after the first mutation of the turn.
    from src.tools.shadow_checkpoints import checkpoint_before_mutation
    _reason = "run_terminal: " + " ".join(command.split())[:80]
    checkpoint_before_mutation(workspace, _reason)

    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True
        )

        output = ""

        if result.stdout:
            output += f"STDOUT:\n{result.stdout}"

        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"

        output += f"\nExit code: {result.returncode}"

        return output.strip()

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
        process.terminate()

        try:
            process.wait(timeout=5)

        except subprocess.TimeoutExpired:
            process.kill()
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







