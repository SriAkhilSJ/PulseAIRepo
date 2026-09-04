"""Finalize writes NO prose on success — hermes parity.

Owner reports, in order: (1) a bare "hi" turn came back stapled to
"## ✅ Finished: hi / What would you like to do next?" — fake product voice on
chat turns; (2) after the stamp was gated to work runs, a directory-listing
turn closed with "### ✅ Finished: hi" — the stamp leaked a STALE task name
AND hard-coded tail text ("hardcoded text at last", 2026-09-04 screenshots).
Hermes appends nothing after the model's answer: the streamed words ARE the
turn. Everything the stamp carried rides structure now — verdict in
task_completed/task_status, per-step outcomes in tool cards, suggestions in
the `suggestions` event. Only DEVIATIONS keep words: an unverified or failed
run says so plainly (D9), because the model's own answer may claim success.
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


def test_successful_work_run_stamps_nothing(_no_memory):
    """hermes parity (owner, 2026-09-04): even a run that DID work gets NO
    finalize prose on success — no "Finished" stamp, no "What I did"
    inventory, no sign-off tail. The model's streamed answer is the entire
    transcript; the verdict rides out structurally."""
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["steps_completed"] = ["Wrote file: app/page.tsx"]
    out = finalize_node(dict(state), {"configurable": {}})
    assert out["messages"] == []
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


def test_work_run_never_carries_the_signoff_tail(_no_memory):
    """The "--- / *Need any tweaks? Just let me know!*" tail is dead. No
    finalize message may contain invented sign-off voice, on any outcome."""
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["steps_completed"] = ["Wrote file: app/page.tsx"]
    out = finalize_node(dict(state), {"configurable": {}})
    for m in out["messages"]:
        assert "Need any tweaks" not in m.content
        assert "What would you like to do next" not in m.content


def test_failed_run_keeps_the_incomplete_stamp(_no_memory):
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["failed_steps"] = ["Terminal verification crashed"]
    out = finalize_node(dict(state), {"configurable": {}})
    text = out["messages"][0].content
    assert "Ended incomplete" in text
    assert "✅ Finished" not in text
    assert "Need any tweaks" not in text, "deviation notes stay bare — no sign-off tail"
    assert out["task_completed"] is False
