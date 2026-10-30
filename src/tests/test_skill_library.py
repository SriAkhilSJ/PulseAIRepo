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
