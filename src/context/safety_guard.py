
"""
Safety Guard for PulseCodeAI
==============================
Intercepts potentially destructive tool calls and asks for confirmation.
Protects against:
- Overwriting existing files
- Deleting files or directories
- Running dangerous shell commands
- Editing critical config files without review

What this changes:
- The agent pauses before doing something risky
- Users feel safe letting the agent run autonomously
- Accidental data loss is prevented
"""
import os
from pathlib import Path
from typing import Any

class SafetyGuard:
    """
    Checks tool calls for safety before execution.
    """
    DANGEROUS_COMMANDS = {
        "rm", "rm -rf", "del ", "rd /s", "mkfs", "dd ", "format ",
        ":(){ :|:& };:",  # fork bomb
    }

    CRITICAL_PATHS = {
        ".env", ".env.local", "secrets", "credentials",
        "id_rsa", "id_ed25519", ".aws", ".ssh",
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def check_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> tuple[bool, str]:
        """
        Check if a tool call is safe. Returns (is_safe, warning_message).
        If not safe, the warning explains why and asks for confirmation.
        """
        # --- File overwrite check ---
        if tool_name == "write_file":
            path = tool_args.get("path", "")
            full_path = self._resolve_path(path)
            if full_path.exists():
                return False, self._overwrite_warning(path)

        # --- File edit check ---
        if tool_name == "edit_file":
            path = tool_args.get("path", "")
            if self._is_critical_path(path):
                return False, self._critical_file_warning(path)

        # --- Terminal command check ---
        if tool_name in ("run_terminal", "start_terminal"):
            command = tool_args.get("command", "")
            if self._is_dangerous_command(command):
                return False, self._dangerous_command_warning(command)

        # --- Default: safe ---
        return True, ""

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to workspace."""
        p = Path(path)
        if p.is_absolute():
            return p
        return self.workspace / p

    def _is_critical_path(self, path: str) -> bool:
        """Check if path points to a critical/sensitive file."""
        path_lower = str(path).lower()
        return any(critical in path_lower for critical in self.CRITICAL_PATHS)

    def _is_dangerous_command(self, command: str) -> bool:
        """Check if a shell command is dangerous."""
        cmd_lower = command.lower().strip()
        return any(danger in cmd_lower for danger in self.DANGEROUS_COMMANDS)

    def _overwrite_warning(self, path: str) -> str:
        return (
            f"⚠️ **Safety Check:** The file `{path}` already exists.\n\n"
            f"Running this will **overwrite** the existing content.\n\n"
            f"Are you sure you want to proceed? Reply with:\n"
            f"- `yes` or `y` to overwrite\n"
            f"- `no` or `n` to cancel\n"
            f"- A new path if you want to save elsewhere"
        )

    def _critical_file_warning(self, path: str) -> str:
        return (
            f"🔒 **Safety Check:** `{path}` looks like a sensitive file "
            f"(credentials, secrets, or config).\n\n"
            f"Editing this could break authentication or expose secrets.\n\n"
            f"Please confirm you want to edit this file, or tell me to use a different approach."
        )

    def _dangerous_command_warning(self, command: str) -> str:
        return (
            f"🛑 **Safety Check:** The command `{command}` looks destructive.\n\n"
            f"I've blocked it to prevent accidental data loss.\n\n"
            f"If you're sure, tell me exactly what you want to delete and why, "
            f"and I'll help you do it safely."
        )
