"""Hermes stall guard: the "said-continue-but-stopped" re-prompt.

Field 2026-09-10 (engine 72e271c6, test5): after 13 read-only observations
the model announced its next step in text ("...Next, I'll install the
dependencies and create the component...") and the turn FINALIZED mid-plan —
3 of 4 plan steps unstarted, nothing delivered, owner saw "stopped mid way".
hermes agent/turn_final_response.py answers exactly this shape: a SHORT
toolless reply whose tail announces a next action is not a final answer —
it is re-prompted to act (bounded 2/turn, hermes codex_ack_continuations),
with the assistant reply kept as interim. Ported verbatim: the detector
regex, the 400-char cap, the 160-char search window, the nudge text, the
bound.
"""
from langchain_core.messages import AIMessage, HumanMessage

from src.graphs.gates import finish_gate_node, should_continue
from src.graphs.loop_guards import trailing_continue_intent

FIELD_REPLY = (
    "I've reviewed the project structure. The app uses Next.js 15 with "
    "shadcn/ui. Next, I'll install the missing dependencies and create "
    "the demo component."
)


def _ai(text, tool_calls=None):
    return AIMessage(content=text, tool_calls=tool_calls or [])


def _state(msgs, **extra):
    state = {
        "messages": [HumanMessage(content="add the demo page"), *msgs],
        "current_task": "install dependencies and create the demo component",
        "finish_nudges": 99, "verify_nudges": 99,  # other gates spent: isolation
    }
    state.update(extra)
    return state


# ── the detector (hermes _TRAILING_CONTINUE_INTENT_RE, verbatim) ──────────


def test_detector_fires_on_announced_next_action_tails():
    assert trailing_continue_intent(FIELD_REPLY)
    assert trailing_continue_intent("Got the context. Let me now check the components folder.")
    assert trailing_continue_intent("Understood — now I will add the missing imports.")
    assert trailing_continue_intent("next, I: inspect the pages and patch them")


def test_detector_ignores_answers_and_long_replies():
    # a completed answer with no trailing intent is FINAL
    assert not trailing_continue_intent("The build passed and all tests are green.")
    # over 400 chars it is a substantive reply, never a dangling ack
    assert not trailing_continue_intent("x" * 401 + " I'll now go on")
    assert not trailing_continue_intent("")
    # only the tail window matters: early mentions stay inert
    assert not trailing_continue_intent("I'll now mention something, " + "filler " * 60 + ".")


# ── the router: stall intent continues the turn, bounded ─────────────────


def test_router_continues_on_trailing_intent():
    assert should_continue(_state([_ai(FIELD_REPLY)])) == "finish_gate"


def test_router_continues_twice_then_concludes():
    msgs = [_ai(FIELD_REPLY)]
    assert should_continue(_state(msgs, stall_continuations=0)) == "finish_gate"
    msgs.append(HumanMessage(content="[System: Continue now. Execute the required tool calls "
                                     "and only send your final answer after completing the task.]"))
    msgs.append(_ai(FIELD_REPLY))
    assert should_continue(_state(msgs, stall_continuations=1)) == "finish_gate"
    # hermes codex_ack_continuations < 2: the third lap is not re-prompted
    msgs.append(HumanMessage(content="nudge"))
    msgs.append(_ai(FIELD_REPLY))
    assert should_continue(_state(msgs, stall_continuations=2)) == "finalize"


def test_streak_cap_still_wins_over_the_stall_guard():
    msgs = [_ai(FIELD_REPLY), _ai(FIELD_REPLY), _ai(FIELD_REPLY)]
    assert should_continue(_state(msgs, stall_continuations=0)) == "finalize"


def test_grace_lap_never_gets_the_stall_nudge():
    """The budget-exhausted grace lap runs UNBOUND — 'execute the required
    tool calls' would be an order with no tools to execute. Same condition
    as the incomplete-response gate."""
    assert should_continue(_state([_ai(FIELD_REPLY)], iteration_used=999)) == "finalize"


# ── the node: hermes' nudge row, verbatim, with its own counter ───────────


def test_finish_gate_node_emits_hermes_nudge_and_counts():
    out = finish_gate_node(_state([_ai(FIELD_REPLY)], stall_continuations=0))
    nudge = out["messages"][0].content
    assert nudge == ("[System: Continue now. Execute the required tool calls and only "
                     "send your final answer after completing the task.]")
    assert out["stall_continuations"] == 1


def test_state_carries_the_stall_channel():
    from src.graphs.state import AgentState

    assert "stall_continuations" in AgentState.__annotations__


# ── pins: the port stays hermes-verbatim and wired ────────────────────────


def test_pins_hermes_stall_guard():
    guards = open("src/graphs/loop_guards.py", encoding="utf-8").read()
    assert r"\blet me now\b" in guards
    assert "_TRAILING_CONTINUE_INTENT_MAX_CHARS = 400" in guards
    assert "t[-160:]" in guards
    gates = open("src/graphs/gates.py", encoding="utf-8").read()
    assert "[System: Continue now. Execute the required tool calls and only send your " in gates
    assert "_STALL_CONTINUATION_BUDGET = 2" in gates
    assert "StallGuard] turn ending on trailing continue-intent" in gates
