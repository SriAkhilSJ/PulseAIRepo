"""
Skill Manager for PulseCodeAI
============================
Teach the agent reusable patterns and preferences.
Skills are automatically injected into context when relevant.

Examples:
- "Always use type hints"
- "Prefer FastAPI over Flask"
- "Write Google-style docstrings"
- "Use black formatting"

What this changes:
- The agent remembers your preferences without repeating them
- Skills trigger automatically based on task keywords
- The agent feels personalized to your workflow

D39 (hermes curator + skill_usage): skills now carry lifecycle metadata —
`created_by` provenance ("user" vs "agent"), `pinned` (exempts a skill from
every auto-transition), usage telemetry (`use_count` / `view_count` /
`patch_count` / `last_activity_at`), and a curator state machine
(active -> stale -> archived) that ONLY touches agent-created skills, never
deletes, and leaves pinned skills alone. `skills_manifest()` emits a compact
byte-stable index (the hermes skills-index manifest idea).
"""
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

_DEFAULT_STALE_AFTER_DAYS = 30
_DEFAULT_ARCHIVE_AFTER_DAYS = 90

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_NOW = lambda: _utcnow().isoformat(timespec="seconds")


def _iso_to_dt(iso: str) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None


class SkillManager:
    """
    Manages user-defined skills that inject into agent context.
    """
    def __init__(self, storage_path: str | None = None):
        if storage_path is None:
            home = os.path.expanduser("~")
            pulse_dir = os.path.join(home, ".pulseai")
            os.makedirs(pulse_dir, exist_ok=True)
            self.storage_path = os.path.join(pulse_dir, "skills.json")
        else:
            self.storage_path = storage_path

        self._skills: list[dict] = []
        # D39: single writer for skills.json — the skills layer injects on
        # every build in the dashboard's worker threads.
        self._save_lock = threading.Lock()
        self._load()

    # =========================================================
    # PERSISTENCE
    # =========================================================

    def _ensure_metadata(self, skill: dict) -> dict:
        """Normalize a (possibly legacy) skill dict to the D39 lifecycle
        shape. Returns the skill dict (mutated) with defaults filled."""
        skill.setdefault("enabled", True)
        skill.setdefault("created_by", "user")
        skill.setdefault("pinned", False)
        skill.setdefault("state", "active")
        skill.setdefault("use_count", 0)
        skill.setdefault("view_count", 0)
        skill.setdefault("patch_count", 0)
        skill.setdefault("created_at", _NOW())
        skill.setdefault("updated_at", None)
        skill.setdefault("last_activity_at", None)
        return skill

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                self._skills = [self._ensure_metadata(s) for s in raw if isinstance(s, dict)]
        except Exception:
            self._skills = []

    def _save(self) -> None:
        with self._save_lock:
            try:
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(self._skills, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    # =========================================================
    # CRUD
    # =========================================================

    def add_skill(
        self,
        name: str,
        triggers: list[str],
        instruction: str,
        *,
        created_by: str = "user",
        pinned: bool = False,
    ) -> None:
        """
        Add a new skill (or update an existing one by name).
        Args:
            name: Skill name (e.g., "Type Hint Rule")
            triggers: Keywords that activate this skill (e.g., ["python", "function"])
            instruction: The prompt text injected when triggered
            created_by: "user" (foreground user-facing path) or "agent"
                (self-curation). Curator transitions only touch "agent".
            pinned: True exempts the skill from every auto-transition.
        """
        existing = next((s for s in self._skills if s["name"] == name), None)
        if existing:
            existing["triggers"] = [t.lower() for t in triggers]
            existing["instruction"] = instruction
            existing["enabled"] = True
            existing["pinned"] = existing.get("pinned", False) or pinned
            existing["state"] = "active"  # editing reactivates a stale/archived skill
            existing["patch_count"] = int(existing.get("patch_count", 0)) + 1
            existing["updated_at"] = _NOW()
            existing["last_activity_at"] = _NOW()
            self._save()
            return
        self._skills.append(self._ensure_metadata({
            "name": name,
            "triggers": [t.lower() for t in triggers],
            "instruction": instruction,
            "enabled": True,
            "created_by": created_by,
            "pinned": pinned,
            "state": "active",
            "created_at": _NOW(),
            "updated_at": _NOW(),
            "last_activity_at": _NOW(),
        }))
        self._save()

    def remove_skill(self, name: str) -> bool:
        original_len = len(self._skills)
        self._skills = [s for s in self._skills if s["name"] != name]
        self._save()
        return len(self._skills) < original_len

    def toggle_skill(self, name: str, enabled: bool) -> bool:
        for skill in self._skills:
            if skill["name"] == name:
                skill["enabled"] = enabled
                self._save()
                return True
        return False

    def list_skills(self) -> list[dict]:
        return list(self._skills)

    def get_usage(self, name: str) -> dict | None:
        """D39: telemetry snapshot for one skill."""
        skill = next((s for s in self._skills if s["name"] == name), None)
        if skill is None:
            return None
        return {
            "use_count": skill.get("use_count", 0),
            "view_count": skill.get("view_count", 0),
            "patch_count": skill.get("patch_count", 0),
            "state": skill.get("state", "active"),
            "pinned": skill.get("pinned", False),
            "created_by": skill.get("created_by", "user"),
            "last_activity_at": skill.get("last_activity_at"),
        }

    # =========================================================
    # USAGE TELEMETRY (D39)
    # =========================================================

    def record_usage(self, name: str, action: str) -> None:
        """Record a usage event for a skill and persist.

        action: "use" (injected into context), "view" (inspected), or
        "patch" (updated). Pinned/archived skills still count usage.
        """
        skill = next((s for s in self._skills if s["name"] == name), None)
        if skill is None:
            return
        if action == "use":
            skill["use_count"] = int(skill.get("use_count", 0)) + 1
        elif action == "view":
            skill["view_count"] = int(skill.get("view_count", 0)) + 1
        elif action == "patch":
            skill["patch_count"] = int(skill.get("patch_count", 0)) + 1
        else:
            return
        skill["last_activity_at"] = _NOW()
        self._save()

    # =========================================================
    # SELECTION / INJECTION
    # =========================================================

    def get_relevant_skills(self, task: str) -> list[str]:
        """
        Return instructions for enabled, non-archived skills whose triggers
        match the task, and record 'use' telemetry for each match.
        """
        task_lower = (task or "").lower()
        instructions = []
        for skill in self._skills:
            if not skill.get("enabled", True):
                continue
            if skill.get("state") == "archived":
                continue
            if any(trigger in task_lower for trigger in skill.get("triggers", [])):
                instructions.append(f"**{skill['name']}:** {skill['instruction']}")
                self.record_usage(skill["name"], "use")
        return instructions

    def get_skills_text(self, task: str) -> str:
        """
        Return formatted skills text for context injection.
        """
        instructions = self.get_relevant_skills(task)
        if not instructions:
            return ""
        lines = ["=== ACTIVE SKILLS ==="]
        lines.append("The following user preferences apply to this task:\n")
        for inst in instructions:
            lines.append(f"- {inst}")
        lines.append("\nFollow these preferences when completing the task.")
        return "\n".join(lines)

    def skills_manifest(self) -> str:
        """D39: compact, byte-stable index of all enabled skills. Stable as
        long as the skills file doesn't change (the hermes skills-index
        manifest idea, sans the token bloat of full instructions)."""
        rows = []
        for skill in self._skills:
            if not skill.get("enabled", True):
                continue
            marker = " [pinned]" if skill.get("pinned") else ""
            rows.append(f"- **{skill['name']}** ({', '.join(skill.get('triggers', []))}){marker}")
        if not rows:
            return ""
        return "=== SKILLS INDEX ===\n" + "\n".join(rows)

    # =========================================================
    # CURATOR (D39, hermes curator.py)
    # =========================================================

    def curator_run(
        self,
        stale_after_days: int = _DEFAULT_STALE_AFTER_DAYS,
        archive_after_days: int = _DEFAULT_ARCHIVE_AFTER_DAYS,
    ) -> list[dict[str, Any]]:
        """Auto-transition agent-created skills: active -> stale ->
        archived based on last_activity_at. Invariants: only created_by ==
        "agent"; pinned skills exempt; NEVER deletes (archive is the most
        destructive action); archived skills already stay archived.

        Returns a report of transitions performed (empty when nothing
        moved). Called on demand (e.g. after a background review run)."""
        report: list[dict[str, Any]] = []
        now = _utcnow()
        changed = False
        for skill in self._skills:
            if skill.get("created_by") != "agent":
                continue
            if skill.get("pinned"):
                continue
            state = skill.get("state", "active")
            if state == "archived":
                continue
            last = _iso_to_dt(skill.get("last_activity_at"))
            if last is None:
                continue
            age_days = (now - last).days
            new_state = state
            if age_days >= archive_after_days:
                new_state = "archived"
            elif age_days >= stale_after_days:
                new_state = "stale"
            if new_state != state:
                skill["state"] = new_state
                skill["updated_at"] = _NOW()
                changed = True
                report.append({
                    "name": skill["name"],
                    "from": state,
                    "to": new_state,
                    "idle_days": age_days,
                })
        if changed:
            self._save()
        return report

# Global singleton
skill_manager = SkillManager()