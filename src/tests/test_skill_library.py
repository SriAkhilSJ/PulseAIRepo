"""The skills library: browse the shelves, open a book, read it, go.

The Architect library is nested (domain -> branch -> technology -> skill), so a
skill is no longer addressable as ``skills/<name>/SKILL.md``. These tests pin
the library contract:

  - loading records where a skill sits (``path`` / ``shelf``)
  - ``skills_list`` browses shelves instead of dumping every skill flat
  - ``skill_view`` opens the real file at whatever depth it lives, and returns
    the whole body (never the capped stored instruction)
  - path resolution never escapes the library root
"""

from pathlib import Path

import pytest

from src.agents.skill_manager import SkillManager
from src.tools import skill_tools

BODY = "# Deep Book\n\nOpening rule.\n\n" + ("middle line\n" * 400) + "\nLAST LINE MARKER\n"


def _make_library(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    book = root / "website-architect" / "frontend-architect" / "react-architect" / "nextjs-architect"
    book.mkdir(parents=True)
    (book / "SKILL.md").write_text(
        "---\nname: nextjs-architect\ndescription: Next.js architecture.\n"
        "metadata:\n  crusor-triggers: \"nextjs, rsc\"\n---\n\n" + BODY,
        encoding="utf-8",
    )
    top = root / "website-architect"
    (top / "SKILL.md").write_text(
        "---\nname: website-architect\ndescription: Domain entry.\n---\n\nDomain body.\n",
        encoding="utf-8",
    )
    return root


def _manager(tmp_path: Path, root: Path) -> SkillManager:
    sm = SkillManager(storage_path=str(tmp_path / "store.json"))
    sm._skills = [s for s in sm._skills if s.get("created_by") != "bundled"]
    sm._load_bundled_skills(str(root))
    return sm


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = _make_library(tmp_path)
    sm = _manager(tmp_path, root)
    monkeypatch.setattr(skill_tools, "_manager", lambda: sm)
    monkeypatch.setattr(skill_tools, "_skills_dir", lambda: root)
    return sm


def test_loading_records_the_shelf_a_skill_sits_on(library):
    by_name = {s["name"]: s for s in library.list_skills() if s.get("created_by") == "bundled"}
    assert by_name["nextjs-architect"]["path"] == (
        "website-architect/frontend-architect/react-architect/nextjs-architect"
    )
    assert by_name["nextjs-architect"]["shelf"] == (
        "website-architect/frontend-architect/react-architect"
    )
    assert by_name["website-architect"]["shelf"] == ""


def test_skills_list_browses_shelves_instead_of_dumping_everything(library):
    root_listing = skill_tools.skills_list.invoke({})
    assert "website-architect/" in root_listing

    shelf = skill_tools.skills_list.invoke({"shelf": "website-architect"})
    assert "frontend-architect/" in shelf
    assert "nextjs-architect" not in shelf  # one level down, not a direct book

    deep = skill_tools.skills_list.invoke(
        {"shelf": "website-architect/frontend-architect/react-architect"}
    )
    assert "nextjs-architect" in deep


def test_skill_view_opens_the_nested_file_and_returns_the_whole_body(library):
    out = skill_tools.skill_view.invoke({"name": "nextjs-architect"})
    assert "LAST LINE MARKER" in out  # only the file has this, past the cap
    assert library.get_usage("nextjs-architect")["view_count"] == 1


def test_skill_file_refuses_to_escape_the_library(library):
    assert skill_tools._skill_file({"path": "../../etc"}) is None
    assert skill_tools._skill_file({"path": "missing/skill"}) is None


# ---------------------------------------------------------------------------
# the planning rule: architect skills are planning instruments
# ---------------------------------------------------------------------------

def _write_skill(root: Path, rel: str, name: str, body: str = "Body.", meta: str = "") -> None:
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name}.\n{meta}---\n\n{body}\n",
        encoding="utf-8",
    )


def test_architect_skills_are_planning_phase_by_default(tmp_path):
    root = tmp_path / "skills"
    _write_skill(root, "dom/react-architect", "react-architect")
    _write_skill(root, "dom/react-architect/nextjs-architect", "nextjs-architect")
    _write_skill(root, "dom/deploy", "deploy")
    _write_skill(root, "dom/lint", "lint", meta="metadata:\n  crusor-phase: planning\n")

    sm = _manager(tmp_path, root)
    by_name = {s["name"]: s for s in sm.list_skills()}
    assert by_name["nextjs-architect"]["phase"] == "planning"
    assert by_name["react-architect"]["phase"] == "planning"
    assert by_name["deploy"]["phase"] == "always"
    assert by_name["lint"]["phase"] == "planning"  # explicit metadata wins


def test_architect_skills_are_not_injected_while_executing(tmp_path):
    root = tmp_path / "skills"
    _write_skill(
        root, "dom/nextjs-architect", "nextjs-architect",
        meta='metadata:\n  crusor-triggers: "nextjs, app router"\n',
    )
    sm = _manager(tmp_path, root)

    task = "nextjs app router refactor"
    # Executing: an architect skill never arrives by trigger match.
    assert sm.get_relevant_skills(task, phase="executing") == []
    # Planning: it is exactly the moment it belongs to.
    assert sm.get_relevant_skills(task, phase="planning")
    # …and it is still reachable on demand, which is how the library works.
    assert sm.get_usage("nextjs-architect")["use_count"] == 1


def test_skill_view_marks_a_planning_skill(library):
    out = skill_tools.skill_view.invoke({"name": "nextjs-architect"})
    assert "PLANNING SKILL" in out


def test_a_stale_persisted_copy_is_refreshed_from_disk(tmp_path):
    import json

    root = tmp_path / "skills"
    _write_skill(root, "dom/nextjs-architect", "nextjs-architect", body="FRESH BODY")
    store = tmp_path / "store.json"
    store.write_text(json.dumps([{
        "name": "nextjs-architect", "created_by": "bundled", "instruction": "STALE BODY",
        "triggers": ["nextjs"], "enabled": True, "state": "active", "pinned": True,
        "use_count": 7, "view_count": 2,
    }]), encoding="utf-8")

    sm = SkillManager(storage_path=str(store))
    sm._load_bundled_skills(str(root))
    entry = next(s for s in sm.list_skills() if s["name"] == "nextjs-architect")
    assert "FRESH BODY" in entry["instruction"]
    assert entry["phase"] == "planning"          # new field lands
    assert entry["path"] == "dom/nextjs-architect"  # shelf recorded
    assert entry["use_count"] == 7               # telemetry survives
    assert len([s for s in sm.list_skills() if s["name"] == "nextjs-architect"]) == 1


def test_a_user_skill_is_never_shadowed_by_a_shipped_one(tmp_path):
    import json

    root = tmp_path / "skills"
    _write_skill(root, "dom/deploy", "deploy", body="SHIPPED")
    store = tmp_path / "store.json"
    store.write_text(json.dumps([{
        "name": "deploy", "created_by": "user", "instruction": "MINE",
        "triggers": ["deploy"], "enabled": True, "state": "active",
    }]), encoding="utf-8")
    sm = SkillManager(storage_path=str(store))
    sm._load_bundled_skills(str(root))
    entry = next(s for s in sm.list_skills() if s["name"] == "deploy")
    assert entry["instruction"] == "MINE"
