"""Plan-vs-task constraint check: general, model-driven, zero hardcoded data.

test5-3 pin: the planner produced 'scaffold Next.js' against a task that
demands 'native HTML/JS, no build step'. No regex can know Next.js implies
a build step -- the check must READ the task, quote the contradiction, and
trigger exactly one corrected retry.
"""
from langchain_core.messages import AIMessage

from src.models.plan_models import TaskPlanStep


class _Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def invoke(self, messages, *a, **k):
        self.calls.append(messages)
        return AIMessage(content=self.replies.pop(0))


def test_validator_returns_empty_on_ok(monkeypatch):
    import src.agents.planner as p
    llm = _Scripted(["OK"])
    monkeypatch.setattr(p, "get_llm", lambda *a, **k: llm)
    out = p._plan_constraint_violation("task text", [{"step": "write index.html"}], "custom", "m")
    assert out == ""
    assert llm.calls, "the validator must actually ask the model"
    # constraints are read from the TASK text, nothing hardcoded:
    sent = llm.calls[0][1].content
    assert "task text" in sent and "write index.html" in sent


def test_validator_quotes_contradiction(monkeypatch):
    import src.agents.planner as p
    llm = _Scripted(["VIOLATION: step 2 contradicts 'no build step'"])
    monkeypatch.setattr(p, "get_llm", lambda *a, **k: llm)
    out = p._plan_constraint_violation(
        "build native, no build step", [{"step": "scaffold Next.js"}], "custom", "m"
    )
    assert llm.calls, "the validator must actually ask the model"
    assert out.startswith("VIOLATION"), repr(out)
    assert "no build step" in out


def test_validator_handles_real_task_plan_steps_and_tracks_usage(monkeypatch):
    """TaskPlan.steps contains Pydantic objects, not dictionaries."""
    import src.agents.planner as p

    llm = _Scripted(["OK"])
    monkeypatch.setattr(p, "get_llm", lambda *a, **k: llm)
    usage = []
    out = p._plan_constraint_violation(
        "build native HTML",
        [TaskPlanStep(id=1, description="write index.html")],
        "custom",
        "m",
        usage,
    )
    assert out == ""
    assert "write index.html" in llm.calls[0][1].content
    assert len(usage) == 1, "an initially-empty usage ledger must receive the validator call"


def test_validator_failure_is_advisory(monkeypatch):
    import src.agents.planner as p

    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(p, "get_llm", boom)
    assert p._plan_constraint_violation("t", [{"step": "x"}], "custom", "m") == ""
