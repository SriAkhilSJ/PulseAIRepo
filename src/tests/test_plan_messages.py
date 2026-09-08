"""P10 behavior contracts for src/context/plan_messages.py.

The planner / replanner / reviser message builders are pure string
construction — these tests pin the exact briefs they emit (section
ordering, caps on failures/lessons, plan text in the reviser) and pin
the engine's delegation seams (planner.py calls them on the engine).
"""

from langchain_core.messages import HumanMessage, SystemMessage

from src.context import plan_messages
from src.context.context_engine import ContextEngine


def _engine() -> ContextEngine:
    return ContextEngine(max_tokens=4000, llm=None, memory_manager=None)


PROMPT = "You are a planner."
TASK = "add auth to the API"


# ---------------------------------------------------------------------------
# Strict-output wrapper
# ---------------------------------------------------------------------------

def test_wrap_planner_prompt_preserves_original_and_appends_rules():
    out = plan_messages.wrap_planner_prompt(PROMPT)
    assert out.startswith(PROMPT)
    assert "Return ONLY the final plan as a numbered list." in out
    assert "Start every line with a number like `1.`." in out
    assert "usually 3-8 steps." in out


def test_all_builders_use_wrapped_system_prompt():
    plan = [{"id": 1, "description": "step one", "status": "pending"}]
    for msgs in (
        plan_messages.build_planner_messages(TASK, PROMPT),
        plan_messages.build_reviser_messages(TASK, plan, "make it shorter", PROMPT),
    ):
        assert isinstance(msgs[0], SystemMessage)
        assert msgs[0].content == plan_messages.wrap_planner_prompt(PROMPT)
        assert isinstance(msgs[1], HumanMessage)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

def test_build_planner_messages_is_prompt_plus_task():
    msgs = plan_messages.build_planner_messages(TASK, PROMPT)
    assert len(msgs) == 2
    assert msgs[1].content == TASK


# ---------------------------------------------------------------------------
# Replanner
# ---------------------------------------------------------------------------

def test_reviser_includes_full_plan_and_request():
    plan = [
        {"id": 7, "description": "keep me"},
        {"id": 8, "description": "change me"},
    ]
    brief = plan_messages.build_reviser_messages(
        TASK, plan, "make it shorter", PROMPT
    )[1].content
    assert f"Original task:\n{TASK}" in brief
    assert "7. keep me" in brief
    assert "8. change me" in brief
    assert "User requested this plan change:\nmake it shorter" in brief
    assert "Preserve steps that do not need to change." in brief
    assert "Do not execute anything." in brief


def test_reviser_falls_back_to_enumeration_index_without_ids():
    plan = [
        {"description": "one"},
        {"description": "two"},
    ]
    brief = plan_messages.build_reviser_messages(
        TASK, plan, "rev", PROMPT
    )[1].content
    assert "1. one" in brief
    assert "2. two" in brief


# ---------------------------------------------------------------------------
# Engine delegation seams (planner.py calls these on the engine)
# ---------------------------------------------------------------------------

def test_engine_plan_builders_delegate_to_module():
    eng = _engine()
    plan = [{"id": 1, "description": "step", "status": "completed"}]
    failed = ["boom"]

    assert eng.build_planner_messages(TASK, PROMPT) == \
        plan_messages.build_planner_messages(TASK, PROMPT)
    assert eng.build_reviser_messages(TASK, plan, "rev", PROMPT) == \
        plan_messages.build_reviser_messages(TASK, plan, "rev", PROMPT)
    assert ContextEngine._planner_prompt(PROMPT) == \
        plan_messages.wrap_planner_prompt(PROMPT)
