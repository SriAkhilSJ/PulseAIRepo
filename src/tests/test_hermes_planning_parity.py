"""Planning must be model reasoning inside the loop, not a toll before it.

Upstream (NousResearch/hermes-agent @ 0cbc6e3) is unambiguous: ``tools/todo_tool.py:316`` is one function
the model calls when the task earns a list, ``:15`` says behavioural guidance lives entirely in the tool
schema description, and ``agent/plan_prompt.py`` makes PLAN MODE a prompt fed as a normal turn -- "There is
no engine and no model-tool footprint". Pulse had the inverse: a classifier call, a generation call and a
validation call before the agent could act, so ``hi`` and ``create a hello.py`` cost money and latency to
produce a plan nobody needed.

These run the real graph nodes with the planner factory sabotaged, so a pre-action planner call is a test
failure rather than a rumour.
"""
from __future__ import annotations

import json

import pytest


def test_plan_update_tool_reads_and_replaces_like_hermes_todo():
    from src.tools.plan_tool import plan_update

    replace = plan_update.func(
        steps=[
            {"description": "write hello.py", "status": "pending"},
            "run it once",  # bare text is a legitimate step; it must not raise
        ]
    )
    payload = json.loads(replace)
    assert payload["summary"]["total"] == 2
    # exactly one step is "the one you are doing now"
    assert payload["summary"]["in_progress"] == 1
    assert payload["steps"][0]["status"] == "in_progress"
    assert payload["steps"][0]["id"] == 1
    assert payload["steps"][1]["description"] == "run it once"

    read = json.loads(plan_update.func())
    assert read["summary"]["total"] == 0


def test_the_tool_description_carries_the_guidance():
    """Hermes keeps the *when to use it* rules in the schema, not in an extra prompt layer."""

    from src.tools.plan_tool import plan_update

    doc = plan_update.description.lower()
    assert "do not call" in doc or "not call this" in doc, "the schema must tell the model when to abstain"
    for word in ("greeting", "money", "latency"):
        assert word in doc, f"guidance should name the cost of a decorative list: {word}"


def _planner_source():
    from pathlib import Path

    return (Path(__file__).resolve().parents[2] / "src/graphs/chat_graph.py").read_text(encoding="utf-8")


def test_no_mode_but_plan_pays_for_the_pre_action_chain():
    source = _planner_source()
    guard = 'if state.get("execution_mode", "agent") != "plan":\n        return _no_plan()'
    assert guard in source, "the pre-action chain must be gated on explicit plan mode"
    assert "build_plan_prompt(current_task)" in source, "plan mode must use Hermes' prompt path"
    # The advisory pre-action chain is gone from this node, not merely bypassed: dead code that
    # reads as live is how the next reader re-introduces the cost.
    node = source[source.index("def planner_node(") : source.index("def _plan_tool_steps(")]
    assert "should_create_plan(" not in node, "planner_node must not call the classifier any more"
    assert "create_plan(" not in node, "planner_node must not generate a plan before the loop"
    assert 'if state.get("plan"):\n        return {}' in node, (
        "a plan the model wrote must survive the next planner pass"
    )


def test_a_plan_update_call_writes_the_models_list_into_state():
    source = _planner_source()
    assert 'if tool_name == "plan_update":' in source, "the model's list must win over receipt inference"
    assert 'plan and tool_name != "plan_update"' in source, (
        "receipt-driven advancement must not second-guess an explicit list"
    )


# ── EXECUTED: the node itself, with the planner factory sabotaged ─────────────────────
# The text pins above prove the code reads this way. These prove it behaves this way, on the real
# graph module, in a venv that can import it. A skip here is a host gap to report, never a pass.

def _graph():
    try:
        import src.graphs.chat_graph as graph
    except ModuleNotFoundError as exc:  # pragma: no cover
        pytest.skip(f"graph not importable on this host (needs the provider/langchain set): {exc}")
    return graph


def _state(task, mode):
    return {
        "messages": [],
        "current_task": task,
        "execution_mode": mode,
        "plan": [],
        "plan_created": False,
        "token_usage": {"input": 0, "output": 0, "cache": 0},
    }


_CONFIG = {"configurable": {"thread_id": "parity-test", "workspace": "."}}


@pytest.mark.parametrize("mode", ["agent", "ask", "debug"])
def test_no_interactive_mode_pays_for_planning_before_acting(mode):
    graph = _graph()
    calls = []

    def _sabotage(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("a provider call was made before the action loop")

    graph.should_create_plan = _sabotage
    graph.create_plan = _sabotage

    out = graph.planner_node(_state("hi", mode), _CONFIG)

    assert calls == [], f"{mode} mode still consults the advisory planner"
    assert out["plan"] == []
    assert out["plan_created"] is False


def test_plan_mode_is_a_prompt_turn_with_no_engine():
    """Hermes: "There is no engine and no model-tool footprint" -- the prompt IS the mode."""

    graph = _graph()
    called = []
    graph.should_create_plan = lambda *a, **k: called.append(1) or (_ for _ in ()).throw(
        AssertionError("plan mode must not run the advisory chain")
    )

    out = graph.planner_node(_state("add retry to the bridge", "plan"), _CONFIG)

    assert called == []
    content = str(out["messages"][0].content)
    assert "PLAN MODE" in content.upper(), "the plan-mode ground rules must reach the agent"
    assert out["plan"] == [], "no generated list is injected; the agent writes the plan itself"


def test_a_plan_the_model_wrote_survives_the_next_planner_pass():
    graph = _graph()
    state = _state("keep going", "agent")
    state["plan"] = [{"id": 1, "description": "write hello.py", "status": "in_progress"}]

    out = graph.planner_node(state, _CONFIG)

    assert out == {}, f"a bare no-plan return would erase the model's list: {out!r}"


def test_plan_mode_mirrors_the_saved_plan_into_the_inspector():
    """A plan nobody can see is not a deliverable.

    Upstream keeps PLAN MODE invisible in the CLI (the turn reports a tool count and the user opens the
    markdown). The desktop panel has a real PLAN section fed by graph state, so the prompt has to hand it
    the steps -- without touching the frozen corpus text, which the prompt-parity lane compares
    byte-for-byte against `upstream_corpus.json`.
    """

    from src.prompts.hermes.plan_learn import build_plan_prompt

    prompt = build_plan_prompt("Add retry to the bridge")
    assert "Surface contract" in prompt
    assert "`plan_update`" in prompt, "the plan must be mirrored into the state the UI reads"
    assert "After saving the plan file" in prompt, "file first, then mirror -- not two competing lists"
    assert prompt.startswith("[/plan — plan mode]"), "the upstream-shaped head stays intact"
    assert ".hermes" not in prompt, "local paths only; corpus text is adapted, not edited"
