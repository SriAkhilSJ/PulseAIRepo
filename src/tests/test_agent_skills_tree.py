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
        "python-architect",
        "flask-architect",
        "fastapi-architect",
        "django-architect",
        "tailwind-architect",
        "vite-architect",
        "playwright-architect",
        "tanstack-query-architect",
        "redux-toolkit-architect",
        "express-architect",
        "nestjs-architect",
        "fastify-architect",
        "accessibility-architect",
        "web-performance-architect",
        "i18n-architect",
        "forms-architect",
        "motion-architect",
        "seo-architect",
        "pwa-architect",
        "vitest-architect",
        "database-engineering-architect",
        "postgres-architect",
        "mongodb-architect",
        "redis-architect",
        "prisma-architect",
        "drizzle-architect",
        "api-development-architect",
        "rest-architect",
        "graphql-architect",
        "trpc-architect",
        "grpc-architect",
        "api-auth-architect",
        "rate-limiting-architect",
        "security-architect",
        "owasp-top10-architect",
        "authz-models-architect",
        "secrets-management-architect",
        "supply-chain-architect",
        "browser-security-architect",
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


def test_skill_names_unique_and_crusor_path_matches_location():
    """A tree is only navigable if names are unique and paths tell the truth."""
    from pathlib import Path

    from src.agents.skill_manager import _parse_skill_frontmatter

    root = Path("skills")
    tree = root / "website-architect"

    # Names used elsewhere in the repository, so the tree cannot shadow them.
    taken = {}
    for path in root.rglob("SKILL.md"):
        if tree in path.parents:
            continue
        fm, _ = _parse_skill_frontmatter(path.read_text(encoding="utf-8"))
        if fm.get("name"):
            taken[str(fm["name"])] = path

    seen = {}
    for path in sorted(tree.rglob("SKILL.md")):
        fm, _ = _parse_skill_frontmatter(path.read_text(encoding="utf-8"))
        name = str(fm["name"])
        assert name not in seen, f"{name} declared in both {seen[name]} and {path}"
        assert name not in taken, f"{name} collides with {taken[name]}"
        seen[name] = path

        expected = path.parent.relative_to(tree).as_posix()
        declared = fm.get("metadata", {}).get("crusor-path")
        assert declared == expected, f"{path}: crusor-path {declared!r} != {expected!r}"


# Capability -> skill. This is the definition of "the frontend branch is
# complete": every capability a website frontend needs has a book on the shelf.
FRONTEND_CAPABILITIES = {
    "markup and cascade": "html-css-architect",
    "language runtime": "javascript-architect",
    "type contracts": "typescript-architect",
    "styling system": "tailwind-architect",
    "build and bundling": "vite-architect",
    "motion": "motion-architect",
    "offline and install": "pwa-architect",
    "accessibility": "accessibility-architect",
    "performance": "web-performance-architect",
    "indexability": "seo-architect",
    "internationalisation": "i18n-architect",
    "forms": "forms-architect",
    "unit and component tests": "vitest-architect",
    "end-to-end tests": "playwright-architect",
    "react": "react-architect",
    "vue": "vue-architect",
    "angular": "angular-architect",
    "svelte": "svelte-architect",
    "astro": "astro-architect",
    "node runtime": "nodejs-architect",
    "3d": "threejs-architect",
}


def test_frontend_branch_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {cap: skill for cap, skill in FRONTEND_CAPABILITIES.items() if skill not in available}
    assert not missing, f"frontend capabilities without a skill: {missing}"
    assert len(FRONTEND_CAPABILITIES) >= 20


DATABASE_CAPABILITIES = {
    "relational core": "postgres-architect",
    "document store": "mongodb-architect",
    "cache and ephemeral state": "redis-architect",
    "typescript schema and migrations": "prisma-architect",
    "sql-first typed queries": "drizzle-architect",
    "engine-agnostic data direction": "database-engineering-architect",
}


def test_database_branch_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in DATABASE_CAPABILITIES.items() if s not in available}
    assert not missing, f"data-layer capabilities without a skill: {missing}"


API_CAPABILITIES = {
    "contract and versioning direction": "api-development-architect",
    "resource-oriented http": "rest-architect",
    "client-driven graph": "graphql-architect",
    "typescript-only rpc": "trpc-architect",
    "service-to-service streaming": "grpc-architect",
    "identity and authorization": "api-auth-architect",
    "quotas and abuse": "rate-limiting-architect",
}


def test_api_branch_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in API_CAPABILITIES.items() if s not in available}
    assert not missing, f"API capabilities without a skill: {missing}"


SECURITY_CAPABILITIES = {
    "threat modelling and boundaries": "security-architect",
    "vulnerability classes": "owasp-top10-architect",
    "permission modelling and enforcement": "authz-models-architect",
    "credential custody and rotation": "secrets-management-architect",
    "dependency and pipeline integrity": "supply-chain-architect",
    "browser boundaries and headers": "browser-security-architect",
}


def test_security_branch_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in SECURITY_CAPABILITIES.items() if s not in available}
    assert not missing, f"security capabilities without a skill: {missing}"
