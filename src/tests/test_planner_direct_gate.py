"""One-step questions must never enter the plan loop (founder-pbr004-1).

Measured: the PLAN/DIRECT classifier returned a confident-wrong PLAN for
"Summarize the workspace." and the plan loop burned 20 full-context laps —
21 calls / 118k input tokens / $0.12 to answer one question.
"""


# ------------------------------------------- one-step questions never plan (PBR-004)

def test_obvious_questions_are_direct_without_spending_a_call(monkeypatch):
    """founder-pbr004-1 pin: 'Summarize the workspace.' got a wrong PLAN
    verdict and the plan loop burned 20 full-context laps ($0.12 for one
    question). Obvious one-step questions must return DIRECT and must not
    even invoke the PLAN/DIRECT classifier LLM."""
    import src.agents.planner as planner

    def no_llm_allowed(*args, **kwargs):
        raise AssertionError("classifier LLM must not be called for obvious questions")

    monkeypatch.setattr(planner, "get_llm", no_llm_allowed)
    for task in (
        "Summarize the workspace.",
        "Explain workspace_proof.py",
        "What is this project about?",
        "Describe the structure of the repo",
    ):
        assert planner.should_create_plan(task, "custom", "m") is False, task


def test_plan_verdict_on_obvious_question_is_overridden(monkeypatch):
    """Even when the classifier DOES run and answers PLAN, an obvious
    one-step question stays DIRECT (the measured wrong-verdict case)."""
    import src.agents.planner as planner

    class _PlanAlways:
        content = "PLAN"

        def invoke(self, *a, **k):
            return self

    monkeypatch.setattr(planner, "get_llm", lambda *a, **k: _PlanAlways())
    assert planner.should_create_plan("Summarize the workspace.", "custom", "m") is False
    # A real multi-step task with a PLAN verdict is still a plan:
    assert planner.should_create_plan(
        "Create a login page and run the tests", "custom", "m") is True


def test_real_plan_tasks_still_reach_the_classifier(monkeypatch):
    import src.agents.planner as planner

    called = []

    class _Direct:
        content = "DIRECT"

        def invoke(self, *a, **k):
            called.append(1)
            return self

    monkeypatch.setattr(planner, "get_llm", lambda *a, **k: _Direct())
    # Not an obvious question -> classifier runs -> DIRECT verdict, then the
    # plan heuristic double-check.
    planner.should_create_plan("Refactor the auth module", "custom", "m")
    assert called, "classifier must still run for non-obvious tasks"
