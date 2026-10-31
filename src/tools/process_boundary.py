"""
process_boundary.py - Structured Process Execution Boundary.

Pillar 3 of the Hardened Production Architecture.
- Enforces structured argv vectoring (subprocess with shell=False).
- Enforces strict workspace jailing to prevent traversal outside project roots.
- Intercepts conversational monologue leakage before execution.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional


class ProcessBoundaryViolation(Exception):
    """Raised when a command violates workspace jailing or process safety."""
    pass


# Heuristic patterns that indicate conversational monologue leaking into terminal commands
_CONVERSATIONAL_LEAK_PATTERNS = [
    re.compile(r"^(?:sure|certainly|okay|ok|i will|let me|now i will|let's|i'll)\b", re.IGNORECASE),
    re.compile(r"^(?:here is|below is|i am going to)\b", re.IGNORECASE),
    re.compile(r"(?:first,|next,|finally,)\s+(?:i will|we will)", re.IGNORECASE),
]


def detect_conversational_leak(cmd_string: str) -> Optional[str]:
    """Detect if raw model commentary was accidentally passed as a shell command."""
    cleaned = cmd_string.strip()
    # Check for prose introductory phrases
    for pat in _CONVERSATIONAL_LEAK_PATTERNS:
        if pat.search(cleaned):
            return f"Conversational commentary detected in command string: {cleaned[:60]}..."
    # Check for long un-tokenizable prose (multiple sentences with punctuation)
    if "\n\n" in cleaned or (cleaned.count(". ") >= 2 and not any(p in cleaned for p in [".py", ".sh", ".js", "./"])):
        return "Command appears to contain multiple sentences of natural language text."
    return None


def execute_sandboxed_command(
    cmd_string: str,
    workspace_root: Path | str,
    timeout_s: float = 60.0,
    env_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Execute a command within strict workspace boundaries using structured argv."""
    workspace = Path(workspace_root).resolve()
    if not workspace.exists() or not workspace.is_dir():
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": f"Error: Workspace directory '{workspace}' does not exist.",
        }

    raw_cmd = cmd_string.strip()
    if not raw_cmd:
        return {"exit_code": 1, "stdout": "", "stderr": "Error: Command string is empty."}

    # 1. Pre-flight sanity: prevent raw prose monologue leaks
    leak_error = detect_conversational_leak(raw_cmd)
    if leak_error:
        return {
            "exit_code": 2,
            "stdout": "",
            "stderr": f"Error [ProcessBoundary]: Rejected prose command. {leak_error}",
        }

    # 2. Tokenize into structured argv vector
    try:
        # On POSIX or Windows bash environments, posix=True splits quotes cleanly
        tokens = shlex.split(raw_cmd, posix=(os.name != "nt"))
    except ValueError as ve:
        return {
            "exit_code": 2,
            "stdout": "",
            "stderr": f"Error [ProcessBoundary]: Command parsing error: {ve}",
        }

    if not tokens:
        return {"exit_code": 1, "stdout": "", "stderr": "Error: No command tokens found."}

    # 3. Workspace jailing: check for directory traversal escapes (e.g. cd ../../../)
    for i, token in enumerate(tokens):
        if token == "cd" and i + 1 < len(tokens):
            target_dir = (workspace / tokens[i + 1]).resolve()
            if not str(target_dir).startswith(str(workspace)):
                return {
                    "exit_code": 3,
                    "stdout": "",
                    "stderr": f"Error [ProcessBoundary]: Directory traversal outside workspace jailed root: {target_dir}",
                }

    # 4. Environment preparation
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    # 5. Safe execution
    try:
        # On Windows, when executing standard binaries (python, git, npm), run directly without shell
        # If shell features like pipes or redirects are present, use controlled shell invocation
        has_shell_operators = any(op in raw_cmd for op in ["|", "&&", "||", ";", ">", "<"])
        use_shell = has_shell_operators

        proc = subprocess.run(
            raw_cmd if use_shell else tokens,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=use_shell,
            env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": 124,
            "stdout": "",
            "stderr": f"Error: Command timed out after {timeout_s} seconds.",
        }
    except Exception as exc:
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": f"Error: Command execution failed: {exc}",
        }
