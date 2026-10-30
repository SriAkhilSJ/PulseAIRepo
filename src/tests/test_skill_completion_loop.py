"""Closing the loop: a completed task returns the books that governed it.

The plan turn injects the stack; the build turn carries the constraints; the
completion returns the books themselves — name, path, provenance and the
verification receipts the plan was supposed to satisfy. These tests pin the
contract and the wiring.
"""

from __future__ import annotations

import pathlib

import pytest

from src.agents.skill_manager import SkillManager

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def manager():
    return SkillManager()


def test_a_completed_product_task_returns_its_books(manager):
    result = manager.complete_task(
        "build a multi-tenant SaaS for field service teams",
        [{"description": "tenant isolation"}, {"description": "billing"}],
    )
    assert result["count"] >= 8
    names = [b["name"] for b in result["books"]]
    assert "backend-development-architect" in names
    for book in result["books"]:
        assert book["path"] and book["tier"] in ("core", "stack", "detail")


def test_returned_books_carry_their_verification_receipts(manager):
    result = manager.complete_task("build a multi-tenant SaaS with billing", [])
    with_receipts = [b for b in result["books"] if b["receipts"]]
    assert with_receipts, "no returned book carried a receipt"
    assert all(len(b["receipts"]) <= 5 for b in result["books"])


def test_an_unrelated_task_returns_nothing(manager):
    assert manager.complete_task("summarize this log file", [])["count"] == 0


def test_completion_records_usage(manager):
    before = manager.get_usage("kafka-architect").get("use_count", 0)
    manager.complete_task("our kafka consumer lag is growing", [])
    assert manager.get_usage("kafka-architect").get("use_count", 0) > before


def test_finalize_returns_the_books_in_state():
    """Wiring guard: finalize_node must put the receipt into the turn's state."""
    source = (REPO_ROOT / "src" / "graphs" / "chat_graph.py").read_text(encoding="utf-8")
    assert '"skills_returned": skills_returned' in source
    assert "complete_task(" in source
