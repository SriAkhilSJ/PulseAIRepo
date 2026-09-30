"""Bundled SKILL.md loading: frontmatter parsing, trigger derivation, injection.

Pins the hermes-parity bundled loader (`SkillManager._load_bundled_skills`):
  - every skills/<name>/SKILL.md loads as a pinned bundled skill
  - triggers come from the **Triggers:** line, then frontmatter
    keywords/triggers (never tags — taxonomy, too loose as substrings),
    then the folder name
  - a wildcard "*" trigger (the legacy `**Triggers:**` split bug) can never
    leak in — it would match every task
  - the injected instruction is the skill BODY (frontmatter stripped) and is
    capped at _BUNDLED_INSTRUCTION_CAP (6000) chars
"""

import json

import pytest

from src.agents.skill_manager import (
    _BUNDLED_INSTRUCTION_CAP,
    SkillManager,
    _frontmatter_triggers,
    _parse_skill_frontmatter,
)

SKILLS_DOC = """---
name: my-skill
description: "Do the thing, under sixty chars."
version: 0.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [tag-one, tag-two]
    related_skills: [other-skill]
keywords: [alpha, beta gamma]
---

**Triggers:** trig-one, trig two

# My Skill

Body content here.
"""


def _bundled(sm: SkillManager) -> dict:
    return {s["name"]: s for s in sm.list_skills() if s.get("created_by") == "bundled"}


# ---------------------------------------------------------------------------
# frontmatter parser
# ---------------------------------------------------------------------------

def test_frontmatter_split_and_fields():
    fm, body = _parse_skill_frontmatter(SKILLS_DOC)
    assert fm["name"] == "my-skill"
    assert fm["description"] == "Do the thing, under sixty chars."
    assert fm["keywords"] == ["alpha", "beta gamma"]
    assert fm["metadata"]["hermes"]["tags"] == ["tag-one", "tag-two"]
    assert fm["metadata"]["hermes"]["related_skills"] == ["other-skill"]
    assert body.startswith("**Triggers:**")
    assert "name: my-skill" not in body
    assert body.rstrip().endswith("Body content here.")


def test_frontmatter_nested_mapping_after_seeded_list():
    # `metadata:` is seeded as a block list; a nested `hermes:` mapping must
    # convert it — this used to raise TypeError and abort the whole load.
    text = "---\nmetadata:\n  hermes:\n    tags: [a, b]\n---\nBody."
    fm, body = _parse_skill_frontmatter(text)
    assert fm["metadata"]["hermes"]["tags"] == ["a", "b"]
    assert body == "Body."


def test_frontmatter_absent_returns_body_verbatim():
    fm, body = _parse_skill_frontmatter("# No frontmatter\n\ntext")
    assert fm == {}
    assert body.startswith("# No frontmatter")


def test_frontmatter_unclosed_treated_as_absent():
    fm, body = _parse_skill_frontmatter("---\nname: x\nno close ever")
    assert fm == {}


def test_frontmatter_triggers_use_keywords_not_tags():
    fm, _ = _parse_skill_frontmatter(SKILLS_DOC)
    triggers = _frontmatter_triggers(fm)
    assert "alpha" in triggers and "gamma" in triggers  # from keywords
    assert "tag-one" not in triggers  # tags are taxonomy, not triggers


# ---------------------------------------------------------------------------
# bundled load + trigger derivation on the real repo skills/
# ---------------------------------------------------------------------------

def test_all_repo_skills_load_as_bundled():
    sm = SkillManager(storage_path=_tmpfile())
    bundled = _bundled(sm)
    # 5 connectors + 10 hermes-ported coding-workflow skills + 4 docs/thinking
    assert len(bundled) >= 19
    for name, skill in bundled.items():
        assert skill["pinned"] is True, name
        assert skill["state"] == "active", name
        assert skill["enabled"] is True, name
        assert skill["triggers"], f"no triggers: {name}"
        assert "*" not in skill["triggers"], f"wildcard trigger leaked: {name}"
        assert len(skill["instruction"]) <= _BUNDLED_INSTRUCTION_CAP
        # body, not frontmatter
        assert not skill["instruction"].startswith("---\n"), name


def test_expected_skill_names_present():
    sm = SkillManager(storage_path=_tmpfile())
    bundled = set(_bundled(sm))
    expected = {
        "mcp", "github-connector", "browser-connector", "db-connector",
        "terminal-connector", "codebase-inspection", "test-driven-development",
        "systematic-debugging", "requesting-code-review", "simplify-code",
        "subagent-driven-development", "spike", "node-inspect-debugger",
        "python-debugpy", "ast-grep", "rest-graphql-debug", "code-wiki",
        "grill-me", "skill-authoring",
    }
    missing = expected - bundled
    assert not missing, f"bundled skills missing: {sorted(missing)}"


def test_triggers_line_wins_over_frontmatter(tmp_path):
    d = tmp_path / "trig-skill"
    d.mkdir()
    (d / "SKILL.md").write_text(SKILLS_DOC, encoding="utf-8")
    sm = _load_from(tmp_path)
    skill = _bundled(sm)["trig-skill"]
    assert "trig-one" in skill["triggers"]
    assert "trig two" in skill["triggers"]
    assert "alpha" not in skill["triggers"]  # keywords ignored: line wins


def test_frontmatter_keywords_used_when_no_triggers_line(tmp_path):
    d = tmp_path / "kw-skill"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: kw-skill\nkeywords: [kw-one]\n---\nBody.", encoding="utf-8"
    )
    sm = _load_from(tmp_path)
    assert "kw-one" in _bundled(sm)["kw-skill"]["triggers"]


def test_folder_name_fallback(tmp_path):
    d = tmp_path / "no-triggers-at-all"
    d.mkdir()
    (d / "SKILL.md").write_text("# nothing\n", encoding="utf-8")
    sm = _load_from(tmp_path)
    assert _bundled(sm)["no-triggers-at-all"]["triggers"] == ["no-triggers-at-all"]


def test_instruction_cap_enforced(tmp_path):
    d = tmp_path / "big-skill"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: big\n---\n" + ("x" * 9000), encoding="utf-8")
    sm = _load_from(tmp_path)
    assert len(_bundled(sm)["big-skill"]["instruction"]) == _BUNDLED_INSTRUCTION_CAP


# ---------------------------------------------------------------------------
# natural-language trigger matching (the injection contract)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "task,expected",
    [
        ("fix this crashing bug in auth.py", ["systematic-debugging"]),
        ("why is this test failing? traceback says NoneType", ["systematic-debugging"]),
        ("write unit tests for the parser", ["test-driven-development"]),
        ("prototype whether websockets can stream tokens", ["spike"]),
        ("is this even possible? quick check", ["spike"]),
        ("generate a wiki for this codebase", ["code-wiki"]),
        ("grill me on my migration plan", ["grill-me"]),
        ("my rest api returns 401", ["rest-graphql-debug"]),
        ("create a skill for linting", ["skill-authoring"]),
        ("spawn subagents to analyze these folders", ["subagent-driven-development"]),
        ("debug the node dev server", ["node-inspect-debugger", "systematic-debugging"]),
        ("rewrite every console.log call to logger", ["ast-grep"]),
        ("connect to postgres and list tables", ["db-connector", "mcp"]),
    ],
)
def test_natural_language_tasks_fire_expected_skills(task, expected):
    sm = SkillManager(storage_path=_tmpfile())
    bundled = _bundled(sm)
    hits = sorted(
        name for name, s in bundled.items()
        if any(t in task.lower() for t in s["triggers"])
    )
    for name in expected:
        assert name in hits, f"{task!r} did not fire {name} (fired: {hits})"
    # and never more than a handful — a wild trigger set floods the context
    assert len(hits) <= 4, f"{task!r} fired too many skills: {hits}"


def test_get_relevant_skills_injects_body_without_frontmatter():
    sm = SkillManager(storage_path=_tmpfile())
    text = sm.get_skills_text("grill me on my migration plan")
    assert "grill-me" in text
    assert "name: grill-me" not in text  # no YAML in the prompt
    assert "Frontier Rounds" in text


def _tmpfile() -> str:
    import os, tempfile
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps([]))
    return path


def _load_from(skills_dir) -> SkillManager:
    """SkillManager whose bundled loader points at an alternate skills dir."""
    sm = SkillManager(storage_path=_tmpfile())
    sm._load_bundled_skills(skills_dir=str(skills_dir))
    return sm
