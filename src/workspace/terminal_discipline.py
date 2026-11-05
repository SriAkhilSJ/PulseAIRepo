"""
src/workspace/terminal_discipline.py - Terminal & External Tool Discipline.

Phase 11.3: Workspace Discipline & Change Management.
Enforces:
1. Inspecting commands before execution to identify destructive filesystem or Git side-effects.
2. Blocking destructive Git commands (git reset, git clean, force push) without authorization.
3. Restricting dangerous deletion commands (rm -rf, del /s /q).
4. Permitting safe build and test commands (pytest, npm test, tsc).
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from src.workspace.models import RiskLevel

log = logging.getLogger("crusor.workspace.terminal")

# Explicit destructive patterns that must be blocked or require authorization
DESTRUCTIVE_COMMAND_PATTERNS = [
    (r"\bgit\s+reset\s+--hard\b", "Destructive git reset --hard discards uncommitted user changes."),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "Destructive git clean deletes untracked user files."),
    (r"\bgit\s+checkout\s+--\s+\.", "Destructive git checkout discards working tree edits."),
    (r"\bgit\s+restore\s+\.", "Destructive git restore discards working tree edits."),
    (r"\bgit\s+push\b.*--force", "Force pushing destroys remote repository history."),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f\b", "Recursive forced deletion can permanently destroy files."),
    (r"\bdel\s+/[sS]\s+/[qQ]\b", "Windows silent recursive deletion can destroy directory trees."),
    (r"\brmdir\s+/[sS]\s+/[qQ]\b", "Windows silent recursive directory removal."),
    (r"\bformat\b", "Drive formatting is strictly prohibited."),
]

SAFE_PREFIXES = frozenset({
    "pytest", "python -m pytest", "npm test", "npm run", "yarn test", "cargo test",
    "git status", "git diff", "git log", "git branch", "git rev-parse",
    "dir", "ls", "echo", "type", "cat", "findstr", "grep",
})


class TerminalSafetyBroker:
    """
    Evaluates terminal and execution broker commands against workspace discipline policies.
    """

    @classmethod
    def evaluate_command_safety(
        cls,
        command_line: str,
        has_explicit_authorization: bool = False,
    ) -> Tuple[bool, RiskLevel, str]:
        """
        Evaluates a proposed command line string.
        Returns (is_permitted, risk_level, reason).
        """
        cmd = command_line.strip()
        if not cmd:
            return True, RiskLevel.LOW_RISK, "Empty command."

        # Check against destructive patterns
        for pattern, reason in DESTRUCTIVE_COMMAND_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                if has_explicit_authorization:
                    return True, RiskLevel.HIGH_RISK, f"Authorized high-risk command: {reason}"
                return False, RiskLevel.PROHIBITED, f"Blocked destructive command: {reason} Explicit authorization required."

        # Check for dependency installation (MEDIUM RISK)
        if re.search(r"\b(pip\s+install|npm\s+install|yarn\s+add|cargo\s+add)\b", cmd, re.IGNORECASE):
            return True, RiskLevel.MEDIUM_RISK, "Dependency installation command modifies environment or manifests."

        # Check for Git commits or branch switches (HIGH RISK without authorization)
        if re.search(r"\bgit\s+(commit|branch|switch|checkout)\b", cmd, re.IGNORECASE) and not re.search(r"\bgit\s+checkout\s+[^\s]+\s+--\s+[^\s]+", cmd):
            if not has_explicit_authorization:
                return False, RiskLevel.HIGH_RISK, "Automated git commit or branch alteration requires explicit user approval."
            return True, RiskLevel.HIGH_RISK, "Authorized git operation."

        # Safe read-only or testing commands
        for safe in SAFE_PREFIXES:
            if cmd.lower().startswith(safe):
                return True, RiskLevel.LOW_RISK, "Safe development or test command."

        # Default standard execution
        return True, RiskLevel.LOW_RISK, "Standard task command."

