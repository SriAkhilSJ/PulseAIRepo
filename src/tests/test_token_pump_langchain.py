"""LangChain handler contract for the token pump (owner desktop regression).

At f414aa02 the pump was a duck-typed object; LangChain's callback manager
reads ``handler.run_inline`` on every registered handler, so EVERY agent
call died with AttributeError and burned 5 retries: "no streaming" was one
attribute away. Pinned here: the pump IS a BaseCallbackHandler, opts into
inline (ordered) delivery, survives the REAL manager paths, and extracts
text from chunk-shaped tokens.
"""
from __future__ import annotations

import uuid


def test_pump_is_a_real_langchain_handler():
    from langchain_core.callbacks import BaseCallbackHandler

    from src.graphs.chat_graph import _AgentTokenPump

    pump = _AgentTokenPump("t")
    assert isinstance(pump, BaseCallbackHandler)
    # ordered delivery: without this the manager dispatches each token
    # through run_in_executor(copy_context().run, ...) and chunks race.
    assert pump.run_inline is True


def test_pump_survives_real_callback_manager(monkeypatch):
    """The exact crash path: manager.on_llm_start filters handlers by
    run_inline and dispatches events -- a duck-typed pump raised
    AttributeError before a single token could flow."""
    from langchain_core.callbacks import CallbackManager

    import src.graphs.chat_graph as chat_graph

    emitted = []
    monkeypatch.setattr(chat_graph, "event_bus", type(
        "Bus", (), {"emit": staticmethod(lambda kind, payload: emitted.append((kind, payload)))}
    )())

    pump = chat_graph._AgentTokenPump("t1")
    manager = CallbackManager([pump])
    runs = manager.on_llm_start(
        serialized={}, prompts=["hi"], run_id=uuid.uuid4()
    )
    for run in runs:
        run.on_llm_new_token("Hel")
        run.on_llm_new_token("lo")

    assert pump.streamed is True
    assert "".join(p["chunk"] for k, p in emitted if k == "message.agent.chunk") == "Hello"


def test_pump_extracts_text_from_chunk_shaped_tokens(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    emitted = []
    monkeypatch.setattr(chat_graph, "event_bus", type(
        "Bus", (), {"emit": staticmethod(lambda kind, payload: emitted.append((kind, payload)))}
    )())

    pump = chat_graph._AgentTokenPump("t2")

    class Chunk:  # GenerationChunk stand-in: carries .text, not a str
        text = " chunked "

    pump.on_llm_new_token(Chunk())
    pump.on_llm_new_token(None)
    assert [p["chunk"] for _, p in emitted] == [" chunked "]


def test_async_manager_path_also_accepts_the_pump():
    """manager.py line ~416 reads handler.run_inline on the async path too."""
    from langchain_core.callbacks import AsyncCallbackManager

    from src.graphs.chat_graph import _AgentTokenPump

    manager = AsyncCallbackManager([_AgentTokenPump("t3")])
    assert manager.handlers and manager.handlers[0].run_inline is True
