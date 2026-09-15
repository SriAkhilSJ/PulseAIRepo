"""The nudge trail is request-scoped — hermes' drop-the-trail law.

hermes turn_truncation.py marks every continuation nudge, bounds it, and at
the recovery's end DELETES the trail: "Unanswered continue nudges made every
later turn re-truncate: drop the trail." Crusor's recovery nudges (incomplete,
stall, finish, verify, artifact, plan-wrap) used to be PERSISTED
SystemMessage rows that accumulated in the transcript and shaped every later
request — each repeated imperative row biases the next completion toward
exactly those imperatives (field 2026-09-10: the degenerate turn looped on
the nudges' leading word, "continue").

The law pinned here: every nudge is tagged (crusor_nudge) at creation, and
finalize sweeps every tagged row out of the transcript — on the success,
failed, unverified, and cancelled paths alike. Nothing but real work
survives a turn.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

GATES = "src/graphs/gates.py"


# ── creation: every nudge is tagged ─────────────────────────────────────────


def test_every_nudge_row_in_gates_is_tagged():
    """Structural pin: the number of nudge returns in gates.py equals the
    number of crusor_nudge tags — a future untagged nudge breaks this."""
    source = open(GATES, encoding="utf-8").read()
    assert source.count("SystemMessage(content=") == source.count(
        'additional_kwargs={"crusor_nudge": True}'
    ), "every SystemMessage nudge must carry the crusor_nudge tag"


def test_incomplete_branch_nudge_is_tagged():
    from src.graphs.gates import should_continue

    msg = AIMessage(
        content="partial answer",
        additional_kwargs={"crusor_incomplete_response": True},
    )
    state = {"messages": [msg], "incomplete_response_retries": 1}
    route = should_continue(state)
    assert route == "finish_gate"
    out = finish_gate(state)
    row = out["messages"][0]
    assert isinstance(row, SystemMessage)
    assert row.additional_kwargs.get("crusor_nudge") is True


def finish_gate(state):
    from src.graphs.gates import finish_gate_node

    return finish_gate_node(state)


# ── finalize: the trail is dropped on every path ────────────────────────────


@pytest.fixture()
def _no_memory(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setattr(chat_graph, "memory_manager", None)


def _state_with_nudge():
    # In the real graph LangGraph assigns an id when the row is persisted
    # into the checkpoint; the sweep (correctly) only removes id-carrying
    # rows. Construct with an explicit id to mirror that state.
    nudge = SystemMessage(
        content="[System: Continue now.]",
        additional_kwargs={"crusor_nudge": True},
        id="nudge-1",
    )
    return {
        "messages": [
            HumanMessage("fix the build"),
            AIMessage("partial work"),
            nudge,
            AIMessage("the final answer"),
        ],
        "current_task": "fix the build",
        "steps_completed": [], "failed_steps": [], "plan": [],
    }, nudge.id


def test_finalize_sweeps_the_nudge_trail(_no_memory):
    from src.graphs.chat_graph import finalize_node

    state, nudge_id = _state_with_nudge()
    out = finalize_node(state, {"configurable": {}})
    removed = [m for m in out["messages"] if type(m).__name__ == "RemoveMessage"]
    assert [m.id for m in removed] == [nudge_id]
    # finalize appends no prose on success (hermes parity, pinned elsewhere):
    # the sweep is the ONLY thing this return carries.
    assert [m for m in out["messages"] if not type(m).__name__ == "RemoveMessage"] == []


def test_finalize_cancelled_path_sweeps_too(_no_memory):
    from src.graphs.chat_graph import finalize_node

    state, nudge_id = _state_with_nudge()
    state["messages"].append(AIMessage(
        content="x", additional_kwargs={"crusor_cancelled": True},
    ))
    out = finalize_node(state, {"configurable": {}})
    assert out["task_status"] == "cancelled"
    removed = [m for m in out["messages"] if type(m).__name__ == "RemoveMessage"]
    assert nudge_id in [m.id for m in removed]


def test_untagged_rows_are_never_swept(_no_memory):
    from src.graphs.chat_graph import finalize_node

    state, _ = _state_with_nudge()
    # a legacy/foreign System row without the tag must survive
    state["messages"].insert(1, SystemMessage(content="PERSONA"))
    out = finalize_node(state, {"configurable": {}})
    removed_ids = {m.id for m in out["messages"] if type(m).__name__ == "RemoveMessage"}
    assert len(removed_ids) == 1  # only the tagged nudge
