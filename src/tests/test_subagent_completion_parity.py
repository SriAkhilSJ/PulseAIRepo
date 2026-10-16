"""Completion truth, ported from OpenCode's subagent implementation
(upstream `packages/core/src/tool/plugin/subagent.ts`,
`session/subagent-completion.ts`, `job.ts` — read 2026-10-16 at the
founder's word: "jzt read opencode sub agents files and copy the
codes … but should support our environment").

Upstream's contract is a status machine, not a reading of the text:

- the child's run ends; its output is the last assistant message's
  text, or NO_TEXT ("Subagent completed without a text response.")
  when the run produced none;
- exit status `error` FAILS the parent tool call with
  `Subagent failed (sessionID: …): …` — the session id stays visible
  so the parent can resume that exact child;
- `cancelled` likewise fails with `Subagent cancelled (sessionID: …)`;
- only a clean run end earns `status: "completed"`.

Our environment's seams: the coordinator is the job run (its settled
verdict must travel WITH the text — reading the text alone stamped
a crashed child's apology "succeeded" at the lifecycle, overwrote
the store row marked failed, and the delegate tool answered the
parent with a "completed" header over a crash). These pins expire
on contact with that regression. invoke_agent is faked throughout —
no LLM, no network.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

import src.graphs.chat_graph as cg
from src.agents.sub_agent import NO_TEXT_RESPONSE, SubAgentCoordinator


def _fake_invoke(behavior):
    def fake(message, thread_id="default", provider=None, model=None,
             workspace=".", execution_mode="agent", **_kw):
        return behavior(thread_id, message)
    return fake


def test_empty_child_output_completes_with_the_no_text_sentence(monkeypatch):
    """Upstream: `text(assistant) || NO_TEXT`. A child that ends its
    run with no final text completes with the honest placeholder —
    never an empty result the parent (and the card) reads as a
    deliverable."""
    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke(lambda tid, msg: ""))
    coord = SubAgentCoordinator()
    agent_id = coord.spawn("research", "Research nothing", "parent-thread")
    state, result = coord.get_outcome(agent_id)
    assert state == "succeeded"
    assert result == NO_TEXT_RESPONSE == "Subagent completed without a text response."


def test_crashed_child_outcome_is_failed_and_text_view_stays_compatible(monkeypatch):
    """Upstream: status and output are separate job fields. The
    crash sentence is the output; `failed` is the status; a consumer
    lifting only the text must never be able to re-stamp it success
    (that decision now belongs to whoever reads the outcome)."""
    def boom(tid, msg):
        raise RuntimeError("provider down")
    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent", _fake_invoke(boom))
    coord = SubAgentCoordinator()
    agent_id = coord.spawn("review", "Review the diff", "parent-thread")
    state, result = coord.get_outcome(agent_id)
    assert state == "failed"
    assert "Sub-agent crashed" in result


def test_lifecycle_keeps_a_failed_outcome_failed(monkeypatch):
    """The exact inversion this port removes: lifecycle._run used to
    read only the result text and stamp SUCCEEDED unconditionally,
    then persist over the row the coordinator marked failed."""
    from src.agents.subagent_lifecycle import SubagentLifecycleService

    class FakeCoordinator:
        def spawn(self, **kwargs):
            return kwargs["agent_id"]

        def get_outcome(self, _agent_id):
            return "failed", "⛔ Sub-agent crashed: RuntimeError('boom')"

    monkeypatch.setattr("src.agents.sub_agent.subagent_coordinator", FakeCoordinator())
    service = SubagentLifecycleService(max_workers=1)
    handle = service.launch(parent_session_id="p", goal="review auth", mode="review")
    result = service.wait(handle, timeout=2)
    assert result["state"] == "failed"
    assert "Sub-agent crashed" in (result["error"] or "")
    assert result["ready"] is True


def _delegate_app():
    g = StateGraph(MessagesState)
    g.add_node("tools", ToolNode([cg.delegate_to_subagent]))
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    return g.compile()


def test_delegate_fails_the_call_with_the_resumable_session_id(monkeypatch):
    """Upstream: `Subagent failed (sessionID: …): …` as a tool
    failure — never a 'completed' header over a crash, and the
    session id survives so the parent can resume the child."""
    def boom(**_kw):
        raise RuntimeError("sub-agent exploded (provider down)")
    monkeypatch.setattr(cg, "invoke_agent", boom)
    out = _delegate_app().invoke(
        {"messages": [AIMessage(content="", tool_calls=[{
            "name": "delegate_to_subagent",
            "args": {"mode": "review", "task": "audit the parser"},
            "id": "call_1",
        }])]},
        config={"configurable": {"thread_id": "main", "workspace": "."}},
    )
    content = str(out["messages"][-1].content)
    assert "Subagent failed (session_id: sub-" in content
    assert "Sub-agent crashed" in content  # the cause survives for the parent
    assert "sub-agent exploded" in content
    assert "completed" not in content.split("):")[0]


# ---------------------------------------------------------------------------
# Delivery: the child's answer reaches the parent whole, once.
# Founder field 2026-10-16: the parent announced "its conclusion was
# truncated in the summary and I can't verify from it whether your
# preference question was actually asked and answered" and re-asked
# the user. The envelope cut the result at 2,000 characters,
# head-first (the conclusion lives at the end), and pasted the
# truncated text twice (friendly blob + XML). OpenCode's tool-output
# limits are 2,000 lines / 50 KiB — those are the limits now, the
# result is delivered once, and a real truncation says so.
# ---------------------------------------------------------------------------

def test_delegate_result_survives_past_the_old_2000_char_cut():
    from src.agents.subagent_permissions import truncate_delegate_result
    conclusion = "CONCLUSION: bubble wins on nearly-sorted data."
    text = ("research notes line\n" * 200) + conclusion
    assert len(text) > 2000
    delivered = truncate_delegate_result(text, "sub-x-1")
    assert delivered == text  # whole, once, no marker


def test_delegate_result_truncation_is_explicit_and_points_at_the_child():
    from src.agents.subagent_permissions import truncate_delegate_result
    text = "x" * (60 * 1024)
    delivered = truncate_delegate_result(text, "sub-x-2")
    assert delivered.startswith("x" * 100)
    assert "Result truncated" in delivered
    assert "session_id: sub-x-2" in delivered
    assert len(delivered) < len(text)


def test_format_task_output_no_longer_amputates_at_2000_chars():
    from src.agents.subagent_permissions import format_task_output
    conclusion = "CONCLUSION: merge wins on random data."
    text = ("evidence line\n" * 200) + conclusion
    out = format_task_output(session_id="sub-x-3", state="completed", text=text)
    assert conclusion in out
