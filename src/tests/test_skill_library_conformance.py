"""Conformance + retrieval gate for the Architect skill library.

Runs `scripts/audit_skills.py` in strict mode, then proves every book is reachable:
a query built from a book's own triggers must select that book during planning.
This is the test that would have caught the drift the ad-hoc audit missed.
"""

from __future__ import annotations

import importlib.util
import pathlib
from tempfile import NamedTemporaryFile

import pytest

from src.agents.skill_manager import SkillManager

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load_auditor():
    spec = importlib.util.spec_from_file_location(
        "audit_skills", REPO_ROOT / "scripts" / "audit_skills.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report():
    auditor = _load_auditor()
    _, rep = auditor.audit()
    return rep


def test_every_book_is_conformant(report):
    violations = [b for b in report["books"] if b["violations"]]
    detail = "\n".join(
        f"{b['name']}: " + "; ".join(b["violations"]) for b in violations
    )
    assert report["books"], "no architect books discovered"
    assert not violations, f"{len(violations)} non-conformant books:\n{detail}"


def test_library_size_is_expected(report):
    # Guards against a silent delete: the pass target is >= 220 books across 6 domains.
    assert len(report["books"]) >= 220
    assert len({b["domain"] for b in report["books"]}) == 6


def test_adapted_books_are_pinned_and_licensed():
    auditor = _load_auditor()
    books = [auditor.parse(p) for p in sorted(auditor.ROOT.rglob("SKILL.md"))]
    adapted = [b for b in books if b.get("origin") == "adapted"]
    assert adapted, "expected at least one adapted book with provenance"
    for b in adapted:
        assert "@" in b["sources"], f"{b['name']} is adapted but has no pinned source"
        assert b["license"] in ("MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause"), b["name"]
    notices = (REPO_ROOT / "skills" / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    for b in adapted:
        repo = b["sources"].split("@")[0].split("/")[-2:] # owner/repo
        assert "/".join(repo) in notices, f"{b['name']}: upstream missing from THIRD-PARTY-NOTICES"


@pytest.mark.parametrize("phase", ["executing"])
def test_no_architect_skill_injected_during_execution(phase):
    manager = SkillManager(storage_path=NamedTemporaryFile(suffix=".json").name)
    assert manager.get_relevant_skills("set up our aws accounts", phase=phase) == []


def test_every_book_retrieves_itself():
    manager = SkillManager(storage_path=NamedTemporaryFile(suffix=".json").name)
    books = [s for s in manager.list_skills() if s["name"].endswith("-architect")]
    misses = []
    for book in books:
        query = " ".join(book["triggers"][:4])
        selected = {
            hit.split(":**")[0].strip("* ")
            for hit in manager.get_relevant_skills(query, phase="planning")
        }
        if book["name"] not in selected:
            misses.append((book["name"], query))
    assert not misses, f"{len(misses)} books unreachable by their own triggers: {misses[:10]}"
