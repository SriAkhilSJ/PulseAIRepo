"""Task-classifier robustness: a prose answer must never fail a turn.

Owner desktop run: the classifier asked for strict JSON; `auto/best-chat`
answered the literal word `unrelated` -- semantically correct, syntactically
prose -- and with_structured_output raised ValidationError, which
RetryLLMProxy retried 5x (a permanently failing parse) before the turn died
in "Asking..." dead air. Pinned here: every shape the router's three-word
vocabulary can arrive in is salvaged, and a hopeless answer falls back to
the SAFE default ('continue' preserves the active task) with one honest
log line -- never an exception, never a silent guess.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# _salvage_task_decision: the parser contract
# ---------------------------------------------------------------------------

def test_bare_word_unrelated_is_salvaged():
    """The owner's exact case: the model answered in one plain word."""
    from src.graphs.chat_graph import _salvage_task_decision

    decision = _salvage_task_decision("unrelated")
    assert decision is not None
    assert decision.action == "unrelated"


def test_bare_words_with_case_and_punctuation():
    from src.graphs.chat_graph import _salvage_task_decision

    for raw, expected in (
        ("Continue.", "continue"), ("NEW", "new"),
        ("  unrelated!  ", "unrelated"),
    ):
        decision = _salvage_task_decision(raw)
        assert decision is not None and decision.action == expected, raw


def test_prose_naming_the_action_is_salvaged():
    from src.graphs.chat_graph import _salvage_task_decision

    decision = _salvage_task_decision(
        "This message is unrelated to the current coding task."
    )
    assert decision is not None and decision.action == "unrelated"


def test_direct_json_and_fenced_json_are_salvaged():
    from src.graphs.chat_graph import _salvage_task_decision

    direct = _salvage_task_decision('{"action": "new", "updated_task": "build login"}')
    assert direct is not None and direct.action == "new"
    assert direct.updated_task == "build login"

    fenced = _salvage_task_decision(
        'Here is my answer:\n```json\n{"action": "continue"}\n```'
    )
    assert fenced is not None and fenced.action == "continue"


def test_garbage_returns_none():
    from src.graphs.chat_graph import _salvage_task_decision

    assert _salvage_task_decision("") is None
    assert _salvage_task_decision("42") is None
    long_prose = ("The quick brown fox jumps over the lazy dog. " * 6)
    assert _salvage_task_decision(long_prose) is None  # >200 chars, no action word


def test_long_prose_mentioning_new_does_not_hijack():
    from src.graphs.chat_graph import _salvage_task_decision

    essay = (
        "Everything in this repository is quite new to me, and I have been "
        "reviewing the structure for a while now. " * 3
    )
    decision = _salvage_task_decision(essay)
    # too long to trust a word-match; not JSON; must NOT classify as new
    assert decision is None or decision.action != "new"


# ---------------------------------------------------------------------------
# _invoke_task_decision: the never-fail lane
# ---------------------------------------------------------------------------

class _FakeLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        return AIMessage(content=self._content)


def test_invoke_returns_decision_for_prose_answer():
    from src.graphs.chat_graph import _invoke_task_decision

    decision = _invoke_task_decision(_FakeLLM("unrelated"), [])
    assert decision.action == "unrelated"


def test_invoke_never_raises_on_garbage(capsys):
    from src.graphs.chat_graph import _invoke_task_decision

    decision = _invoke_task_decision(_FakeLLM("lorem ipsum dolor sit"), [])
    assert decision.action == "continue"
    out = capsys.readouterr().out
    assert "[task_classifier]" in out and "continue" in out


def test_invoke_handles_block_shaped_content():
    from src.graphs.chat_graph import _invoke_task_decision

    class BlockLLM:
        def invoke(self, messages):
            from langchain_core.messages import AIMessage

            return AIMessage(content=[{"type": "text", "text": '{"action": "new"}'}])

    assert _invoke_task_decision(BlockLLM(), []).action == "new"


# ---------------------------------------------------------------------------
# task_manager_node end-to-end with a prose model (the regression that was)
# ---------------------------------------------------------------------------

@pytest.fixture()
def _no_memory(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setattr(chat_graph, "memory_manager", None)


def test_task_manager_node_survives_prose_model(monkeypatch):
    """A real instruction (NOT a conversational opener -- those take the free
    path and never reach the LLM) answered in prose must classify, not die."""
    from langchain_core.messages import HumanMessage

    import src.graphs.chat_graph as chat_graph

    monkeypatch.setattr(
        chat_graph, "_task_manager_llm",
        lambda provider, model: _FakeLLM("This seems unrelated to the task"),
    )
    state = {
        "messages": [HumanMessage("also fix the flaky login test please")],
        "latest_instruction": "also fix the flaky login test please",
        "current_task": "build a chat app",
        "token_usage": {},
    }
    config = {"configurable": {"thread_id": "t-owner", "workspace": "."}}
    out = chat_graph.task_manager_node(dict(state), config)
    assert out["task_action"] == "unrelated"
    assert out["current_task"] == "build a chat app"  # preserved


def test_conversational_opener_never_reaches_the_llm(monkeypatch):
    """The hermes-aligned mechanism: 'hello??' classifies FREE -- the fake
    LLM raises if consulted, proving zero provider calls were spent."""
    from langchain_core.messages import HumanMessage

    import src.graphs.chat_graph as chat_graph

    def _boom(provider, model):
        raise AssertionError("opener must not pay a classifier round-trip")

    monkeypatch.setattr(chat_graph, "_task_manager_llm", _boom)
    state = {
        "messages": [HumanMessage("hello??")],
        "latest_instruction": "hello??",
        "current_task": "build a chat app",
        "token_usage": {},
    }
    config = {"configurable": {"thread_id": "t-owner", "workspace": "."}}
    out = chat_graph.task_manager_node(dict(state), config)
    assert out["task_action"] == "continue"
    assert out["current_task"] == "build a chat app"
