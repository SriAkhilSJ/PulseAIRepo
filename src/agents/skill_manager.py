
"""
Skill Manager for PulseCodeAI
=============================
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
"""
import json
import os
from typing import Any

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
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                self._skills = json.load(f)
        except Exception:
            self._skills = []

    def _save(self) -> None:
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self._skills, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def add_skill(self, name: str, triggers: list[str], instruction: str) -> None:
        """
        Add a new skill.
        Args:
            name: Skill name (e.g., "Type Hint Rule")
            triggers: Keywords that activate this skill (e.g., ["python", "function"])
            instruction: The prompt text injected when triggered
        """
        # Remove existing skill with same name
        self._skills = [s for s in self._skills if s["name"] != name]
        self._skills.append({
            "name": name,
            "triggers": [t.lower() for t in triggers],
            "instruction": instruction,
            "enabled": True,
        })
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

    def get_relevant_skills(self, task: str) -> list[str]:
        """
        Return instructions for skills whose triggers match the task.
        """
        task_lower = task.lower()
        instructions = []
        for skill in self._skills:
            if not skill.get("enabled", True):
                continue
            if any(trigger in task_lower for trigger in skill["triggers"]):
                instructions.append(f"**{skill['name']}:** {skill['instruction']}")
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

# Global singleton
skill_manager = SkillManager()
