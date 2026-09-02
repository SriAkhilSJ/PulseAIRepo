
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

The consent rule
----------------
**If git can restore it, go ahead. If git can't, ask.**

    ignored by git  -> consent required, every time
    tracked/ignored-nothing -> no prompt, no approval round-trip
    no git to answer -> the pre-existing verdict, unchanged

A file the repo *declares* private (`.env`, credentials, machine-local config,
installed/generated trees) is private precisely because nothing will give it back.
A tracked file is the opposite: `git checkout --` is an undo button, so prompting on
it buys nothing and costs the agent its ability to fix its own work — the measured D9
deadlock, where `tsconfig.json` was blocked four times and the model declared
"Finished" on a broken app. So the nag is gone for exactly the class of writes that
should never have been interrupted, and consent is *wider* than before for the class
that matters, without us hand-maintaining a basename list of everyone's secrets.

Deliberately NOT `--no-index`: `git check-ignore` consults the index, so an ignored-by-
pattern path that somebody force-committed reports as *not* ignored and is treated as
recoverable — the rule answering correctly, not a loophole. Names on `CRITICAL_PATHS`
still ask regardless, because step 1 (the veto) runs before git is consulted: being
tracked is a reason to relax *friction*, never a reason to relax *secrets*.

Structure follows upstream Hermes, which gates on the resolved path rather than the
tool name and keeps a veto that outranks autonomous policies
(`acp_adapter/edit_approval.py::should_auto_approve_edit`, whose `_is_sensitive_auto_approve_path`
refuses to auto-approve anything with `.git`/`.ssh` in its parts). We keep that
`NEVER_AUTO_APPROVE_PARTS` list *in addition to* gitignore membership, because git
reports `.git/config` as not-ignored — the two checks are complements, not duplicates.
"""
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_UNSET = object()

class SafetyGuard:
    """
    Checks tool calls for safety before execution.
    """
    DANGEROUS_COMMANDS = {
        "del ", "rd /s", "mkfs", "dd ", "format ",
        ":(){ :|:& };:",  # fork bomb
    }
    # Match rm as a shell token instead of a raw substring. The old "rm"
    # pattern blocked harmless commands such as PowerShell's Format-Table;
    # the branch's interim "rm " fix still missed tabs and a bare `rm`.
    RM_COMMAND = re.compile(r"(?<![\w-])rm(?=\s|$)", re.IGNORECASE)

    CRITICAL_PATHS = {
        ".env", ".env.local", "secrets", "credentials",
        "id_rsa", "id_ed25519", ".aws", ".ssh",
    }

    #: Veto that outranks every policy, git's own answer included — upstream's
    #: `_is_sensitive_auto_approve_path`. `.git` in particular is reported as
    #: NOT ignored by `git check-ignore`, so this cannot be folded into it.
    NEVER_AUTO_APPROVE_PARTS = {".git", ".ssh", ".aws"}

    #: Tool -> the argument keys that name a path the call will write or read.
    #: One rule per path, so *choosing a different tool is not a way past the
    #: guard* (it used to be: `write_file` blocked `.env` on overwrite while
    #: `edit_file` blocked it always and `copy_file` was never consulted at all).
    PATH_ARGS = {
        "write_file": ("path",),
        "edit_file": ("path",),
        "copy_file": ("src", "dst"),
    }

    # `scaffold_nextjs` is deliberately absent: it takes only `packages` and acts on
    # the whole workspace, so there is no path to grant consent over. Its own guard is
    # "refuse a non-empty existing project", and a `("path",)` entry here would read a
    # key that never exists -- coverage that only looks like coverage.

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()
        self._repo_root = _UNSET

    def check_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> tuple[bool, str]:
        """
        Check if a tool call is safe. Returns (is_safe, warning_message).
        If not safe, the warning explains why and asks for confirmation.
        """
        # --- File mutations: one consent rule, evaluated per path ---
        keys = self.PATH_ARGS.get(tool_name)
        if keys:
            for key in keys:
                path = str(tool_args.get(key, "") or "")
                if not path:
                    continue
                blocked, warning = self._consent_for(tool_name, key, path)
                if blocked:
                    return False, warning
            return True, ""

        # --- Terminal command check ---
        if tool_name in ("run_terminal", "start_terminal"):
            command = tool_args.get("command", "")
            if self._is_dangerous_command(command):
                return False, self._dangerous_command_warning(command)

        # --- Default: safe ---
        return True, ""

    def _consent_for(self, tool_name: str, key: str, path: str) -> tuple[bool, str]:
        """Decide consent for one path touched by one call."""
        resolved = self._resolve_path(path)

        side = "read from" if (tool_name == "copy_file" and key == "src") else "write to"

        # 1. The veto, outranking git and any autonomous policy.
        if self._is_critical_path(path) or self._has_never_auto_part(resolved):
            warning = self._critical_file_warning(path)
            if side == "read from":
                # A read of a secret is not an "edit that breaks authentication",
                # and the model cannot route around a warning that mislabels the
                # risk: copying this file out is an exfiltration, not an overwrite.
                warning += (
                    f"\n\nThis call would **read from** `{path}` into another path. "
                    f"That moves the secret somewhere git *will* track — the copy lands "
                    f"in the repo, in the diff, and in the model's context."
                )
            return True, warning

        # 2. git's own answer, which is what "sensitive" means per repo.
        ignored = self._git_ignore_state(resolved)
        if ignored is False:
            # Recoverable by git: let the agent work. This is the D9 fix, now
            # the default rather than an opt-in flag.
            return False, ""
        if ignored is True:
            # Autonomous eval has no human to answer, so it keeps its historical
            # freedom for git-ignored-but-ordinary paths (`out/`, `dist/`, caches).
            # The veto above it — named secrets, `.git`, `.ssh` — never relaxes,
            # which is the same precedence upstream uses for sensitive paths.
            if os.environ.get("PULSEAI_AUTO_APPROVE_WRITES", "").strip() == "1":
                return False, ""
            return True, self._ignored_file_warning(tool_name, key, path)

        # 3. No git to ask (not a repo, git missing, timed out, or the escape
        # hatch PULSEAI_SAFETY_GITIGNORE=0): behave exactly as this guard did
        # before, so a host without git neither gains nor loses freedom.
        return self._legacy_verdict(tool_name, key, path, resolved)

    def _legacy_verdict(self, tool_name: str, key: str, path: str, resolved: Path) -> tuple[bool, str]:
        if tool_name in ("copy_file", "edit_file"):
            return False, ""
        if tool_name == "write_file" and resolved.exists():
            if os.environ.get("PULSEAI_AUTO_APPROVE_WRITES", "").strip() == "1":
                return False, ""
            return True, self._overwrite_warning(path)
        return False, ""

    def _has_never_auto_part(self, resolved: Path) -> bool:
        lowered = {part.lower() for part in resolved.parts}
        return bool(lowered & self.NEVER_AUTO_APPROVE_PARTS)

    def _git_root(self) -> Path | None:
        """Toplevel of the repo containing the workspace, cached (None = no git)."""
        if os.environ.get("PULSEAI_SAFETY_GITIGNORE", "1").strip() == "0":
            return None
        if self._repo_root is not _UNSET:
            return self._repo_root
        try:
            proc = self._git(["rev-parse", "--show-toplevel"])
            self._repo_root = Path(proc.stdout.strip()).resolve() if proc.returncode == 0 else None
        except Exception:
            self._repo_root = None
        return self._repo_root

    def _git_ignore_state(self, resolved: Path) -> bool | None:
        """True = ignored, False = not ignored, None = git could not answer.

        Index-aware on purpose (no `--no-index`): a tracked file that also matches
        an ignore rule is recoverable, so it must not demand consent.
        """
        root = self._git_root()
        if root is None:
            return None
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            # Outside the repo: git holds no copy of it, whatever else it does.
            return True
        if not rel.parts:
            return None
        try:
            proc = self._git(["check-ignore", "-q", "--", rel.as_posix()], cwd=root)
        except Exception:
            return None
        if proc.returncode == 0:
            return True
        if proc.returncode == 1:
            return False
        return None

    def _git(self, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(cwd or self.workspace), *args],
            capture_output=True,
            text=True,
            timeout=5,
            # Standing rule for this repo: never hand a child our own stdin.
            # Under the bridge fd 0 is the client's JSON-RPC pipe, so an
            # inherited stdin can steal protocol frames (and used to hang the
            # tool: see src/tools/terminal_tools.py).
            stdin=subprocess.DEVNULL,
        )

    def _ignored_file_warning(self, tool_name: str, key: str, path: str) -> str:
        side = "read from" if (tool_name == "copy_file" and key == "src") else "write to"
        return (
            f"🔒 **Consent required:** `{path}` is git-ignored, so nothing can give it "
            f"back if this {side} it goes wrong.\n\n"
            f"Git-ignored is how a repo says \"private or generated\" — secrets, "
            f"machine-local config, installed trees. This is not a block, and it is not "
            f"satisfiable for the session: a path git cannot restore is re-asked every "
            f"time.\n\n"
            f"Reply `yes` to go ahead this once, or point me at a tracked path."
        )

    def _resolve_path(self, path: str) -> Path:
        """Resolve with realpath — symlink aware."""
        import os as _os
        p = Path(path)
        raw = p if p.is_absolute() else self.workspace / p
        try:
            return Path(_os.path.realpath(str(raw)))
        except Exception:
            return raw.resolve()

    def _is_critical_path(self, path: str) -> bool:
        """Realpath + file_safety read-block check (defense-in-depth)."""
        try:
            from src.context.file_safety import get_read_block_error
            resolved = str(self._resolve_path(path))
            if get_read_block_error(resolved):
                return True
        except Exception:
            pass
        path_lower = str(path).lower()
        return any(critical in path_lower for critical in self.CRITICAL_PATHS)

    def _is_dangerous_command(self, command: str) -> bool:
        """Check if a shell command is dangerous.

        Command substitution ($() or backticks) ALWAYS escalates: the
        substring list only sees literal text, so `$(cat ~/.env)` would sail
        through as "safe-looking" while smuggling secrets into the context.
        (The reviewer's example `echo $(rm -rf /)` was already caught —
        "rm -rf" is a literal substring — but the general hole was real.)

        NOTE: this guard is a human checkpoint, not a sandbox. Determined
        obfuscation can always slip past regexes; approvals are the control.
        """
        if "$(" in command or "`" in command:
            return True
        cmd_lower = command.lower().strip()
        if self.RM_COMMAND.search(cmd_lower):
            return True
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
