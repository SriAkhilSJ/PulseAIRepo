
"""
Reflection Engine for PulseCodeAI
=================================
After every task, the agent reflects on:
- What went well
- What went wrong
- What it would do differently next time
- What the user might want to do next

These reflections are stored as memories and surfaced in future tasks.

What this changes:
- The agent gets smarter with every task
- Users get proactive suggestions instead of silence
- Mistakes are turned into permanent lessons
"""
import json
import os
from datetime import datetime
from typing import Any

class ReflectionEngine:
    """
    Generates post-task reflections and proactive suggestions.
    """
    def __init__(self, storage_path: str | None = None):
        if storage_path is None:
            home = os.path.expanduser("~")
            pulse_dir = os.path.join(home, ".pulseai")
            os.makedirs(pulse_dir, exist_ok=True)
            self.storage_path = os.path.join(pulse_dir, "reflections.json")
        else:
            self.storage_path = storage_path

        self._reflections: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._reflections = data.get("reflections", [])
        except Exception:
            self._reflections = []

    def _save(self) -> None:
        try:
            data = {
                "reflections": self._reflections[-50:],  # keep last 50
                "last_saved": datetime.now().isoformat(),
            }
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        except Exception:
            pass

    def reflect(
        self,
        task: str,
        steps_completed: list[str],
        failed_steps: list[str],
        plan: list[dict],
    ) -> dict[str, Any]:
        """
        Generate a reflection after task completion.
        Returns a dict with reflection text and suggestions.
        """
        reflection = {
            "task": task,
            "timestamp": datetime.now().isoformat(),
            "success_count": len(steps_completed),
            "failure_count": len(failed_steps),
        }

        # --- What went well ---
        wins = []
        if steps_completed:
            wins.append(f"Completed {len(steps_completed)} steps successfully")
        if not failed_steps:
            wins.append("Zero failures — clean execution")
        if len(plan) > 3 and len(steps_completed) >= len(plan) * 0.8:
            wins.append("High plan adherence")

        # --- What went wrong ---
        lessons = []
        if failed_steps:
            lessons.append(f"Had {len(failed_steps)} failure(s): {failed_steps[-1][:100]}")
        if len(steps_completed) > len(plan) * 1.5:
            lessons.append("Took significantly more steps than planned — consider smaller plans")
        if failed_steps and any("recovery" in f.lower() for f in failed_steps):
            lessons.append("Recovery loops detected — root cause analysis could be faster")

        # --- Proactive suggestions ---
        suggestions = self._generate_suggestions(task, steps_completed, failed_steps)

        reflection["wins"] = wins
        reflection["lessons"] = lessons
        reflection["suggestions"] = suggestions

        self._reflections.append(reflection)
        self._save()
        return reflection

    def _generate_suggestions(
        self,
        task: str,
        steps_completed: list[str],
        failed_steps: list[str],
    ) -> list[str]:
        """
        Generate 2-3 logical next-step suggestions based on what was done.
        """
        suggestions = []
        task_lower = task.lower()

        # If we created code but no tests were mentioned
        code_created = any("wrote file" in s.lower() or "edited file" in s.lower() for s in steps_completed)
        test_mentioned = any("test" in s.lower() for s in steps_completed)

        if code_created and not test_mentioned:
            suggestions.append("🧪 Add tests for the new code")

        # If we fixed a bug
        if "bug" in task_lower or "fix" in task_lower or failed_steps:
            suggestions.append("🔍 Review edge cases to prevent similar issues")

        # If we created a new feature
        if any(w in task_lower for w in ["create", "build", "add", "implement"]):
            suggestions.append("📝 Add documentation or README updates")

        # If we installed packages
        if any("install" in s.lower() for s in steps_completed):
            suggestions.append("📦 Update requirements.txt or pyproject.toml")

        # If we modified config
        if any("config" in s.lower() for s in steps_completed):
            suggestions.append("⚙️ Verify the configuration works in different environments")

        # If nothing specific matched, give generic helpful ones
        if not suggestions:
            suggestions.append("🧹 Clean up any temporary files or debug code")
            suggestions.append("📊 Review the changes for performance or security issues")

        return suggestions[:3]

    def get_recent_lessons(self, n: int = 3) -> list[str]:
        """
        Return the last N lesson strings for injection into context.
        """
        lessons = []
        for r in self._reflections[-n:]:
            for lesson in r.get("lessons", []):
                if lesson not in lessons:
                    lessons.append(lesson)
        return lessons

    def format_suggestions(self, suggestions: list[str]) -> str:
        """
        Format suggestions for the user.
        """
        if not suggestions:
            return ""

        lines = ["", "### 💡 What would you like to do next?", ""]
        for s in suggestions:
            lines.append(f"- {s}")
        lines.append("")
        lines.append("*Just tell me, or say 'done' to wrap up.*")
        return "\n".join(lines)
