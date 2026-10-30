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


def test_injection_stays_inside_the_budget(manager):
    text = manager.get_skills_text(
        "build a multi-tenant SaaS with billing", phase="planning")
    assert 0 < len(text) <= manager._PLAN_KIT_CHARS + 4000


def test_overflow_is_announced_not_hidden(manager, monkeypatch):
    monkeypatch.setattr(manager, "_PLAN_KIT_CHARS", 6000)
    text = manager.get_skills_text("build a multi-tenant SaaS with billing", phase="planning")
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


# -- Plan Mode: the plan is built from many books, not one ------------------

def test_plan_kit_covers_the_stack_for_a_product_task(manager):
    """"Build a SaaS" must yield a stack, not three books."""
    kit = manager.plan_kit(
        "build a multi-tenant SaaS for field service teams with billing and offline mobile"
    )
    names = [e["name"] for tier in ("core", "stack", "detail") for e in kit[tier]]
    assert len(names) >= 8, names
    for required in ("backend-development-architect", "api-development-architect",
                     "database-engineering-architect", "security-architect"):
        assert required in names, f"{required} missing from the SaaS plan kit"


def test_plan_kit_spans_more_than_one_domain(manager):
    kit = manager.plan_kit("build a SaaS product with a mobile app and a data warehouse")
    domains = {e["path"].split("/")[0]
               for tier in ("core", "stack", "detail") for e in kit[tier]}
    assert len(domains) >= 3, domains


def test_narrow_tasks_do_not_get_a_kit(manager):
    kit = manager.plan_kit("add retry to the bridge")
    count = sum(len(kit[t]) for t in ("core", "stack", "detail"))
    assert count <= 3, f"a narrow task pulled {count} books"


def test_plan_mode_text_is_labelled_and_bounded(manager):
    text = manager.get_skills_text(
        "build a multi-tenant SaaS for field service teams with billing", phase="planning"
    )
    assert "Plan Mode" in text
    assert "CORE" in text and "STACK" in text
    assert len(text) <= manager._PLAN_KIT_CHARS + 4000


def test_plan_mode_is_detected_from_the_repo_state_flag():
    """The gate reads `execution_mode == "plan"` — the flag the UI actually sets."""
    from src.context.context_engine import _skills_phase

    assert _skills_phase({"execution_mode": "plan"}) == "planning"
    assert _skills_phase({"mode": "plan"}) == "planning"
    assert _skills_phase({"plan_mode": True}) == "planning"
    assert _skills_phase({"execution_mode": "agent"}) == "executing"
    assert _skills_phase({}) == "executing"
