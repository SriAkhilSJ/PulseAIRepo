
"""
Memory Validator for PulseCodeAI
================================
Checks whether retrieved long-term memories are still valid.
If a memory references a file that no longer exists, or describes
a solution that no longer matches the codebase, it flags the memory
as potentially stale.

What this changes:
- The agent doesn't blindly trust outdated memories
- Stale memories are warned about, not silently used
- The agent can ask the user to confirm before using old solutions
"""
import os
import re
from pathlib import Path
from typing import Any

class MemoryValidator:
    """
    Validates memories against the current filesystem state.
    """
    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace)

    def validate_memories(
        self,
        memories: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Check each memory for staleness. Returns the same list with
        a 'stale_warning' field added to any suspicious memories.
        """
        validated = []
        for memory in memories:
            mem_copy = dict(memory)
            warnings = []
            text = memory.get("text", "")
            if not text:
                validated.append(mem_copy)
                continue

            # Check for referenced file paths
            paths = self._extract_paths(text)
            for p in paths:
                full_path = self.workspace / p
                if not full_path.exists():
                    warnings.append(f"Referenced file '{p}' no longer exists")
                else:
                    # If the file exists but is very different, warn
                    try:
                        current_content = full_path.read_text(encoding="utf-8")
                        # If memory mentions specific code that isn't in the file
                        code_snippets = self._extract_code_snippets(text)
                        for snippet in code_snippets:
                            clean_snippet = snippet.strip()
                            if len(clean_snippet) > 20 and clean_snippet not in current_content:
                                warnings.append(f"File '{p}' may have changed significantly")
                                break
                    except Exception:
                        pass

            if warnings:
                mem_copy["stale_warning"] = " | ".join(warnings)
                mem_copy["confidence"] = "low"
            else:
                mem_copy["confidence"] = "high"

            validated.append(mem_copy)
        return validated

    def _extract_paths(self, text: str) -> list[str]:
        """
        Extract likely file paths from memory text.
        """
        # Match patterns like src/main.py, ./config/settings.py, or just file.py
        pattern = r"(?:[\w\-]+/)*[\w\-]+\.(?:py|js|ts|json|toml|yaml|yml|md|txt|html|css|sql)"
        matches = re.findall(pattern, text)

        # Deduplicate and filter to reasonable paths
        seen = set()
        result = []
        for m in matches:
            if m not in seen and len(m) < 200:
                seen.add(m)
                result.append(m)
        return result

    def _extract_code_snippets(self, text: str) -> list[str]:
        """
        Extract likely code snippets from memory text.
        Looks for text inside backticks or indented blocks.
        """
        # Fenced code blocks
        fenced = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
        # Inline code
        inline = re.findall(r"`([^`]+)`", text)
        return fenced + inline
