"""OpenTelemetry tracing for the Crusor agent — Langfuse-compatible OTLP.

This is the agent's standard observability path (hermes parity: hermes'
langfuse plugin is the same shape — root span per turn, generation per LLM
call, span per tool, session metadata). Spans follow OpenTelemetry GenAI
semantic conventions and export to ANY OTLP HTTP backend — Langfuse by
default (self-hosted: langfuse/docker-compose.yml).

Design rules:
  * env-gated: nothing is imported, initialized, or exported unless
    CRUSORAI_OTEL=on. Off = one env check per span call, zero overhead.
  * fail-closed: every integration point swallows all exceptions. Tracing
    must never break a turn (D17 crash-net idiom).
  * local by default: the endpoint defaults to localhost and keys come from
    env — the hermes no-upload contract.

Environment:
  CRUSORAI_OTEL                  on|off (default: off)
  CRUSORAI_OTEL_ENDPOINT         OTLP HTTP traces endpoint
                                 (default http://127.0.0.1:3000/api/public/otel/v1/traces)
  CRUSORAI_LANGFUSE_PUBLIC_KEY   Langfuse public key (Basic auth with the
  CRUSORAI_LANGFUSE_SECRET_KEY   Langfuse secret key)
  CRUSORAI_OTEL_SERVICE_NAME     resource service.name (default crusor-agent)

Span shape (what Langfuse renders as the trace waterfall):
  turn {session}                       root — session.id
    node.task_manager / node.ai / ...  one per graph node
      llm {model}                      gen_ai.system, gen_ai.request.model,
                                       gen_ai.usage.input_tokens / output_tokens
      tool {name}                      gen_ai.operation.name=execute_tool,
                                       gen_ai.tool.name, redacted args
"""
from __future__ import annotations

import base64
import json
import os
import threading
from typing import Any, Callable

_TRACER_NAME = "crusor-agent"
_provider: Any = None
# session_id -> (span, context-attach token)
_turn_spans: dict[str, tuple[Any, Any]] = {}
_turn_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get("CRUSORAI_OTEL", "off").strip().lower() in {
        "1", "true", "yes", "on", "console", "file",
    }


def _console_mode() -> bool:
    """No-Docker local mode: print spans to stdout instead of OTLP export."""
    return os.environ.get("CRUSORAI_OTEL", "off").strip().lower() == "console"


def _file_mode() -> bool:
    """No-Docker persistent mode: append spans as JSONL under ~/.crusorai."""
    return os.environ.get("CRUSORAI_OTEL", "off").strip().lower() == "file"


def _otel_file_path() -> Any:
    from pathlib import Path

    d = Path.home() / ".crusorai" / "traces"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d / "otel-spans.jsonl"


class _FileSpanExporter:
    """Minimal OTel SpanExporter: one JSON object per line, fail-closed."""

    def export(self, spans: Any) -> Any:
        try:
            from opentelemetry.sdk.trace.export import SpanExportResult
        except Exception:
            return None
        try:
            import json

            path = _otel_file_path()
            with open(path, "a", encoding="utf-8") as fh:
                for span in spans or []:
                    try:
                        # to_json() pretty-prints across lines; re-dump compact
                        # so the file stays true JSONL (one span per line).
                        fh.write(json.dumps(json.loads(span.to_json())) + "\n")
                    except Exception:
                        continue
            return SpanExportResult.SUCCESS
        except Exception:
            try:
                from opentelemetry.sdk.trace.export import SpanExportResult

                return SpanExportResult.FAILURE
            except Exception:
                return None

    def shutdown(self) -> None:
        return None


def _build_provider() -> Any:
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )

    if _console_mode():
        provider = TracerProvider(
            resource=Resource.create({"service.name": "crusor-agent"}),
        )
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        return provider

    if _file_mode():
        provider = TracerProvider(
            resource=Resource.create({"service.name": "crusor-agent"}),
        )
        provider.add_span_processor(SimpleSpanProcessor(_FileSpanExporter()))
        return provider

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )

    headers = {}
    pub = os.environ.get("CRUSORAI_LANGFUSE_PUBLIC_KEY", "").strip()
    sec = os.environ.get("CRUSORAI_LANGFUSE_SECRET_KEY", "").strip()
    if pub and sec:
        headers["Authorization"] = "Basic " + base64.b64encode(
            f"{pub}:{sec}".encode()
        ).decode()
    exporter = OTLPSpanExporter(
        endpoint=os.environ.get(
            "CRUSORAI_OTEL_ENDPOINT",
            "http://127.0.0.1:3000/api/public/otel/v1/traces",
        ).strip(),
        headers=headers or None,
    )
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": os.environ.get(
                    "CRUSORAI_OTEL_SERVICE_NAME", "crusor-agent"
                ).strip()
                or "crusor-agent"
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def configure_provider(provider: Any) -> None:
    """Test hook: swap in a provider (e.g. one with an in-memory exporter)."""
    global _provider
    _provider = provider


def tracer() -> Any:
    """A tracer when OTel is on, else None. Never raises."""
    try:
        if not enabled():
            return None
        global _provider
        if _provider is None:
            _provider = _build_provider()
        from opentelemetry import trace

        return trace.get_tracer(_TRACER_NAME, tracer_provider=_provider)
    except Exception:
        return None


def _current_session() -> str | None:
    try:
        from src.runtime.turn_control import active_session

        return active_session()
    except Exception:
        return None


# ----------------------------------------------------------------- turns

def on_turn_begin(session_id: str) -> None:
    """Start the turn root span and make it the CURRENT context, so node /
    llm / tool spans opened on this thread nest under it (the trace tree).
    Called from turn_control.begin (depth 0->1)."""
    t = tracer()
    if t is None or not session_id:
        return
    try:
        with _turn_lock:
            if session_id in _turn_spans:
                return  # nested begin: the root is already current
            span = t.start_span(f"turn {session_id}")
            span.set_attribute("session.id", session_id)
            span.set_attribute("crusor.kind", "turn")
            from opentelemetry import context as otel_context
            from opentelemetry import trace as otel_trace

            token = otel_context.attach(
                otel_trace.set_span_in_context(span)
            )
            _turn_spans[session_id] = (span, token)
    except Exception:
        pass


def on_turn_end(session_id: str, *, error: str | None = None) -> None:
    """End the turn root span and detach its context.
    Called from turn_control.end (depth ->0)."""
    try:
        with _turn_lock:
            entry = _turn_spans.pop(session_id, None)
        if entry is None:
            return
        span, token = entry
        if error:
            from opentelemetry.trace import StatusCode

            span.set_attribute("crusor.turn.error", error[:200])
            span.set_status(StatusCode.ERROR, error[:200])
        else:
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.OK)
        span.end()
        from opentelemetry import context as otel_context

        try:
            otel_context.detach(token)
        except Exception:
            pass  # e.g. end() on another thread — span is ended regardless
    except Exception:
        pass


# ------------------------------------------------------------------ llm

def _set_usage_attributes(span: Any, response: Any) -> None:
    try:
        usage = getattr(response, "usage_metadata", None)
        if not usage and isinstance(getattr(response, "response_metadata", None), dict):
            usage = getattr(response, "response_metadata", {}).get("token_usage")
        if not usage:
            return
        if isinstance(usage, dict):
            in_tok = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
            out_tok = usage.get("output_tokens") or usage.get("completion_tokens") or 0
            details = usage.get("input_tokens_details") or {}
            cached = details.get("cached_tokens") if isinstance(details, dict) else None
        else:
            in_tok = getattr(usage, "input_tokens", 0) or 0
            out_tok = getattr(usage, "output_tokens", 0) or 0
            cached = None
        span.set_attribute("gen_ai.usage.input_tokens", int(in_tok or 0))
        span.set_attribute("gen_ai.usage.output_tokens", int(out_tok or 0))
        if cached:
            span.set_attribute("crusor.usage.cache_tokens", int(cached))
    except Exception:
        pass


def traced_llm_invoke(fn: Callable) -> Callable:
    """Decorator for RetryLLMProxy.invoke: one span per model call."""

    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        t = tracer()
        if t is None:
            return fn(self, *args, **kwargs)
        try:
            inner = getattr(self, "_llm", None)
            span = t.start_span(f"llm {getattr(self, 'model', '') or 'unknown'}")
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.system", type(inner or self).__name__)
            model = getattr(self, "model", "")
            if model:
                span.set_attribute("gen_ai.request.model", str(model))
            sid = _current_session()
            if sid:
                span.set_attribute("session.id", sid)
        except Exception:
            return fn(self, *args, **kwargs)
        try:
            response = fn(self, *args, **kwargs)
        except Exception as exc:
            try:
                span.set_attribute("error.type", type(exc).__name__)
                span.record_exception(exc)
            except Exception:
                pass
            try:
                span.end()
            except Exception:
                pass
            raise
        try:
            _set_usage_attributes(span, response)
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.OK)
            span.end()
        except Exception:
            pass
        return response

    return wrapper


# ----------------------------------------------------------------- tools

def tool_span_start(name: str, args: dict) -> Any:
    """Start a tool span (returns None when tracing is off). Caller MUST
    call :func:`tool_span_end` exactly once on every path."""
    t = tracer()
    if t is None:
        return None
    try:
        span = t.start_span(f"tool {name}")
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", name)
        try:
            from src.runtime.persistence import sanitize_tool_arguments

            span.set_attribute(
                "crusor.tool.args",
                json.dumps(sanitize_tool_arguments(args), ensure_ascii=False)[:400],
            )
        except Exception:
            pass
        return span
    except Exception:
        return None


def tool_span_end(span: Any, *, status: str = "ok", error: BaseException | None = None) -> None:
    """End a tool span with its logical status (no-op when span is None)."""
    if span is None:
        return
    try:
        if error is not None:
            from opentelemetry.trace import StatusCode

            span.set_attribute("error.type", type(error).__name__)
            span.record_exception(error)
            span.set_status(StatusCode.ERROR, type(error).__name__)
        elif status == "error":
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.ERROR, "tool returned error")
        else:
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.OK)
        span.end()
    except Exception:
        pass


# ------------------------------------------------------------------ nodes

def traced_node(name: str, fn: Callable) -> Callable:
    """Wrap a LangGraph node with a span (pass-through when tracing is off).

    LangGraph inspects the node's SIGNATURE to decide what to pass
    (state only, or state + config), so the wrapper mirrors the original
    signature instead of hiding it behind *args.
    """
    import inspect

    params = inspect.signature(fn).parameters
    takes_config = "config" in params

    def _run(args: tuple, kwargs: dict) -> Any:
        t = tracer()
        if t is None:
            return fn(*args, **kwargs)
        try:
            with t.start_as_current_span(f"node {name}"):
                return fn(*args, **kwargs)
        except Exception:
            # start_as_current_span already ended the span; propagate as-is.
            raise

    if takes_config:
        # NOTE: `config` must stay UNANNOTATED (or annotated RunnableConfig):
        # LangGraph injects it as a kwarg only when the parameter annotation
        # is empty/RunnableConfig/Optional[RunnableConfig] — `Any` is rejected.

        def wrapper(state: Any, config=None, **kwargs: Any) -> Any:
            return _run((state, config), kwargs)

    else:

        def wrapper(state: Any, **kwargs: Any) -> Any:
            return _run((state,), kwargs)

    wrapper.__name__ = getattr(fn, "__name__", name)
    wrapper.__doc__ = getattr(fn, "__doc__", None)
    return wrapper
