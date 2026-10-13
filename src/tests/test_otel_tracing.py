"""Tests for the OTel tracing layer (CRUSORAI_OTEL) — hermes langfuse parity.

Unit tests use an in-memory exporter (no network). The integration test runs
a REAL scripted turn through the graph (stub model inside the real
RetryLLMProxy) and asserts the full span tree: turn -> node -> llm / tool.
"""
from __future__ import annotations

import uuid

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

try:  # spelling changed between otel releases
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
except ImportError:  # pragma: no cover
    from opentelemetry.sdk.trace.export.in_memory_span_exportor import (
        InMemorySpanExporter,
    )

from src.runtime import otel_tracing


@pytest.fixture()
def otel_env(monkeypatch):
    """OTel ON + in-memory exporter; provider reset afterwards."""
    monkeypatch.setenv("CRUSORAI_OTEL", "on")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_tracing.configure_provider(provider)
    yield exporter
    otel_tracing.configure_provider(None)
    otel_tracing._turn_spans.clear()


def _attrs(span) -> dict:
    return dict(span.attributes or {})


def test_disabled_tracer_is_none(monkeypatch):
    monkeypatch.delenv("CRUSORAI_OTEL", raising=False)
    otel_tracing.configure_provider(None)
    assert otel_tracing.tracer() is None
    assert otel_tracing.tool_span_start("bash", {"cmd": "ls"}) is None
    # pass-through behavior
    fn = otel_tracing.traced_node("demo", lambda state: 42)
    assert fn(None) == 42


def test_turn_span_lifecycle(otel_env):
    otel_tracing.on_turn_begin("sess-1")
    otel_tracing.on_turn_end("sess-1")
    spans = otel_env.get_finished_spans()
    assert [s.name for s in spans] == ["turn sess-1"]
    assert _attrs(spans[0])["session.id"] == "sess-1"
    # unknown session end is a no-op
    otel_tracing.on_turn_end("never-begun")


def test_turn_span_is_current_context(otel_env):
    """Child spans opened on the turn thread must nest under the turn root."""
    otel_tracing.on_turn_begin("sess-2")
    t = otel_tracing.tracer()
    child = t.start_span("child-op")
    child.end()
    otel_tracing.on_turn_end("sess-2")
    spans = otel_env.get_finished_spans()
    by_name = {s.name: s for s in spans}
    parent = by_name["child-op"].parent
    assert parent is not None
    assert parent.span_id == by_name["turn sess-2"].context.span_id


def test_traced_node_span_and_exception(otel_env):
    ok = otel_tracing.traced_node("demo", lambda state: "value")
    assert ok(None) == "value"
    spans = otel_env.get_finished_spans()
    assert [s.name for s in spans] == ["node demo"]

    def boom(state=None):
        raise ValueError("x")

    wrapped = otel_tracing.traced_node("boomer", boom)
    with pytest.raises(ValueError):
        wrapped(None)
    names = [s.name for s in otel_env.get_finished_spans()]
    assert "node boomer" in names  # span ended even on exception


def test_tool_span_status_and_error(otel_env):
    span = otel_tracing.tool_span_start("bash", {"cmd": "ls"})
    otel_tracing.tool_span_end(span, status="ok")
    err_span = otel_tracing.tool_span_start("bash", {"cmd": "rm"})
    otel_tracing.tool_span_end(err_span, status="error")
    exc_span = otel_tracing.tool_span_start("bash", {"cmd": "x"})
    otel_tracing.tool_span_end(exc_span, error=RuntimeError("kaput"))
    spans = otel_env.get_finished_spans()
    assert all(_attrs(s)["gen_ai.tool.name"] == "bash" for s in spans)
    assert all(_attrs(s)["gen_ai.operation.name"] == "execute_tool" for s in spans)
    from opentelemetry.trace import StatusCode

    statuses = {id(s.context.span_id): s.status.status_code for s in spans}
    assert statuses[id(exc_span.context.span_id)] == StatusCode.ERROR
    assert statuses[id(err_span.context.span_id)] == StatusCode.ERROR
    # None span is a safe no-op
    otel_tracing.tool_span_end(None, status="ok")


def test_traced_llm_invoke_usage_and_error(otel_env):
    class Inner:
        pass

    class FakeSelf:
        model = "test-model"
        _llm = Inner()

    class Resp:
        usage_metadata = {"input_tokens": 10, "output_tokens": 5}

    orig = lambda self, *a, **k: Resp()  # noqa: E731
    wrapped = otel_tracing.traced_llm_invoke(orig)
    out = wrapped(FakeSelf(), ["msg"])
    assert isinstance(out, Resp)
    spans = otel_env.get_finished_spans()
    assert [s.name for s in spans] == ["llm test-model"]
    attrs = _attrs(spans[0])
    assert attrs["gen_ai.request.model"] == "test-model"
    assert attrs["gen_ai.usage.input_tokens"] == 10
    assert attrs["gen_ai.usage.output_tokens"] == 5

    def failing(self, *a, **k):
        raise RuntimeError("boom")

    wrapped_bad = otel_tracing.traced_llm_invoke(failing)
    with pytest.raises(RuntimeError):
        wrapped_bad(FakeSelf())
    assert "llm test-model" in [s.name for s in otel_env.get_finished_spans()]


# ------------------------------------------------------------------ real turn

def _stub_factory():
    """A scripted model + a kwargs-binding shim, compatible with the real
    RetryLLMProxy (bind_tools -> .kwargs['tools'] visible to the sanitizer)."""
    from langchain_core.messages import AIMessage

    SCRIPT = [("write_file", {"path": "hello.py", "content": "print('hi')\n"})]

    class _Binding:
        def __init__(self, model, tools):
            self.kwargs = {
                "tools": [
                    {"type": "function", "function": {"name": t.name, "parameters": {}}}
                    for t in tools
                ]
            }
            self.model = model.model
            self._model = model

        def invoke(self, messages, **kw):
            return self._model.invoke(messages, **kw)

        # The proxy re-binds the bound view (bind_generation etc.); a no-op
        # bind keeps the stub shape stable.
        def bind(self, **kw):
            return self

        def bind_tools(self, tools, **kw):
            return self

    class StubModel:
        model = "otel-stub"

        def __init__(self):
            self._tools = None

        def bind_tools(self, tools, **kw):
            self._tools = {t.name for t in tools}
            return _Binding(self, tools)

        def bind(self, **kw):
            return self

        def invoke(self, messages, **kw):
            n = sum(1 for m in messages if getattr(m, "type", "") == "tool")
            if n >= len(SCRIPT):
                return AIMessage(content="Done. hello.py created.")
            name, args = SCRIPT[n]
            return AIMessage(
                content="",
                tool_calls=[{"name": name, "args": args, "id": f"c{n}", "type": "tool_call"}],
            )

    return StubModel()  # an INSTANCE: the proxy forwards calls to self._llm


def _drop_checkpoints(thread_id: str) -> None:
    """Remove a thread's checkpoint rows from the shared sessions DB (best
    effort; the graph's SqliteSaver is bound to ~/.crusorai at import time)."""
    try:
        import os
        import sqlite3

        db = os.path.join(os.path.expanduser("~"), ".crusorai", "sessions.db")
        if not os.path.exists(db):
            return
        conn = sqlite3.connect(db, timeout=5)
        try:
            conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # test hygiene only — never fail the test over it


def test_real_turn_produces_trace_tree(tmp_path, monkeypatch, otel_env):
    """End-to-end: a scripted turn through the REAL graph + real
    RetryLLMProxy + real tool middleware -> full span tree."""
    pytest.importorskip("langgraph")
    monkeypatch.setenv("CRUSORAI_MEMORY", "off")
    monkeypatch.delenv("CRUSORAI_OBSERVABILITY", raising=False)

    # Isolate the runtime services (journal etc.) to a temp home.
    from src.runtime import factory

    monkeypatch.setattr(factory, "_default", factory.create_runtime_services(tmp_path))

    from langchain_core.messages import HumanMessage
    from src.graphs import chat_graph
    from src.llm.factory import RetryLLMProxy
    from src.runtime.turn_control import set_active_session, turn_controls

    monkeypatch.setattr(chat_graph, "get_llm", lambda **kw: RetryLLMProxy(_stub_factory()))

    ws = tmp_path / "ws"
    ws.mkdir()
    # UNIQUE thread id: the graph's SqliteSaver persists to the shared
    # ~/.crusorai/sessions.db at import time — a fixed id would resume a
    # stale checkpoint from an earlier run and loop on its state.
    thread = f"otel-trace-test-{uuid.uuid4().hex[:8]}"
    config = {
        "configurable": {
            "thread_id": thread,
            "provider": "custom",
            "model": "otel-stub",
            "workspace": str(ws),
            "approval_policy": "workspace_session",
            "turn_id": f"turn-{thread}",
        },
        "recursion_limit": 60,
    }
    state = {
        "messages": [HumanMessage(content="Create hello.py that prints hi. That's all.")],
        "latest_instruction": "Create hello.py that prints hi. That's all.",
        "execution_mode": "agent",
        "iteration_used": 0,
        "grace_done": 0,
        "budget_warning_done": 0,
        "incomplete_response_retries": 0,
        "plan_wrap_nudges": 0,
        "wrap_summary": 0,
        "turn_token_usage": chat_graph._zero_token_usage(),
    }
    turn_controls.begin(thread)
    set_active_session(thread)
    try:
        result = chat_graph.graph.invoke(state, config=config)
    finally:
        turn_controls.end(thread)
        set_active_session(None)  # unbind the thread-local
        # Best-effort: drop this run's checkpoint rows so repeated test runs
        # don't accumulate in the shared ~/.crusorai/sessions.db.
        _drop_checkpoints(thread)
    assert (ws / "hello.py").exists(), "the real tool must have written the file"

    spans = otel_env.get_finished_spans()
    names = [s.name for s in spans]
    by_name = {s.name: s for s in spans}

    # 1. the turn root
    assert f"turn {thread}" in names
    turn_span = by_name[f"turn {thread}"]
    assert _attrs(turn_span)["session.id"] == thread

    # 2. graph-node spans nested under the turn
    assert "node ai" in names
    assert "node finalize" in names
    for node_name in ("node ai", "node finalize"):
        parent = by_name[node_name].parent
        assert parent is not None
        assert parent.span_id == turn_span.context.span_id

    # 3. an LLM generation span (through the real RetryLLMProxy)
    llm_spans = [s for s in spans if s.name.startswith("llm ")]
    assert llm_spans, f"no llm span in {names}"
    llm_span = llm_spans[0]
    assert _attrs(llm_span).get("gen_ai.request.model") == "otel-stub"
    assert _attrs(llm_span).get("gen_ai.operation.name") == "chat"

    # 4. a tool span with the tool name, nested under the turn
    assert "tool write_file" in names
    tool_span = by_name["tool write_file"]
    assert _attrs(tool_span)["gen_ai.tool.name"] == "write_file"
    assert _attrs(tool_span)["gen_ai.operation.name"] == "execute_tool"
