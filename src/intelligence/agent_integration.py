"""
agent_integration.py -- Integration with Crusor Agent Core & Targeted Context Retrieval.

Phase 11.0: Project & Repository Intelligence.
Provides targeted, task-specific repository intelligence to the Crusor Agent:
- Context for Planning & Task Understanding
- Context for Code Editing & File Selection
- Context for Debugging & Verification
- Bounded token footprint: avoids flooding context window with redundant data.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.intelligence.models import ProjectKnowledge
from src.intelligence.persistence import PersistentProjectIntelligenceManager

log = logging.getLogger("crusorai.intelligence.agent_integration")


class ProjectIntelligenceRetriever:
    """
    Supplies targeted project intelligence slices tailored to specific agent tasks.
    """

    def __init__(self, manager: PersistentProjectIntelligenceManager) -> None:
        self.manager = manager

    def get_planning_context(self, task_description: str) -> Dict[str, Any]:
        """
        Extract high-level architectural intelligence for planning tasks.
        """
        k = self.manager.get_project_knowledge()
        components_summary = [
            f"- {c.name} ({c.category}): {', '.join(c.responsibilities)}"
            for c in k.architecture_map.components.values()
        ][:8]

        frameworks_summary = [f"{f.name} ({f.category})" for f in k.frameworks]

        return {
            "project_name": k.project_name,
            "project_type": k.project_type.value.value,
            "project_purpose": k.project_purpose.value,
            "frameworks": frameworks_summary,
            "languages": list(k.languages.keys()),
            "entry_points": [e.path for e in k.entry_points[:5]],
            "test_runner": k.build_commands.test or "pytest",
            "major_components": components_summary,
            "source_dirs": k.source_dirs,
            "test_dirs": k.test_dirs,
        }

    def get_editing_context(self, target_files: List[str]) -> Dict[str, Any]:
        """
        Extract component relationships and dependencies relevant to files being edited.
        """
        k = self.manager.get_project_knowledge()
        related_components = set()

        for f in target_files:
            for cname in k.architecture_map.components:
                if f.startswith(cname):
                    related_components.add(cname)

        component_details = {}
        for cname in related_components:
            comp = k.architecture_map.components.get(cname)
            if comp:
                component_details[cname] = {
                    "category": comp.category,
                    "responsibilities": comp.responsibilities,
                    "internal_deps": comp.internal_deps,
                    "external_deps": comp.external_deps,
                }

        return {
            "target_files": target_files,
            "related_components": component_details,
            "shared_utilities": k.architecture_map.shared_utilities[:5],
        }

    def get_debugging_context(self, error_message: str) -> Dict[str, Any]:
        """
        Extract testing, execution, and build commands for debugging sessions.
        """
        k = self.manager.get_project_knowledge()
        return {
            "test_command": k.build_commands.test,
            "run_command": k.build_commands.run,
            "config_files": k.config_files,
            "test_dirs": k.test_dirs,
            "known_risks": k.known_risks_and_limitations,
        }

    def render_markdown_context(self, max_tokens_estimate: int = 400) -> str:
        """
        Render a concise, high-density markdown context block suitable for prompt injection.
        """
        k = self.manager.get_project_knowledge()
        fw_str = ", ".join(f.name for f in k.frameworks) or "Standard Libraries"
        lang_str = ", ".join(f"{lang} ({info.percentage:.0f}%)" for lang, info in k.languages.items() if info.percentage > 5.0) or "Unknown"

        md = [
            f"### Project Intelligence: {k.project_name}",
            f"- **Type:** `{k.project_type.value.value}` | **Confidence:** `{k.project_type.confidence.value}`",
            f"- **Purpose:** {k.project_purpose.value}",
            f"- **Stack:** {lang_str} | **Frameworks:** {fw_str}",
        ]
        if k.entry_points:
            eps = ", ".join(f"`{e.path}`" for e in k.entry_points[:3])
            md.append(f"- **Entry Points:** {eps}")
        if k.build_commands.test:
            md.append(f"- **Test Command:** `{k.build_commands.test}`")
        if k.architecture_map.components:
            comps = ", ".join(f"`{c}`" for c in list(k.architecture_map.components.keys())[:6])
            md.append(f"- **Core Subsystems:** {comps}")

        return "\n".join(md)

