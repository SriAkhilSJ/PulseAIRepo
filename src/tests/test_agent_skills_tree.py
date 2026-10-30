"""Bundled-skill discovery is recursive and taxonomy-aware.

The Architect library nests domain -> branch -> technology -> skill
(`skills/website-architect/frontend-development/react/nextjs/SKILL.md`).
Discovery must find every leaf at any depth, must ignore containers that carry
no `SKILL.md`, and must keep the flat legacy layout working unchanged.
"""
from __future__ import annotations

import textwrap

from src.agents.skill_manager import SkillManager


def _write(path, name: str, description: str, *, triggers: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = f"keywords: [{triggers}]\n" if triggers else ""
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: {description}
            {extra}metadata:
              crusor-domain: website-architect
              crusor-origin: original
            ---

            # {name}

            Body for {name}.
            """
        ),
        encoding="utf-8",
    )


def _manager(tmp_path) -> SkillManager:
    return SkillManager(storage_path=str(tmp_path / "skills.json"))


def test_nested_skill_is_discovered_at_any_depth(tmp_path):
    root = tmp_path / "skills"
    _write(
        root / "website-architect" / "frontend-development" / "react" / "demo-nextjs" / "SKILL.md",
        "demo-nextjs",
        "Architect-level Next.js guidance.",
        triggers="nextjs, app router",
    )
    # A container with no SKILL.md must not become a skill.
    (root / "website-architect" / "backend-development").mkdir(parents=True)

    mgr = _manager(tmp_path)
    mgr._load_bundled_skills(str(root))

    by_name = {s["name"]: s for s in mgr._skills}
    assert "demo-nextjs" in by_name
    assert "website-architect" not in by_name
    assert "frontend-development" not in by_name
    skill = by_name["demo-nextjs"]
    assert skill["description"] == "Architect-level Next.js guidance."
    assert "nextjs" in skill["triggers"]
    assert skill["created_by"] == "bundled"
    assert skill["pinned"] is True
    assert "Body for demo-nextjs." in skill["instruction"]
    # Frontmatter never leaks into the injected instruction.
    assert "crusor-domain" not in skill["instruction"]


def test_flat_legacy_skills_still_load(tmp_path):
    root = tmp_path / "skills"
    _write(root / "systematic-debugging" / "SKILL.md", "systematic-debugging", "Debug workflow.")
    _write(
        root / "website-architect" / "frontend-development" / "react" / "react-core-architect" / "SKILL.md",
        "react-core-architect",
        "React application structure.",
    )

    mgr = _manager(tmp_path)
    mgr._load_bundled_skills(str(root))

    names = {s["name"] for s in mgr._skills}
    assert {"systematic-debugging", "react-core-architect"} <= names


def test_root_index_skill_md_is_not_a_skill(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    (root / "SKILL.md").write_text("# Skills index\n", encoding="utf-8")
    _write(root / "demo-nextjs" / "SKILL.md", "demo-nextjs", "Demo Next.js.")

    mgr = _manager(tmp_path)
    mgr._load_bundled_skills(str(root))

    names = {s["name"] for s in mgr._skills}
    assert "demo-nextjs" in names
    # The tree root's index file is a container, never a skill named after it.
    assert "skills" not in names


def test_duplicate_skill_names_are_not_loaded_twice(tmp_path):
    root = tmp_path / "skills"
    _write(root / "a" / "shared-name" / "SKILL.md", "shared-name", "First.")
    _write(root / "b" / "shared-name" / "SKILL.md", "shared-name", "Second.")

    mgr = _manager(tmp_path)
    mgr._load_bundled_skills(str(root))

    matches = [s for s in mgr._skills if s["name"] == "shared-name"]
    assert len(matches) == 1


def test_repo_architect_library_is_discoverable(tmp_path):
    """The shipped Website Architect pilot must load from the repo tree."""
    manager = _manager(tmp_path)
    names = {s["name"] for s in manager._skills}

    assert {
        "frontend-development-architect",
        "html-css-architect",
        "javascript-architect",
        "typescript-architect",
        "react-architect",
        "react-core-architect",
        "nextjs-architect",
        "react-router-architect",
        "react-state-management-architect",
        "react-ui-libraries-architect",
        "react-testing-architect",
        "vue-architect",
        "angular-architect",
        "svelte-architect",
        "astro-architect",
        "nodejs-architect",
        "threejs-architect",
    } <= names
    # Existing flat process skills must survive the recursive discovery change.
    assert "systematic-debugging" in names


def test_architect_leaves_conform_to_the_agent_skills_spec():
    """Every shipped Architect skill: name==dir, spec-safe slug, bounded body."""
    import re
    from pathlib import Path

    from src.agents.skill_manager import (
        _BUNDLED_INSTRUCTION_CAP,
        _parse_skill_frontmatter,
    )

    slug = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    leaves = list(Path("skills/website-architect").rglob("SKILL.md"))
    assert leaves, "Website Architect tree is missing"

    for path in leaves:
        frontmatter, body = _parse_skill_frontmatter(path.read_text(encoding="utf-8"))
        name = str(frontmatter.get("name", ""))
        description = str(frontmatter.get("description", ""))
        assert name == path.parent.name, f"{path}: name must equal directory"
        assert slug.match(name), f"{path}: invalid skill slug {name!r}"
        assert 0 < len(description) <= 1024, f"{path}: description length"
        assert len(body) <= _BUNDLED_INSTRUCTION_CAP, (
            f"{path}: body {len(body)} exceeds injection cap "
            f"{_BUNDLED_INSTRUCTION_CAP} and would be silently truncated"
        )
        # Provenance is mandatory in this library.
        assert frontmatter.get("metadata", {}).get("crusor-origin"), path
