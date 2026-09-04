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

    monkeypatch.delenv("PULSEAI_LLM_STREAMING", raising=False)
    assert streaming_enabled(default=True) is True
    assert streaming_enabled(default=False) is False
    monkeypatch.setenv("PULSEAI_LLM_STREAMING", "off")
    assert streaming_enabled(default=True) is False
    monkeypatch.setenv("PULSEAI_LLM_STREAMING", "1")
    assert streaming_enabled(default=False) is True
    monkeypatch.setenv("PULSEAI_LLM_STREAMING", "garbage")
    assert streaming_enabled(default=True) is False


def test_groq_branch_streams_by_default_and_env_can_stop_it(monkeypatch):
    import src.llm.factory as factory

    monkeypatch.setattr(factory, "GROQ_API_KEY", "test-key")
    monkeypatch.delenv("PULSEAI_LLM_STREAMING", raising=False)
    llm = factory.get_llm("groq", "test-model")
    assert getattr(llm._llm, "streaming", False) is True

    monkeypatch.setenv("PULSEAI_LLM_STREAMING", "off")
    llm = factory.get_llm("groq", "test-model")
    assert getattr(llm._llm, "streaming", False) is False


def test_custom_branch_streams_by_default_and_env_can_stop_it(monkeypatch):
    """Owner deployment routes EVERY turn through the custom endpoint and
    their model streams fine -- custom now defaults ON like the first-class
    branches; PULSEAI_LLM_STREAMING=off stays as the escape hatch."""
    import src.llm.factory as factory

    monkeypatch.setattr(factory, "CUSTOM_API_KEY", "test-key")
    monkeypatch.setattr(factory, "CUSTOM_BASE_URL", "http://localhost:9/v1")
    monkeypatch.delenv("PULSEAI_LLM_STREAMING", raising=False)
    llm = factory.get_llm("custom", "test-model")
    assert getattr(llm._llm, "streaming", False) is True

    monkeypatch.setenv("PULSEAI_LLM_STREAMING", "off")
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
