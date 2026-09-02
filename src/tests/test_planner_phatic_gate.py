"""A greeting must not cost a provider call.

The owner typed "hi" into the desktop agent and it took 42 seconds at the provider before surfacing an
error: `should_create_plan` had exactly one free bypass -- a list of request verbs -- and "hi" contains no
verb, so it went to the LLM classifier, came back PLAN, and then a second call built a plan for a greeting.
The gate could recognise a question but not the absence of a request.

These tests are EXECUTED with the model factory sabotaged: the phatic cases must return before `get_llm`
is reachable (a call here is the waste we are removing), and the non-phatic cases must still reach it, so
the whitelist cannot quietly grow into a rule that skips planning on real work.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def planner():
    """Import the planner with the model factory stubbed out.

    `src.llm.factory` imports every provider SDK, which has nothing to do with a string gate and is not
    installed on a fresh host. Stubbing it is what lets this test EXECUTE instead of skip -- a skipped
    gate test proves nothing, which is the lesson this repo has already paid for twice.
    """
    import sys
    import types

    if "src.llm.factory" not in sys.modules:
        stub = types.ModuleType("src.llm.factory")
        stub.get_llm = lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("the model factory is not available in this test")
        )
        sys.modules["src.llm.factory"] = stub
    try:
        import src.agents.planner as module
    except ModuleNotFoundError as exc:  # pragma: no cover - host gap, never a pass
        pytest.skip(f"planner not importable on this host: {exc}")
    return module


@pytest.fixture
def no_provider(monkeypatch, planner):
    calls = []

    def _boom(**kwargs):
        calls.append(kwargs)
        raise AssertionError(f"the classifier was asked to run: {calls}")

    monkeypatch.setattr(planner, "get_llm", _boom)

    return calls


@pytest.mark.parametrize("task", ["hi", "hiii", "hello there", "thanks", "thank you!", "ok", "okkk",
                                 "hey", "good morning", "yo", "ty", "nice", "hi, thanks"])
def test_a_social_turn_answers_socially_for_free(task, planner, no_provider):
    assert planner.should_create_plan(task=task, provider="x", model="y") is False
    assert no_provider == [], "a phatic turn must never reach the model factory"


@pytest.mark.parametrize("task", [
    "hi, run the tests and fix the first failure",
    "fix this",
    "refactor the planner gate",
    "hi the build is broken",
    "hello world program",
])
def test_a_real_request_still_reaches_the_classifier(task, planner, monkeypatch):
    reached = []

    def _capture(**kwargs):
        reached.append(kwargs)
        raise RuntimeError("stop here; the classifier was consulted")

    monkeypatch.setattr(planner, "get_llm", _capture)
    # Any exception inside should_create_plan degrades to "no plan" upstream, so what this asserts is the
    # call itself -- the gate did not fire on a message that carries a request.
    try:
        planner.should_create_plan(task=task, provider="x", model="y")
    except Exception:
        pass
    assert reached, f"{task!r} skipped the classifier -- the phatic whitelist is too broad"
