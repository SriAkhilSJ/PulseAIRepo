"""Skill pull tools (Agent Skills / Copilot parity): skill_view + skills_list.

Pins the read path end to end:
  - both tools sit in the always-on waist AND are bound in chat_graph's
    _TOOLS_BY_NAME (a tool the resolver names but the graph cannot call is
    a phantom)
  - skill_view returns the SKILL.md BODY (frontmatter stripped) for bundled
    skills and the stored instruction for user-created skills; errors are
    strings, never raised (hermes tool shape D17)
  - discovery: SkillManager stores a per-skill description, and the
    <available_skills> index carries name + description for BOTH sources —
    bundled from the dir tree, user skills merged in (without the merge a
    user skill is invisible to the model that would pull it)
  - with skill_view bound the index renders the upstream PULL sentence
    ("load it with skill_view(name)"); without it, Crusor's injection
    sentence stays truthful
  - telemetry: skill_view records "view"; eager trigger injection remains
    the separate "use" path
"""

from pathlib import Path

import pytest

from src.agents.skill_manager import SkillManager
from src.prompts.hermes.skills_index import (
    _skills_lead,
    build_skills_system_prompt,
    clear_skills_system_prompt_cache,
)
from src.tools.skill_tools import skill_view, skills_list
from src.tools.toolsets import all_known_tool_names, resolve_toolset_names

_REPO = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _REPO / "skills"


@pytest.fixture
def sm(tmp_path, monkeypatch):
    """A SkillManager on throwaway storage, wired into the tools AND the
    index merge — never the developer's real ~/.crusorai/skills.json."""
    manager = SkillManager(storage_path=str(tmp_path / "skills.json"))
    monkeypatch.setattr("src.tools.skill_tools._manager", lambda: manager)
    monkeypatch.setattr("src.agents.skill_manager.skill_manager", manager)
    clear_skills_system_prompt_cache()
    yield manager
    clear_skills_system_prompt_cache()


def _index(tools, home: Path) -> str:
    return build_skills_system_prompt(
        available_tools=tools,
        skills_dir_override=_SKILLS_DIR,
        home=home,
    )


# ---------------------------------------------------------------------------
# waist + binding
# ---------------------------------------------------------------------------

def test_skill_tools_are_always_in_the_waist():
    resolved = set(resolve_toolset_names("hello, how are you?"))
    assert {"skill_view", "skills_list"} <= resolved
    assert {"skill_view", "skills_list"} <= set(all_known_tool_names())


def test_skill_tools_registered_in_chat_graph():
    from src.graphs.chat_graph import _TOOLS_BY_NAME

    assert "skill_view" in _TOOLS_BY_NAME
    assert "skills_list" in _TOOLS_BY_NAME


# ---------------------------------------------------------------------------
# skill_view: bundled + user + errors
# ---------------------------------------------------------------------------

def test_skill_view_returns_bundled_body_without_frontmatter(sm):
    out = skill_view.invoke({"name": "media-sourcing"})
    lines = out.splitlines()
    assert lines[0] == "# skill: media-sourcing"
    assert "(source: bundled;" in out
    assert "platforms: [linux" not in out  # frontmatter stripped
    assert "**Triggers:**" in out  # body, not metadata-only
    assert "never hotlink" in out  # the actual workflow
    assert sm.get_usage("media-sourcing")["view_count"] == 1
    assert sm.get_usage("media-sourcing")["use_count"] == 0  # pull != eager use


def test_skill_view_reads_user_created_skill(sm):
    sm.add_skill(
        "unit-proof",
        triggers=["zzq-never-matches"],
        instruction="SECRET-XYZ always first.",
        description="Unit proof skill.",
    )
    out = skill_view.invoke({"name": "unit-proof"})
    assert "SECRET-XYZ" in out
    assert "(source: user;" in out
    assert sm.get_usage("unit-proof")["view_count"] == 1


def test_skill_view_is_case_insensitive_and_never_raises(sm):
    assert "# skill: media-sourcing" in skill_view.invoke({"name": "Media-Sourcing"})
    out = skill_view.invoke({"name": "does-not-exist"})
    assert out.startswith("skill_view error:")
    assert "media-sourcing" in out  # available list so the model can recover


# ---------------------------------------------------------------------------
# skills_list
# ---------------------------------------------------------------------------

def test_skills_list_is_the_index_as_a_tool(sm):
    sm.add_skill("listed-user", triggers=["t-one"], instruction="x", description="d")
    out = skills_list.invoke({})
    assert out.startswith("Available skills")
    assert "skill_view(name)" in out
    assert "- media-sourcing (bundled)" in out
    assert "- listed-user (user)" in out


# ---------------------------------------------------------------------------
# discovery index: description + user merge + pull sentence
# ---------------------------------------------------------------------------

def test_bundled_description_stored_for_discovery(sm):
    entry = next(s for s in sm.list_skills() if s["name"] == "media-sourcing")
    assert entry["description"].startswith("Find, download and wire")


def test_index_carries_descriptions_and_merges_user_skills(sm, tmp_path):
    sm.add_skill(
        "index-proof",
        triggers=["t-two"],
        instruction="body",
        description="Proof the user skill reaches discovery.",
    )
    idx = _index({"skill_view", "skills_list", "web_search", "read_file"}, tmp_path)
    assert "- media-sourcing: " in idx  # bundled, with frontmatter description
    assert "- index-proof: Proof the user skill reaches discovery." in idx
    assert "  user:" in idx  # merged under its own category


def test_index_renders_pull_sentence_only_with_skill_view(tmp_path):
    pull = _index({"skill_view", "read_file"}, tmp_path)
    assert "skill_view(name)" in pull
    injected = _index({"read_file", "web_search"}, tmp_path)
    assert "load it with skill_view" not in injected
    assert "injects the body" in injected


def test_lead_sentence_helper_matches_index_behavior():
    assert "skill_view(name)" in _skills_lead({"skill_view"}, "terminal")
    no_tool = _skills_lead({"read_file"}, "terminal")
    assert "skill_view" not in no_tool
    assert "injects the body" in no_tool


# ---------------------------------------------------------------------------
# eager injection still coexists with the pull path
# ---------------------------------------------------------------------------

def test_eager_injection_still_fires_for_matched_tasks(sm):
    text = sm.get_skills_text("change the perfume product, use real product photos")
    assert "**media-sourcing:**" in text
    assert sm.get_usage("media-sourcing")["use_count"] == 1
    # a non-matching task pulls nothing in eagerly — skill_view is the way in
    quiet = sm.get_skills_text("summarize this log file for me")
    assert "**media-sourcing:**" not in quiet
