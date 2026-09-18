"""The hermes repetition guard, ported and wired.

hermes agent/repetition_guard.py (issue #86581): a model in a degenerate
repetition loop can spend its ENTIRE output budget echoing one fragment; a
length continuation then stitches it into the final response (hermes
incident: a 60k-char turn delivered as 31 Discord messages). The guard
detects repetition-dominated fragments BEFORE the continuation nudge so the
turn aborts with a clear error.

Field 2026-09-10 (owner, desktop, custom/auto/best-chat): a degenerate
salad turn streamed into the panel at full length and the run ended
"unverified" — Crusor had NO such guard, and its own finish-gate nudge would
have asked the melting model to CONTINUE. This pins: the verbatim-repeat
law (hermes constants), Crusor's documented word-loop extension, the ai_node
discard (history keeps the notice, never the slop), the router ending the
turn, and the finish gate refusing to nudge a discarded fragment.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from src.llm.repetition_guard import (
    MIN_FRAGMENT_LENGTH,
    REPETITION_DOMINATED_NOTICE,
    is_degenerate_output,
    is_repetition_dominated,
    is_word_looped,
)


def _echo_slop() -> str:
    """hermes' canonical shape: one long verbatim window repeating."""
    return ("the build step repeats this exact fragment forever " * 10)


def _field_slop() -> str:
    """The owner's field incident shape (2026-09-10): word-anchored salad —
    'continue'-family filling thousands of chars with NO long verbatim
    window, which is why the verbatim check alone cannot cover it."""
    lines = []
    for i in range(30):
        lines.append(
            f"continue is continues continue continued are continue , are continue "
            f"continue's continue {i} , continue are are continue continuev continued"
        )
    return "\n".join(lines)


_NORMAL_PROSE = (
    "The build fails during prerendering because the homepage imports a client "
    "component that calls useRef at module evaluation time. Next.js tries to "
    "prerender the client component tree on the server, and React hooks require "
    "a render tree to exist. The fix is to mark the route dynamic so the "
    "prerender pass skips it, or to move the hook usage behind an effect. Both "
    "approaches keep the client boundary intact while the export succeeds. "
    "After rebuilding, the error page for the not-found route should compile "
    "without the document import that the pages router owns."
) * 2


# ── hermes verbatim-repeat law ───────────────────────────────────────────────


def test_verbatim_repeat_window_detected():
    assert is_repetition_dominated(_echo_slop()) is True


def test_short_fragment_fails_open():
    assert len("x" * 300) < MIN_FRAGMENT_LENGTH
    assert is_repetition_dominated("x" * 300) is False


def test_normal_prose_and_code_not_flagged():
    assert is_repetition_dominated(_NORMAL_PROSE) is False
    # Varied, realistic source: a verbatim-repeated block WOULD flag (that is
    # hermes' law — an echoed block is a loop); real code never looks like one.
    code = (
        "function update() {\n  setCount(count + 1);\n  render(count);\n}\n"
        "function reset() {\n  setCount(0);\n  render(0);\n}\n"
        "export default function Counter() {\n  const [count, setCount] = useState(0);\n"
        "  return <button onClick={update}>{count}</button>;\n}\n"
        "type Props = { start?: number; label?: string; onDone?: () => void };\n"
        "const styles = { button: 'rounded px-2 py-1', panel: 'mt-2 border p-2' };\n"
        "async function save(value: number) {\n  await fetch('/api/count', { method: 'POST', body: String(value) });\n"
        "}\n"
    ) * 3
    assert len(code) >= MIN_FRAGMENT_LENGTH
    assert is_repetition_dominated(code) is False
    assert is_word_looped(code) is False


def test_multilingual_solo_word_salad_without_verbatim_window_passes_verbatim_check():
    """The honest boundary: hermes' verbatim check alone does NOT trip on the
    field slop (varying text, no long verbatim window) — which is exactly why
    the word-loop extension exists."""
    slop = _field_slop()
    assert is_repetition_dominated(slop) is False


# ── Crusor word-loop extension ────────────────────────────────────────────────


def test_word_loop_extension_catches_field_slop():
    slop = _field_slop()
    assert len(slop) >= 1500
    assert is_word_looped(slop) is True
    assert is_degenerate_output(slop) is True


def test_word_loop_disabled_by_env(monkeypatch):
    monkeypatch.setenv("CRUSORAI_WORD_LOOP_SHARE", "0")
    assert is_word_looped(_field_slop()) is False


def test_legit_repeated_word_never_flags():
    text = (_NORMAL_PROSE + " The verification receipt is the proof. ") * 8
    assert is_word_looped(text) is False


# ── ai_node: the discard ─────────────────────────────────────────────────────


def _state(thread):
    return {
        "messages": [], "current_task": "fix test5 build",
        "token_usage": {}, "turn_token_usage": {},
        "execution_trace": [], "plan": [], "incomplete_response_retries": 0,
        "grace_done": 0, "finish_nudges": 0, "verify_nudges": 0,
        "workspace": "/nonexistent",
    }


def _config(thread):
    return {"configurable": {"workspace": "/nonexistent", "thread_id": thread,
                             "execution_mode": "agent"}}


class _FakeEngine:
    def build_ai_messages(self, state, system_message):
        from langchain_core.messages import SystemMessage
        return [SystemMessage(content="PERSONA"), SystemMessage(content="LAYER")]


def _patch_provider(monkeypatch, replied):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "10")

    class _FakeLLM:
        model = "m"
        def bind_tools(self, tools):
            return self
        def invoke(self, messages, **kw):
            return replied

    import src.graphs.chat_graph as cg
    monkeypatch.setattr(cg, "get_llm", lambda provider, model, reasoning_config=None, **kw: _FakeLLM())
    monkeypatch.setattr(cg, "get_context_engine", lambda config: _FakeEngine())
    monkeypatch.setattr(cg.cost_router, "route", lambda t, p: ("groq", "m"))


def _length_cut(content):
    msg = AIMessage(content=content)
    msg.response_metadata = {"finish_reason": "length"}
    msg.usage_metadata = {"input_tokens": 900, "output_tokens": 800}
    return msg


def test_ai_node_discards_repetition_dominated_partial(monkeypatch, capsys):
    _patch_provider(monkeypatch, _length_cut(_echo_slop()))
    import src.graphs.chat_graph as cg

    out = cg.ai_node(_state("rep-t"), _config("rep-t"))
    final = out["messages"][0]
    assert final.content == REPETITION_DOMINATED_NOTICE
    assert final.additional_kwargs["crusor_repetition_dominated"] is True
    assert final.additional_kwargs["crusor_incomplete_response"] is True
    assert out["incomplete_response_retries"] == 1
    assert "repetition-dominated output (finish_reason=length)" in capsys.readouterr().out


def test_ai_node_keeps_normal_length_cut_intact(monkeypatch, capsys):
    long_normal = _NORMAL_PROSE * 3  # > MIN_FRAGMENT_LENGTH, no dominance
    _patch_provider(monkeypatch, _length_cut(long_normal))
    import src.graphs.chat_graph as cg

    out = cg.ai_node(_state("rep-k"), _config("rep-k"))
    final = out["messages"][0]
    assert final.content == long_normal
    assert final.additional_kwargs["crusor_incomplete_response"] is True
    assert "crusor_repetition_dominated" not in final.additional_kwargs
    assert "repetition-dominated" not in capsys.readouterr().out


def test_ai_node_stop_ended_slop_is_untouched_but_logged(monkeypatch, capsys):
    slop = _field_slop()
    msg = AIMessage(content=slop)
    msg.response_metadata = {"finish_reason": "stop"}
    msg.usage_metadata = {"input_tokens": 900, "output_tokens": 800}
    _patch_provider(monkeypatch, msg)
    import src.graphs.chat_graph as cg

    out = cg.ai_node(_state("rep-s"), _config("rep-s"))
    final = out["messages"][0]
    assert final.content == slop  # behavior scope stays hermes-verbatim
    assert "crusor_repetition_dominated" not in final.additional_kwargs
    assert "stop-ended response (informational)" in capsys.readouterr().out


# ── router + finish gate: a discarded fragment ends the turn ─────────────────


def test_router_finalizes_repetition_dominated_fragment():
    from src.graphs.gates import should_continue

    msg = AIMessage(
        content=REPETITION_DOMINATED_NOTICE,
        additional_kwargs={"crusor_incomplete_response": True,
                           "crusor_repetition_dominated": True},
    )
    state = {"messages": [msg], "incomplete_response_retries": 1}
    assert should_continue(state) == "finalize"


def test_finish_gate_never_nudges_a_discarded_fragment():
    from src.graphs.gates import finish_gate_node

    msg = AIMessage(
        content=REPETITION_DOMINATED_NOTICE,
        additional_kwargs={"crusor_incomplete_response": True,
                           "crusor_repetition_dominated": True},
    )
    out = finish_gate_node({"messages": [msg]})
    assert out == {}
