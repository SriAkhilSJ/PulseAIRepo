"""Custom instructions loader for PulseAI.

Reads user-defined instructions from `.pulseai/instructions.md` files
in the workspace root. These instructions are injected into the system
prompt so the AI follows project-specific conventions.

Supports multiple instruction files:
- `.pulseai/instructions.md` — global Pulse instructions
- `.pulseai/instructions/{topic}.md` — topic-specific instructions
- `AGENTS.md` — agent instructions (Copilot-compatible)
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class InstructionFile:
    """A loaded instruction file."""
    path: str
    content: str
    topic: str
    priority: int = 0  # Higher = loaded first


class CustomInstructionsLoader:
    """Loads and caches custom instruction files from the workspace."""

    INSTRUCTIONS_DIR = ".pulseai"
    INSTRUCTIONS_FILE = "instructions.md"
    INSTRUCTIONS_TOPIC_DIR = "instructions"
    AGENTS_FILE = "AGENTS.md"

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict[str, list[InstructionFile]] = {}
        self._enabled = os.environ.get("PULSEAI_CUSTOM_INSTRUCTIONS", "1").strip().lower() in {
            "1", "true", "yes", "on",
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    def load_instructions(self, workspace: str) -> list[InstructionFile]:
        """Load all instruction files from the workspace."""
        if not self._enabled or not workspace:
            return []

        with self._lock:
            if workspace in self._cache:
                return self._cache[workspace]

        instructions: list[InstructionFile] = []
        workspace_path = Path(workspace)

        # 1. Load .pulseai/instructions.md (global)
        global_file = workspace_path / self.INSTRUCTIONS_DIR / self.INSTRUCTIONS_FILE
        if global_file.exists():
            try:
                content = global_file.read_text(encoding="utf-8")
                if content.strip():
                    instructions.append(InstructionFile(
                        path=str(global_file),
                        content=content,
                        topic="global",
                        priority=100,
                    ))
            except Exception:
                pass

        # 2. Load .pulseai/instructions/{topic}.md (topic-specific)
        topic_dir = workspace_path / self.INSTRUCTIONS_DIR / self.INSTRUCTIONS_TOPIC_DIR
        if topic_dir.is_dir():
            try:
                for topic_file in sorted(topic_dir.glob("*.md")):
                    try:
                        content = topic_file.read_text(encoding="utf-8")
                        if content.strip():
                            topic = topic_file.stem
                            instructions.append(InstructionFile(
                                path=str(topic_file),
                                content=content,
                                topic=topic,
                                priority=50,
                            ))
                    except Exception:
                        continue
            except Exception:
                pass

        # 3. Load AGENTS.md (Copilot-compatible)
        agents_file = workspace_path / self.AGENTS_FILE
        if agents_file.exists():
            try:
                content = agents_file.read_text(encoding="utf-8")
                if content.strip():
                    instructions.append(InstructionFile(
                        path=str(agents_file),
                        content=content,
                        topic="agents",
                        priority=30,
                    ))
            except Exception:
                pass

        # Sort by priority (highest first)
        instructions.sort(key=lambda x: x.priority, reverse=True)

        # Cache
        with self._lock:
            if len(self._cache) > 32:
                # Evict oldest
                keys = list(self._cache.keys())
                for k in keys[:16]:
                    del self._cache[k]
            self._cache[workspace] = instructions

        return instructions

    def format_instructions_for_prompt(self, workspace: str) -> str:
        """Format instructions as a string suitable for injection into the system prompt."""
        instructions = self.load_instructions(workspace)
        if not instructions:
            return ""

        parts = ["## Custom Instructions\n"]
        for instr in instructions:
            parts.append(f"### {instr.topic.title()} ({instr.path})\n")
            parts.append(instr.content.strip())
            parts.append("")

        return "\n".join(parts)

    def invalidate(self, workspace: str) -> None:
        """Invalidate cached instructions for a workspace."""
        with self._lock:
            self._cache.pop(workspace, None)


# Singleton
_custom_instructions_loader: CustomInstructionsLoader | None = None
_custom_instructions_lock = threading.Lock()


def get_custom_instructions_loader() -> CustomInstructionsLoader:
    global _custom_instructions_loader
    if _custom_instructions_loader is None:
        with _custom_instructions_lock:
            if _custom_instructions_loader is None:
                _custom_instructions_loader = CustomInstructionsLoader()
    return _custom_instructions_loader
