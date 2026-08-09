"""Regression pins for the lab run 10 fixes.

- F6/F3: ai_node fails over to the base provider/model when the routed
  tier's LLM call raises (e.g. 403 on a blocked Groq model) instead of
  killing the turn.
- F2: planner_node degrades to a "no plan" dict on any plan-generation
  failure instead of raising / emitting {"planner": None}.
- Pivot: pivot_node injects strategy-switch guidance, resets the recovery
  budget, and is bounded by pivot_count.
"""

from __future__ import annotations


def _cfg(provider="custom", model="auto"):
    return {
        "configurable": {
            "provider": provider,
            "model": model,
            "thread_id": "lab-fixes-test",
            "workspace": ".",
        }
    }


# ---------------------------------------------------------------------
# F6/F3 — ai_node provider failover
# ---------------------------------------------------------------------

def test_ai_node_fails_over_to_base_tier_on_provider_error(monkeypatch):
    import src.graphs.chat_graph as cg
    from langchain_core.messages import AIMessage, HumanMessage
    from src.context.token_tracker import TokenUsage

    class _Failing:
        def bind_tools(self, tools):
            class _Bound:
                def invoke(self, messages):
                    raise PermissionError("403 blocked model at project level")
            return _Bound()

    class _Working:
        def __init__(self, provider, model):
            self.provider, self.model = provider, model

        def bind_tools(self, tools):
            class _Bound:
                def invoke(self, messages):
                    return AIMessage(content="served by base tier")
            return _Bound()

    built = []

    def _fake_get_llm(provider, model):
        built.append((provider, model))
        if provider == "groq":
            return _Failing()
        return _Working(provider, model)

    monkeypatch.setattr(cg, "get_llm", _fake_get_llm)
    monkeypatch.setattr(
        cg, "cost_router",
        type("R", (), {"route": staticmethod(lambda *a, **k: ("groq", "blocked-model"))})(),
    )
    monkeypatch.setattr(
        cg, "get_context_engine",
        lambda config: type(
            "E", (),
            {"build_ai_messages": staticmethod(
                lambda state, system_message: [HumanMessage(content="hi")]
            )},
        )(),
    )
    monkeypatch.setattr(
        cg, "TokenTracker",
        type("T", (), {"record_call": staticmethod(lambda *a, **k: TokenUsage())}),
    )

    state = {"current_task": "t", "plan": [], "token_usage": {}, "messages": []}
    out = cg.ai_node(state, _cfg())
    assert built == [("groq", "blocked-model"), ("custom", "auto")]
    assert out["messages"][0].content == "served by base tier"


def test_ai_node_raises_when_base_tier_also_fails(monkeypatch):
    import src.graphs.chat_graph as cg
    from langchain_core.messages import HumanMessage

    class _AlwaysFails:
        def bind_tools(self, tools):
            class _Bound:
                def invoke(self, messages):
                    raise RuntimeError("provider fully down")
            return _Bound()

    monkeypatch.setattr(cg, "get_llm", lambda provider, model: _AlwaysFails())
    monkeypatch.setattr(
        cg, "cost_router",
        type("R", (), {"route": staticmethod(lambda *a, **k: ("groq", "blocked-model"))})(),
    )
    monkeypatch.setattr(
        cg, "get_context_engine",
        lambda config: type(
            "E", (),
            {"build_ai_messages": staticmethod(
                lambda state, system_message: [HumanMessage(content="hi")]
            )},
        )(),
    )

    state = {"current_task": "t", "plan": [], "token_usage": {}, "messages": []}
    try:
        cg.ai_node(state, _cfg())
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError when both tiers fail")


# ---------------------------------------------------------------------
# F2 — planner_node graceful degradation
# ---------------------------------------------------------------------

def test_planner_node_degrades_to_no_plan_on_failure(monkeypatch):
    import src.graphs.chat_graph as cg

    def _boom(**kwargs):
        raise RuntimeError("plan llm down")

    monkeypatch.setattr(cg, "should_create_plan", lambda **kw: True)
    monkeypatch.setattr(
        cg, "cost_router",
        type("R", (), {"route": staticmethod(lambda *a, **k: ("groq", "blocked"))})(),
    )
    monkeypatch.setattr(cg, "create_plan", _boom)

    state = {"current_task": "task", "plan_created": False, "token_usage": {}}
    out = cg.planner_node(state, _cfg())
    assert out["plan"] == []
    assert out["plan_created"] is False
    assert out["plan_goal"] == ""
    assert "token_usage" in out


def test_planner_node_builds_plan_normally(monkeypatch):
    import src.graphs.chat_graph as cg

    class _Step:
        def model_dump(self):
            return {"id": 1, "description": "do the thing", "status": "pending"}

    class _Plan:
        goal = "task"
        steps = [_Step(), _Step()]

    monkeypatch.setattr(cg, "should_create_plan", lambda **kw: True)
    monkeypatch.setattr(
        cg, "cost_router",
        type("R", (), {"route": staticmethod(lambda *a, **k: ("custom", "auto"))})(),
    )
    monkeypatch.setattr(cg, "create_plan", lambda **kw: _Plan())

    state = {"current_task": "task", "plan_created": False, "token_usage": {}}
    out = cg.planner_node(state, _cfg())
    assert out["plan_created"] is True
    assert len(out["plan"]) == 2
    # start_next_plan_step marks the first pending step in_progress
    assert out["plan"][0]["status"] == "in_progress"
    assert out["plan"][1]["status"] == "pending"


def test_planner_node_classifier_failure_still_degrades(monkeypatch):
    import src.graphs.chat_graph as cg

    def _boom(**kwargs):
        raise RuntimeError("classifier llm down")

    monkeypatch.setattr(cg, "should_create_plan", _boom)
    state = {"current_task": "task", "plan_created": False, "token_usage": {}}
    out = cg.planner_node(state, _cfg())
    assert out["plan"] == []
    assert out["plan_created"] is False


# ---------------------------------------------------------------------
# pivot_node
# ---------------------------------------------------------------------

def test_pivot_node_injects_guidance_and_resets_recovery_budget():
    from src.graphs.chat_graph import pivot_node
    import src.graphs.progress_helpers as ph

    out = pivot_node({"pivot_count": 0})
    assert out["pivot_count"] == 1
    assert out["recovery_mode"] is False
    assert out["recovery_command"] is None
    assert out["recovery_attempts"] == 0
    assert out["env_failures"] == 0
    msgs = out["messages"]
    assert msgs and msgs[0].content == ph.PIVOT_GUIDANCE_PROMPT
    assert "PIVOT YOUR STRATEGY" in ph.PIVOT_GUIDANCE_PROMPT
