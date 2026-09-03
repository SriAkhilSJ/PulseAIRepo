"""Finalize-stamp contract: the run stamp belongs to WORK, not to conversation.

Owner report (desktop screenshots): a bare "hi" turn came back as the model's
greeting stapled to "## ✅ Finished: hi / ### 💡 What would you like to do
next? / *Just tell me, or say 'done'...*" — the D9 stamp block, which exists
to keep CODING runs from lying about success, was being glued onto chat turns
where nothing was done, nothing failed, and nothing was unverified. Fake
product voice. The stamp now requires work; chat turns return no finalize
message at all (the model's streamed words are the whole transcript) and the
verdict still rides out structurally.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def _no_memory(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setattr(chat_graph, "memory_manager", None)


def _chat_state() -> dict:
    from langchain_core.messages import AIMessage, HumanMessage

    return {
        "messages": [HumanMessage("hi"), AIMessage("Hi! How can I help you today?")],
        "current_task": "hi",
        "steps_completed": [],
        "failed_steps": [],
        "plan": [],
    }


def test_pure_chat_turn_stamps_nothing(_no_memory):
    from src.graphs.chat_graph import finalize_node

    out = finalize_node(dict(_chat_state()), {"configurable": {}})
    # No finalize message at all: the model's own words are the transcript.
    assert out["messages"] == []
    # The verdict is still structural, not lost.
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


def test_work_run_keeps_the_finished_stamp(_no_memory):
    """D9 protection stays intact: a run that DID work keeps the honest stamp."""
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["steps_completed"] = ["Wrote file: app/page.tsx"]
    out = finalize_node(dict(state), {"configurable": {}})
    text = out["messages"][0].content
    assert "## ✅ Finished" in text
    assert "### 📁 What I did:" in text
    assert out["task_completed"] is True


def test_failed_run_keeps_the_incomplete_stamp(_no_memory):
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["failed_steps"] = ["Terminal verification crashed"]
    out = finalize_node(dict(state), {"configurable": {}})
    text = out["messages"][0].content
    assert "Ended incomplete" in text
    assert "✅ Finished" not in text
    assert out["task_completed"] is False
