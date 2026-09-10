"""Hermes iteration-summary law (owner field run 2026-09-09 @b75cd4c6:
"check why it ended").

The turn ended at the owner's AGENT_ITERATION_BUDGET=10 and the OLD grace
made a mess of it: a system nudge + ``_drop_tool_pairs`` erased the whole
work history, so the model — seeing nothing — answered "I'll start by
exploring..." with a raw text ``<tool_call>`` block, and the turn finalized
"completed" on that (the owner's screenshot).

hermes handle_max_iterations (agent/chat_completion_helpers.py:2101):
  1. print "⚠️ Reached maximum iterations (N). Requesting summary..."
  2. append MAX_ITERATIONS_SUMMARY_REQUEST (context_compressor.py:261) as a
     USER message on the FULL history (:2119),
  3. call with NO tools key (:2025, codex pops "tools" :2070) — tool traffic
     rides unbound (:1937 _iteration_summary_api_messages),
  4. strip <think>, ONE retry on an empty summary, honest fallback text
     (:1934, :2126-2138).

These pins hold pulse to that law. Pure: fake LLMs, no provider keys.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import src.graphs.chat_graph as cg
from src.graphs.budget import _MAX_ITERATIONS_SUMMARY_REQUEST


HERMES_VERBATIM = (
    "You've reached the maximum number of tool-calling iterations allowed. "
    "Please provide a final response summarizing what you've found and "
    "accomplished so far, without calling any more tools."
)


class _QueuedLLM:
    """Unbound- invoke fake with a reply queue and call recording."""

    model = "m"
    bound = None  # bind_tools prepared but never invoked

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []  # (messages, raised)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, **kwargs):
        self.calls.append((list(messages), False))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            self.calls[-1] = (list(messages), True)
            raise reply
        return AIMessage(content=reply, id=f"r{len(self.calls)}")


class _FakeEngine:
    def build_ai_messages(self, state, system_message):
        # the REAL engine returns the fused system head + the threaded history
        return [SystemMessage(content="PERSONA")] + list(state.get("messages", []))


def _patch(monkeypatch, replies, budget=2):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", str(budget))
    llm = _QueuedLLM(replies)
    monkeypatch.setattr(cg, "get_llm", lambda provider, model: llm)
    monkeypatch.setattr(cg, "get_context_engine", lambda config: _FakeEngine())
    monkeypatch.setattr(cg.cost_router, "route", lambda t, p: ("groq", "m"))
    return llm


def _state(**extra):
    state = {
        "iteration_used": 2,  # at budget -> exhausted on entry
        "current_task": "fix the chat app",
        "messages": [
            HumanMessage(content="fix the chat app"),
            AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {"path": "a.py"}, "id": "c1"}],
            ),
            ToolMessage(content="def run_pulse(): ...", tool_call_id="c1"),
        ],
        "grace_done": 0,
    }
    state.update(extra)
    return state


def _config():
    return {"configurable": {"thread_id": "grace-law", "provider": "groq", "model": "m"}}


# ── The law ─────────────────────────────────────────────────────────────────


def test_summary_request_is_hermes_verbatim():
    assert _MAX_ITERATIONS_SUMMARY_REQUEST == HERMES_VERBATIM


def test_grace_keeps_full_history_and_appends_user_request(monkeypatch):
    """THE pin for the screenshot bug: the model must SEE its work. Tool
    traffic stays in the request; the summary request rides LAST as a human
    message; the summary itself is the only message returned to state."""
    llm = _patch(monkeypatch, replies=["Fixed the <Html> bug; build still red on X."])
    out = cg.ai_node(_state(), _config())

    assert len(llm.calls) == 1
    sent = llm.calls[0][0]
    types = [m.type for m in sent]
    assert types == ["system", "human", "ai", "tool", "human"], (
        "full history (tool pair INCLUDED) + trailing summary request"
    )
    assert sent[-1].content == HERMES_VERBATIM
    # the unbound proxy served the call (same object bind_tools returned) —
    # no tool schemas were attached to the summary request
    assert llm.calls and llm.calls[0][0] is not None
    # the summary is the final assistant message; the request is not persisted
    assert len(out["messages"]) == 1
    assert out["messages"][0].content == "Fixed the <Html> bug; build still red on X."
    assert out["grace_done"] == 1


def test_grace_summary_strips_think_blocks(monkeypatch):
    llm = _patch(monkeypatch, replies=["<think>deliberating</think>All done: bug fixed."])
    out = cg.ai_node(_state(), _config())
    assert out["messages"][0].content == "All done: bug fixed."


def test_empty_summary_retried_once(monkeypatch):
    """hermes :2128 — for retry_count in (0, 1): an empty summary is retried
    once against the same request."""
    llm = _patch(monkeypatch, replies=["", "Second attempt summary."])
    out = cg.ai_node(_state(), _config())
    assert len(llm.calls) == 2, "one retry on the empty summary"
    assert out["messages"][0].content == "Second attempt summary."


def test_double_empty_summary_falls_back_honestly(monkeypatch):
    """hermes :1934 — "I reached the iteration limit and couldn't generate a
    summary." — never a fabricated farewell."""
    llm = _patch(monkeypatch, replies=["", ""])
    out = cg.ai_node(_state(), _config())
    assert out["messages"][0].content == (
        "I reached the iteration limit and couldn't generate a summary."
    )


def test_provider_400_on_full_history_falls_back_text_only(monkeypatch):
    """The D40 reality: some providers 400 tool-traffic-without-tools. The
    FIRST try is hermes' full history; the ONE fallback is text-only — the
    turn still ends with a real summary instead of dying on its farewell."""
    llm = _patch(
        monkeypatch,
        replies=[
            Exception("400 Tool messages found but no tools provided"),
            "Text-only summary of the work.",
        ],
    )
    out = cg.ai_node(_state(), _config())

    assert len(llm.calls) == 2
    first_types = [m.type for m in llm.calls[0][0]]
    assert "tool" in first_types, "first try carries the full history (hermes)"
    second_types = [m.type for m in llm.calls[1][0]]
    assert "tool" not in second_types, "fallback is text-only (D40)"
    assert out["messages"][0].content == "Text-only summary of the work."
    assert out["grace_done"] == 1


def test_second_lap_is_text_only_without_renudging(monkeypatch):
    """grace_done: hermes never sees a lap 2 (the summary RETURNS). Pulse's
    graph can route one more exhausted call — it must not re-append the
    request, and the D40 pairs-drop keeps it provider-legal."""
    llm = _patch(monkeypatch, replies=["lap2 wrap-up"])
    out = cg.ai_node(_state(grace_done=1), _config())

    sent = llm.calls[0][0]
    assert "tool" not in [m.type for m in sent], "lap-2 request is text-only"
    assert sent[-1].content != HERMES_VERBATIM, "no re-nudge on lap 2"
    assert out["messages"][0].content == "lap2 wrap-up"


def test_tool_call_text_in_summary_is_never_executed(monkeypatch):
    """The repair gate stays disarmed on the summary call: a hermes-trained
    model that emits a text tool_call in its farewell must not have it run."""
    farewell = (
        "Work done so far: explored the app.\n"
        "<tool_call>\nterminal\n<arg_key>command</arg_key>\n"
        "<arg_value>ls -la</arg_value>\n</tool_call>"
    )
    llm = _patch(monkeypatch, replies=[farewell])
    out = cg.ai_node(_state(), _config())
    assert out["messages"][0].content == farewell, "markup stays prose (hermes shows it raw)"
    assert not out["messages"][0].tool_calls


def test_model_wall_is_accounted_per_thread(monkeypatch):
    """Field 2026-09-09: wall=360.0s while logged model+tool time summed to
    ~92s and nothing could say where the rest went. Model-request wall is
    now accumulated per thread and the bridge receipt splits it."""
    import time as _time

    from src.graphs import chat_graph as cg

    class _SlowLLM:
        model = "m"
        def bind_tools(self, tools):
            return self
        def invoke(self, messages, **kwargs):
            _time.sleep(0.01)
            return AIMessage(content="ok")

    monkeypatch.setattr(cg, "_TURN_MODEL_WALL", {})
    cg._invoke_with_token_pump(_SlowLLM(), [], "acct-thread", "groq", "m")
    cg._invoke_with_token_pump(_SlowLLM(), [], "acct-thread", "groq", "m")
    assert cg.turn_model_wall("acct-thread") > 0.0
    assert cg.turn_model_wall("other-thread") == 0.0


def test_bridge_receipt_splits_model_vs_non_model_wall():
    from pathlib import Path

    bridge = (Path(__file__).resolve().parents[1] / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "turn_model_wall" in bridge
    assert "non-model" in bridge, "the receipt must name where non-model wall lives"


def test_bridge_receipt_reads_the_wall_with_the_real_thread_id():
    """Field 2026-09-09: the receipt read turn_model_wall(session_id) but the
    bridge scope names the thread `sid` — NameError, swallowed, and the log
    printed "model 0.0s" while the model visibly consumed minutes."""
    from pathlib import Path

    bridge = (Path(__file__).resolve().parents[1] / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "turn_model_wall(sid)" in bridge
    assert "turn_model_wall(session_id)" not in bridge


def test_grace_print_names_both_budget_legs_and_the_tripped_one():
    """Field 2026-09-09 x2: two turns ended in the grace after ~9-11 visible
    model calls while the print blamed "maximum iterations (30)" — one
    message covered BOTH legs (iterations and tokens), so nobody could tell
    what cut the run. The grace line now carries both counters and names the
    tripped leg: the next field log diagnoses itself."""
    from src.graphs.budget import _budget_trip_reason

    iters = _budget_trip_reason({"iteration_used": 30})
    assert "iterations 30/" in iters and "tripped: iterations" in iters

    tokens = _budget_trip_reason({
        "iteration_used": 9,
        "turn_token_usage": {"total_tokens": 121_000},
    })
    assert "iterations 9/" in tokens
    assert "tokens 121,000/" in tokens and "tripped: tokens" in tokens

    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "graphs" / "chat_graph.py").read_text(encoding="utf-8")
    assert "_budget_trip_reason(state)" in source, "the grace print must carry the diagnostics"
