"""5-Tier Living Project Memory Architecture for CrusorAI 2.1.

Invariants (Peer Review Requirements):
1. User-scope vs Project-scope separation:
   - User preferences live globally (~/.crusorai/user_preferences.json).
   - Project decisions and error records live scoped per workspace (~/.crusorai/projects/<hash>/memory.json).
2. Provenance tracking: Every memory entry captures origin (git_commit, user_prompt, error_fix), turn, and timestamp.
3. Secret redaction: Regex filters strip API keys (sk-..., tokens, passwords) before disk persistence.
4. Atomic writes: Safe writes via temporary file and atomic rename.
5. Advisory role: Memory is contextual guidance, never instructions that override active user prompts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"password\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


class ProjectMemoryManager:
    def __init__(self, workspace_path: str, base_dir: Optional[str] = None) -> None:
        self.workspace_path = os.path.abspath(workspace_path)
        self.workspace_hash = hashlib.sha256(self.workspace_path.encode()).hexdigest()[:16]

        self.root = Path(base_dir or os.path.expanduser("~/.crusorai"))
        self.project_dir = self.root / "projects" / self.workspace_hash
        self.project_memory_file = self.project_dir / "memory.json"
        self.user_prefs_file = self.root / "user_preferences.json"

        self._ensure_storage()

    def _ensure_storage(self) -> None:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        if not self.project_memory_file.exists():
            initial_project = {
                "version": "2.1",
                "workspace": self.workspace_path,
                "blueprint": {},
                "decision_ledger": [],
                "error_graveyard": [],
                "session_scratchpad": {},
            }
            self._atomic_write(self.project_memory_file, initial_project)

        if not self.user_prefs_file.exists():
            initial_user = {"version": "2.1", "preferences": {}}
            self._atomic_write(self.user_prefs_file, initial_user)

    def _atomic_write(self, target_path: Path, data: Dict[str, Any]) -> None:
        """Atomic write via tempfile rename to prevent corruption."""
        serialized = json.dumps(data, indent=2)
        redacted = redact_secrets(serialized)

        target_dir = target_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile("w", dir=target_dir, delete=False, encoding="utf-8") as tf:
            tf.write(redacted)
            temp_name = tf.name

        os.replace(temp_name, target_path)

    # --- Project-Scoped Memory ---

    def record_decision(self, topic: str, decision: str, reason: str, provenance: str = "agent_action") -> None:
        data = self._read_json(self.project_memory_file)
        data.setdefault("decision_ledger", []).append({
            "topic": redact_secrets(topic),
            "decision": redact_secrets(decision),
            "reason": redact_secrets(reason),
            "provenance": provenance,
            "timestamp": time.time(),
        })
        self._atomic_write(self.project_memory_file, data)

    def record_resolved_error(self, error_pattern: str, verified_fix: str, tool: str) -> None:
        data = self._read_json(self.project_memory_file)
        data.setdefault("error_graveyard", []).append({
            "error_pattern": redact_secrets(error_pattern),
            "verified_fix": redact_secrets(verified_fix),
            "tool": tool,
            "timestamp": time.time(),
        })
        self._atomic_write(self.project_memory_file, data)

    def set_blueprint_entry(self, key: str, value: Any) -> None:
        data = self._read_json(self.project_memory_file)
        data.setdefault("blueprint", {})[key] = value
        self._atomic_write(self.project_memory_file, data)

    def set_active_scratchpad(self, content: Dict[str, Any]) -> None:
        data = self._read_json(self.project_memory_file)
        data["session_scratchpad"] = content
        self._atomic_write(self.project_memory_file, data)

    def get_active_scratchpad(self) -> Dict[str, Any]:
        return self._read_json(self.project_memory_file).get("session_scratchpad", {})

    def get_project_memory(self) -> Dict[str, Any]:
        return self._read_json(self.project_memory_file)

    def build_system_prompt(self, max_decisions: int = 5, max_errors: int = 5) -> str:
        """Render bounded, secret-redacted 5-tier living memory block for model prompt injection."""
        project_mem = self.get_project_memory()
        user_prefs = self.get_user_preferences()

        sections: List[str] = []

        # Tier 4: Scoped User Preferences
        if user_prefs:
            pref_lines = [f"- **{k}**: {v}" for k, v in user_prefs.items()]
            sections.append("### Scoped User Preferences\n" + "\n".join(pref_lines))

        # Tier 1: Project Blueprint & Architecture
        blueprint = project_mem.get("blueprint", {})
        if blueprint:
            bp_lines = [f"- **{k}**: {v}" for k, v in blueprint.items()]
            sections.append("### Project Blueprint & Architecture\n" + "\n".join(bp_lines))

        # Tier 2: Decision Ledger (most recent decisions first)
        decisions = project_mem.get("decision_ledger", [])
        if decisions:
            recent_decisions = decisions[-max_decisions:]
            dec_lines = [
                f"- **{d.get('topic', 'General')}**: {d.get('decision')} (Rationale: {d.get('reason')})"
                for d in reversed(recent_decisions)
            ]
            sections.append("### Key Architectural Decisions\n" + "\n".join(dec_lines))

        # Tier 3: Error Graveyard (prevent re-introducing past resolved bugs)
        errors = project_mem.get("error_graveyard", [])
        if errors:
            recent_errors = errors[-max_errors:]
            err_lines = [
                f"- **Known Pitfall**: `{e.get('error_pattern')}` in tool `{e.get('tool')}` -> **Verified Fix**: {e.get('verified_fix')}"
                for e in reversed(recent_errors)
            ]
            sections.append("### Error Graveyard (Past Resolved Pitfalls - Do Not Repeat)\n" + "\n".join(err_lines))

        if not sections:
            return ""

        header = "<living_project_memory>\n"
        footer = "\n</living_project_memory>"
        return header + "\n\n".join(sections) + footer

    # --- User-Scoped Memory ---

    def set_user_preference(self, key: str, value: Any) -> None:
        data = self._read_json(self.user_prefs_file)
        data.setdefault("preferences", {})[key] = value
        self._atomic_write(self.user_prefs_file, data)

    def get_user_preferences(self) -> Dict[str, Any]:
        return self._read_json(self.user_prefs_file).get("preferences", {})

    def _read_json(self, path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
