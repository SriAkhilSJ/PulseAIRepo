"""Loop guards ported from hermes-agent: the loop law + repetition sanity.

The measured reason these exist (founder-pbr004-1): a plan loop produced
~20 full-context laps with ZERO tool calls to answer one question
($0.12). Behavior-based caps make that class structurally impossible.
"""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _ai(text="answer", tool_calls=None):
    return AIMessage(content=text, tool_calls=tool_calls or [])


def test_streak_counts_trailing_no_tool_replies_only():
    from src.graphs.loop_guards import consecutive_no_tool_ai_messages
    msgs = [HumanMessage(content="q"), _ai(), _ai()]
    assert consecutive_no_tool_ai_messages(msgs) == 2
    # tool activity resets the streak
    msgs2 = [HumanMessage(content="q"), _ai(), _ai(tool_calls=[{"name": "t", "args": {}, "id": "1"}])]
    assert consecutive_no_tool_ai_messages(msgs2) == 0
    # human boundary ends it
    msgs3 = [_ai(), HumanMessage(content="and?"), _ai()]
    assert consecutive_no_tool_ai_messages(msgs3) == 1


def test_repetition_guard_ports_hermes_shape():
    from src.graphs.loop_guards import is_repetition_dominated
    frag = "x" * 100
    echo = "\n".join([frag] * 8)  # 800 chars, one line repeated
    assert is_repetition_dominated(echo) is True
    # ordinary prose is never blocked
    prose = " ".join(f"sentence number {i} is unique content" for i in range(40))
    assert is_repetition_dominated(prose) is False
    # short inputs fail open
    assert is_repetition_dominated("short short short") is False
    assert is_repetition_dominated("") is False


def test_router_ends_turn_after_no_tool_limit():
    """3 consecutive no-tool assistant replies => finalize, regardless of
    which loop produced them (plan, replan, misroute)."""
    from src.graphs.gates import should_continue
    msgs = [HumanMessage(content="Summarize the workspace.")]
    for _ in range(3):
        msgs.append(_ai("Working on the summary..."))
    state = {"messages": msgs, "current_task": "Summarize the workspace.",
             "finish_nudges": 99, "verify_nudges": 99}  # nudges already spent
    assert should_continue(state) == "finalize"


def test_router_keeps_bounded_nudges_below_the_limit():
    """The FIRST no-tool reply still goes through the (bounded) finish gate —
    the cap only backstops the pathological streak."""
    from src.graphs.gates import should_continue
    msgs = [HumanMessage(content="Summarize the workspace."), _ai("summary text")]
    state = {"messages": msgs, "current_task": "build app and test it",
             "finish_nudges": 0, "verify_nudges": 0}
    # execution-shaped task with zero tool calls and no deliverables ->
    # the existing finish_gate nudge still fires (bounded behavior unchanged)
    assert should_continue(state) == "finish_gate"


def test_router_finalizes_repetition_dominated_reply():
    from src.graphs.gates import should_continue
    frag = "x" * 120
    echo = "\n".join([frag] * 10)
    msgs = [HumanMessage(content="q"), _ai(echo)]
    state = {"messages": msgs, "current_task": "task",
             "finish_nudges": 0, "verify_nudges": 0}
    assert should_continue(state) == "finalize"
