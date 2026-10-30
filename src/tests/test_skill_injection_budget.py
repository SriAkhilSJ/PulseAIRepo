"""The zero-call path: planning injection must be ranked, budgeted and correct.

Injecting *every* trigger match was neither fast (18k chars for one useful book)
nor accurate (a matched crown shadowing its own child). These tests pin the
behaviour that replaced it: strongest first, inside `_INJECT_CHARS`, with an
explicit note when something was left out.
"""

from __future__ import annotations

from tempfile import NamedTemporaryFile

import pytest

from src.agents import skill_manager as sm_mod
from src.agents.skill_manager import SkillManager


@pytest.fixture(scope="module")
def manager():
    return SkillManager(storage_path=NamedTemporaryFile(suffix=".json").name)


def test_injection_stays_inside_the_budget(manager, monkeypatch):
    monkeypatch.setattr(sm_mod, "_INJECT_CHARS", 6000)
    text = manager.get_skills_text("kafka consumer lag is growing", phase="planning")
    assert 0 < len(text) < 9000  # one book plus the header and the hint
    assert "more book(s) matched" in text or len(text) < 6000


def test_overflow_is_announced_not_hidden(manager, monkeypatch):
    monkeypatch.setattr(sm_mod, "_INJECT_CHARS", 3500)
    text = manager.get_skills_text("kafka consumer lag is growing", phase="planning")
    assert "left out of the budget" in text
    assert "skill_view" in text


def test_ranking_puts_the_strongest_book_first(manager):
    ranked = manager.ranked_for_task("terraform state file is corrupted", phase="planning")
    assert ranked, "expected matches"
    assert ranked[0][1]["name"] == "terraform-architect"


def test_crown_is_dropped_when_its_child_matched(manager):
    ranked = [s["name"] for _score, s in
              manager.ranked_for_task("desktop app packaging for windows", phase="planning")]
    assert "desktop-architect" not in ranked or "desktop-distribution-architect" not in ranked


def test_execution_phase_injects_nothing(manager):
    assert manager.get_skills_text("kafka consumer lag", phase="executing") == ""


def test_unrelated_task_injects_nothing(manager):
    assert manager.get_skills_text("summarize this log file for me", phase="planning") == ""


@pytest.mark.parametrize("task,expected", [
    ("kafka consumer lag is growing", "kafka-architect"),
    ("terraform state file is corrupted", "terraform-architect"),
    ("design a rest api for partners", "rest-architect"),
    ("postgres query is slow on a big table", "postgres-architect"),
    ("airflow dag is stuck in backfill", "airflow-architect"),
    ("windows installer requires admin rights", "desktop-distribution-architect"),
    ("mac app should feel native", "native-feel-architect"),
    ("app must work offline in the field", "mobile-offline-sync-architect"),
    ("vector search returns irrelevant chunks", "vector-store-architect"),
    ("prompt injection through support tickets", "prompting-architect"),
    ("kubernetes pods evicted on memory pressure", "kubernetes-architect"),
    ("snowflake costs doubled", "snowflake-architect"),
    ("our screen reader can't read the desktop app", "desktop-accessibility-architect"),
])
def test_zero_call_routing_finds_the_right_book(manager, task, expected):
    """No tool call at all: the book is already in the injected planning text."""
    text = manager.get_skills_text(task, phase="planning")
    assert expected in text, f"{expected} was not injected for {task!r}"
