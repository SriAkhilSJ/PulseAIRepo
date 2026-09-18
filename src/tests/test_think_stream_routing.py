"""Regression tests: inline <think>…</think> routing in the agent token pump.

Field 2026-09-17: deepseek-v4-flash (custom lane) streams reasoning INLINE in
content (`<think>…</think>` before the answer) — no reasoning_content chunks —
so the Thinking card never painted and the thought polluted the transcript.
"""

import pytest

from src.graphs import chat_graph


class _BusSpy:
    """Capture event_bus emissions without touching engine wiring."""

    def __init__(self):
        self.reasoning = []
        self.text = []
        self._orig = chat_graph.event_bus.emit

    def __enter__(self):
        def spy(evt, data):
            if evt == "reasoning.update":
                self.reasoning.append(data["text"])
            elif evt == "message.agent.chunk":
                self.text.append(data["chunk"])
            return self._orig(evt, data)
        chat_graph.event_bus.emit = spy
        return self

    def __exit__(self, *exc):
        chat_graph.event_bus.emit = self._orig
        return False


def _stream(pieces, strip=False):
    pump = chat_graph._AgentTokenPump("t", strip_tool_blocks=strip)
    with _BusSpy() as spy:
        for p in pieces:
            pump.on_llm_new_token(p)
        pump.flush_tail()
    return spy, pump


def test_split_think_tag_across_chunks_routes_to_reasoning():
    spy, pump = _stream(["<th", "ink>Plan first.</think>\n\nAnswer body", " continues."])
    assert "".join(spy.reasoning).strip() == "Plan first."
    assert "".join(spy.text) == "Answer body continues."
    assert pump._think_seen


def test_plain_answer_without_think_is_untouched():
    spy, pump = _stream(["Hello", " world"])
    assert spy.reasoning == []
    assert "".join(spy.text) == "Hello world"
    assert not pump._think_seen


def test_unterminated_think_flushes_as_reasoning_never_answer():
    spy, _ = _stream(["<think>Still thinking", " forever"])
    # Reasoning frames REPLACE (cumulative text) — the last frame is the truth.
    assert spy.reasoning[-1].strip() == "Still thinking forever"
    assert "".join(spy.text) == ""


def test_think_after_answer_prefix():
    spy, _ = _stream(["First answer.<think>hmm</think>Then more."])
    assert "".join(spy.text) == "First answer.Then more."
    assert "".join(spy.reasoning).strip() == "hmm"


def test_think_routing_coexists_with_tool_block_strip():
    spy, _ = _stream(
        ['<think>why</think>Pick <tool_call>{"x":1}</tool_call> the tool.'],
        strip=True,
    )
    assert "".join(spy.reasoning).strip() == "why"
    joined = "".join(spy.text)
    assert "<tool_call>" not in joined
    assert "Pick" in joined and "the tool." in joined


def test_reasoning_content_chunks_still_forward_cumulatively():
    pump = chat_graph._AgentTokenPump("t2")

    class Chunk:
        def __init__(self, extra):
            self.additional_kwargs = extra

    with _BusSpy() as spy:
        pump.on_llm_new_token("", chunk=Chunk({"reasoning_content": "part one"}))
        pump.on_llm_new_token("", chunk=Chunk({"reasoning_content": "part one + two"}))
    assert spy.reasoning == ["part one", "part one + two"]


def test_result_reasoning_text_extracts_inline_think_from_buffered_content():
    class Msg:
        content = "<think>buffered thought</think>The reply."

    assert chat_graph._result_reasoning_text(Msg()) == "buffered thought"


def test_result_reasoning_text_prefers_reasoning_content_field():
    class Msg:
        content = "<think>inline</think>The reply."
        additional_kwargs = {"reasoning_content": "field thought"}

    assert chat_graph._result_reasoning_text(Msg()) == "field thought"


def test_flush_unstreamed_answer_strips_think_markup():
    class Msg:
        content = "<think>secret plan</think>Visible reply."

    pump = chat_graph._AgentTokenPump("t3")
    with _BusSpy() as spy:
        assert chat_graph._flush_unstreamed_answer(pump, Msg(), "t3") is True
    assert spy.text == ["Visible reply."]


def test_flush_unstreamed_reasoning_emits_accumulated_text():
    class Msg:
        content = "<think>whole thought</think>Reply."

    with _BusSpy() as spy:
        assert chat_graph._flush_unstreamed_reasoning(Msg(), "t4") is True
    assert spy.reasoning == ["whole thought"]
