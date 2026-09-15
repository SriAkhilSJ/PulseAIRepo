"""Live token streaming contracts (hermes discipline: words arrive as words).

Owner report: the panel sat on "Asking auto/best-chat..." for the whole
generation and then printed the answer at once -- the groq branch never set
streaming, and the graph only emitted one chunk per COMPLETED model call.
Three seams pinned here: the env getter, the agent-node pump, and the
duplicate-suppression flag.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def _no_memory(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setattr(chat_graph, "memory_manager", None)


# ---------------------------------------------------------------------------
# factory: streaming is env-driven with per-provider defaults
# ---------------------------------------------------------------------------

def test_streaming_env_getter(monkeypatch):
    from src.llm.factory import streaming_enabled

    monkeypatch.delenv("CRUSORAI_LLM_STREAMING", raising=False)
    assert streaming_enabled(default=True) is True
    assert streaming_enabled(default=False) is False
    monkeypatch.setenv("CRUSORAI_LLM_STREAMING", "off")
    assert streaming_enabled(default=True) is False
    monkeypatch.setenv("CRUSORAI_LLM_STREAMING", "1")
    assert streaming_enabled(default=False) is True
    monkeypatch.setenv("CRUSORAI_LLM_STREAMING", "garbage")
    assert streaming_enabled(default=True) is False


def test_groq_branch_streams_by_default_and_env_can_stop_it(monkeypatch):
    import src.llm.factory as factory

    monkeypatch.setattr(factory, "GROQ_API_KEY", "test-key")
    monkeypatch.delenv("CRUSORAI_LLM_STREAMING", raising=False)
    llm = factory.get_llm("groq", "test-model")
    assert getattr(llm._llm, "streaming", False) is True

    monkeypatch.setenv("CRUSORAI_LLM_STREAMING", "off")
    llm = factory.get_llm("groq", "test-model")
    assert getattr(llm._llm, "streaming", False) is False


def test_custom_branch_streams_by_default_and_env_can_stop_it(monkeypatch):
    """Owner deployment routes EVERY turn through the custom endpoint and
    their model streams fine -- custom now defaults ON like the first-class
    branches; CRUSORAI_LLM_STREAMING=off stays as the escape hatch."""
    import src.llm.factory as factory

    monkeypatch.setattr(factory, "CUSTOM_API_KEY", "test-key")
    monkeypatch.setattr(factory, "CUSTOM_BASE_URL", "http://localhost:9/v1")
    monkeypatch.delenv("CRUSORAI_LLM_STREAMING", raising=False)
    llm = factory.get_llm("custom", "test-model")
    assert getattr(llm._llm, "streaming", False) is True

    monkeypatch.setenv("CRUSORAI_LLM_STREAMING", "off")
    llm = factory.get_llm("custom", "test-model")
    assert getattr(llm._llm, "streaming", False) is False


# ---------------------------------------------------------------------------
# the agent-node pump: deltas reach the bus, the flag is recorded
# ---------------------------------------------------------------------------

def test_pump_emits_deltas_and_sets_flag(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    emitted = []
    monkeypatch.setattr(chat_graph, "event_bus", type(
        "Bus", (), {"emit": staticmethod(lambda kind, payload: emitted.append((kind, payload)))}
    )())

    pump = chat_graph._AgentTokenPump("thread-1")
    pump.on_llm_new_token("Hel")
    pump.on_llm_new_token("lo")
    pump.on_llm_new_token("")  # empty token: ignored

    assert pump.streamed is True
    assert [p for p, _ in emitted] == ["message.agent.chunk", "message.agent.chunk"]
    assert "".join(payload["chunk"] for _, payload in emitted) == "Hello"


def test_invoke_with_pump_records_whether_the_call_streamed(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    chat_graph._TURN_LAST_CALL_STREAMED.clear()

    class StreamingLLM:
        def invoke(self, messages, config=None):
            # simulate the provider firing tokens through the registered handler
            for handler in config["callbacks"]:
                handler.on_llm_new_token(" streamed ")
            return "ok"

    class SilentLLM:
        def invoke(self, messages, config=None):
            return "ok"

    out = chat_graph._invoke_with_token_pump(StreamingLLM(), [], "t1")
    assert out == "ok"
    assert chat_graph._TURN_LAST_CALL_STREAMED["t1"] is True

    chat_graph._invoke_with_token_pump(SilentLLM(), [], "t2")
    assert chat_graph._TURN_LAST_CALL_STREAMED["t2"] is False


def test_invoke_with_pump_logs_a_response_receipt(capsys, monkeypatch):
    """Owner run 2026-09-04: a 2:08 "Waiting on the model" spinner had no
    telemetry — silence vs slow endpoint vs tokens-rendered-nowhere were
    indistinguishable. Every agent call now prints ONE receipt: wall time,
    first-token latency, chunk count (or an explicit non-streaming mark)."""
    import src.graphs.chat_graph as chat_graph

    chat_graph._TURN_LAST_CALL_STREAMED.clear()

    class StreamingLLM:
        def invoke(self, messages, config=None):
            for handler in config["callbacks"]:
                handler.on_llm_new_token("Hel")
                handler.on_llm_new_token("lo")
            return "ok"

    class SilentLLM:
        def invoke(self, messages, config=None):
            return "ok"

    chat_graph._invoke_with_token_pump(
        StreamingLLM(), [], "t1", provider="custom", model="auto/best-chat"
    )
    out = capsys.readouterr().out
    line = [ln for ln in out.splitlines() if "answered in" in ln]
    assert len(line) == 1, out
    assert "custom/auto/best-chat" in line[0]
    assert "first token" in line[0] and "2 chunks streamed" in line[0]
    assert "buffered" not in line[0], "two real chunks is a stream"

    # a pseudo-stream: one giant chunk after a long silence — the endpoint
    # buffered the whole generation (owner run 2026-09-04: "first token
    # 8.1s, 1 chunks streamed"). The receipt must name it.
    class BufferedLLM:
        def invoke(self, messages, config=None):
            for handler in config["callbacks"]:
                handler.on_llm_new_token("x" * 500)
            return "ok"

    chat_graph._invoke_with_token_pump(BufferedLLM(), [], "t4")
    out_b = capsys.readouterr().out
    assert "1 chunks streamed" in out_b and "buffered" in out_b, out_b

    chat_graph._invoke_with_token_pump(SilentLLM(), [], "t2", provider="custom", model="m")
    out2 = capsys.readouterr().out
    assert "non-streaming response" in out2, out2
    # exceptions still record the streamed flag before propagating
    class BoomLLM:
        def invoke(self, messages, config=None):
            for handler in config["callbacks"]:
                handler.on_llm_new_token("partial")
            raise RuntimeError("endpoint died mid-stream")

    try:
        chat_graph._invoke_with_token_pump(BoomLLM(), [], "t3")
    except RuntimeError:
        pass
    assert chat_graph._TURN_LAST_CALL_STREAMED["t3"] is True


def test_invoke_with_pump_survives_config_rejection(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    chat_graph._TURN_LAST_CALL_STREAMED.clear()

    class OldLLM:
        def invoke(self, messages):
            return "fine"

    assert chat_graph._invoke_with_token_pump(OldLLM(), [], "t3") == "fine"
    assert chat_graph._TURN_LAST_CALL_STREAMED["t3"] is False


def test_chat_turn_still_stamps_nothing_with_streaming_flag_present(_no_memory):
    """The suppression flag must not disturb the finalize chat-turn contract."""
    from langchain_core.messages import AIMessage, HumanMessage

    import src.graphs.chat_graph as chat_graph

    chat_graph._TURN_LAST_CALL_STREAMED["default"] = True
    state = {
        "messages": [HumanMessage("hi"), AIMessage("Hello!")],
        "current_task": "hi",
        "steps_completed": [],
        "failed_steps": [],
        "plan": [],
    }
    out = chat_graph.finalize_node(dict(state), {"configurable": {}})
    assert out["messages"] == []


def test_buffered_answer_is_flushed_to_the_transcript():
    """Field 2026-09-06: a 14s answer painted NOTHING — the endpoint buffered
    the whole completion, zero token events fired, and text reaches the UI
    only via chunk frames. Hermes' transport discipline: the transcript must
    show the answer regardless of delivery mode."""
    from langchain_core.messages import AIMessage

    from src.graphs import chat_graph as cg

    events: list[tuple[str, dict]] = []
    original = cg.event_bus.emit
    cg.event_bus.emit = lambda kind, payload=None: (
        events.append((kind, payload or {})), original(kind, payload))[1]
    try:
        pump = cg._AgentTokenPump("flush-t")
        result = AIMessage(content="Here are your files: index.html, src/")
        assert cg._flush_unstreamed_answer(pump, result, "flush-t") is True
        chunks = [p for kind, p in events if kind == "message.agent.chunk"]
        assert chunks == [{"chunk": "Here are your files: index.html, src/", "thread_id": "flush-t"}]
    finally:
        cg.event_bus.emit = original


def test_streamed_answer_is_never_flushed_twice():
    """Any streamed answer text disables the flush — no duplicated transcript."""
    from langchain_core.messages import AIMessage

    from src.graphs import chat_graph as cg

    events: list[tuple[str, dict]] = []
    original = cg.event_bus.emit
    cg.event_bus.emit = lambda kind, payload=None: (
        events.append((kind, payload or {})), original(kind, payload))[1]
    try:
        pump = cg._AgentTokenPump("stream-t")
        for piece in ("Here ", "are ", "your files."):
            pump.on_llm_new_token(piece)
        result = AIMessage(content="Here are your files.")
        assert cg._flush_unstreamed_answer(pump, result, "stream-t") is False
        assert len([p for kind, p in events if kind == "message.agent.chunk"]) == 3
    finally:
        cg.event_bus.emit = original


def test_reasoning_only_stream_still_flushes_the_answer():
    """A reasoning-content stream with a buffered answer must flush the text:
    the transcript paints the ANSWER, not just the Thinking block."""
    from langchain_core.messages import AIMessage

    from src.graphs import chat_graph as cg

    class _Chunk:
        additional_kwargs = {"reasoning_content": "thinking..."}

    events: list[tuple[str, dict]] = []
    original = cg.event_bus.emit
    cg.event_bus.emit = lambda kind, payload=None: (
        events.append((kind, payload or {})), original(kind, payload))[1]
    try:
        pump = cg._AgentTokenPump("reasoning-t")
        pump.on_llm_new_token("", chunk=_Chunk())
        assert pump.text_chars == 0, "reasoning must not count as answer text"
        result = AIMessage(content="The actual answer.")
        assert cg._flush_unstreamed_answer(pump, result, "reasoning-t") is True
        chunks = [p for kind, p in events if kind == "message.agent.chunk"]
        assert chunks and chunks[0]["chunk"] == "The actual answer."
    finally:
        cg.event_bus.emit = original


def test_pump_flush_and_stream_loop_fallback_do_not_double_paint():
    """Hermes-port parity check: hermes ends EVERY turn with one authoritative
    message.complete; our equivalent end is turn_done.message fed by
    final_response. The pump-level flush (buffered endpoint) and the
    stream-loop fallback are two paths to that ONE text — the flush marks the
    call delivered, so the fallback must stay silent (no double paint)."""
    from langchain_core.messages import AIMessage

    from src.graphs import chat_graph as cg

    events: list[tuple[str, dict]] = []
    original = cg.event_bus.emit
    cg.event_bus.emit = lambda kind, payload=None: (
        events.append((kind, payload or {})), original(kind, payload))[1]
    try:
        class BufferedLLM:
            model = "buffered"

            def invoke(self, messages, config=None):
                return AIMessage(content="The buffered answer.")

        result = cg._invoke_with_token_pump(BufferedLLM(), [], "dup-t", "test", "buffered")
        assert result.content == "The buffered answer."
        # the flush marks the call delivered (the exact flag the stream loop reads)
        assert cg._TURN_LAST_CALL_STREAMED.get("dup-t") is True
        chunks = [p for kind, p in events if kind == "message.agent.chunk"]
        assert chunks == [{"chunk": "The buffered answer.", "thread_id": "dup-t"}]
    finally:
        cg.event_bus.emit = original


def test_content_block_answers_normalize_to_clean_text():
    """A provider answering in content BLOCKS must not leak a list onto the
    wire: the fallback chunk and turn_done.message carry clean text only
    (hermes message.complete payload["text"] is always a string)."""
    from langchain_core.messages import AIMessage

    from src.graphs import chat_graph as cg

    events: list[tuple[str, dict]] = []
    original = cg.event_bus.emit
    cg.event_bus.emit = lambda kind, payload=None: (
        events.append((kind, payload or {})), original(kind, payload))[1]
    try:
        message = AIMessage(content=[
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "from blocks."},
        ])
        assert cg._result_answer_text(message) == "Hello from blocks."
        # the stream-loop fallback path uses the same normalization
        assert isinstance(cg._result_answer_text(message), str)
    finally:
        cg.event_bus.emit = original
