"""P1A: incremental delivery through the shared ModelGateway.

The transport is REAL: a local HTTP server speaking OpenAI SSE
(`scripts/streaming_provider_stub.py`) consumed by a real `ChatOpenAI` client
through `RetryLLMProxy`. No paid request is made; the server is on loopback.

What is proven here:
* provider deltas reach `on_token` in order, before the call returns;
* the accumulated text equals the non-streaming response;
* usage still arrives (stream_usage) so FinOps can settle;
* cancellation aborts consumption;
* a broken stream surfaces as an error, never as success;
* a client that does not stream keeps working unchanged.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STUB_PATH = REPO / "scripts" / "streaming_provider_stub.py"


def _load_stub():
    spec = importlib.util.spec_from_file_location("crusor_streaming_stub", STUB_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["crusor_streaming_stub"] = module
    spec.loader.exec_module(module)
    return module


class StubServer:
    def __init__(self, **overrides):
        self.stub = _load_stub()
        args = argparse.Namespace(
            port=0, host="127.0.0.1", model="z-ai/glm-5.3-flash",
            content=overrides.get("content"),
            chunks=overrides.get("chunks", 6),
            chunk_delay_ms=overrides.get("chunk_delay_ms", 10),
            fail_after=overrides.get("fail_after", 0),
        )
        self.stub.Handler.state = self.stub.State(args)
        self.server = self.stub.ThreadingHTTPServer(("127.0.0.1", 0), self.stub.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def requests(self) -> int:
        return self.stub.Handler.state.requests

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def _client(base_url: str, *, streaming: bool = True):
    from langchain_openai import ChatOpenAI
    from src.llm.factory import RetryLLMProxy

    llm = ChatOpenAI(
        api_key="test-key",
        base_url=base_url,
        model="z-ai/glm-5.3-flash",
        streaming=streaming,
        stream_usage=streaming,
        max_retries=0,
        request_timeout=20,
    )
    return RetryLLMProxy(llm, provider="custom")


def _context():
    from src.llm.gateway import new_invocation_context

    return new_invocation_context(
        session_id="s", turn_id="t", task_id="t",
        provider="custom", model="z-ai/glm-5.3-flash", purpose="stream_test",
    )


PROMPT = "Target file: notes.md\nWrite a short greeting."


def test_first_delta_arrives_before_the_call_returns() -> None:
    from src.llm.gateway import invoke_model

    with StubServer(chunks=5, chunk_delay_ms=25) as stub:
        tokens: list[str] = []
        completed = {"value": False}

        def on_token(token: str) -> None:
            assert not completed["value"], "a delta arrived after the call returned"
            tokens.append(token)

        result = invoke_model(
            _client(stub.base_url), PROMPT, context=_context(), on_token=on_token,
        )
        completed["value"] = True

    assert len(tokens) >= 5
    assert result.streamed_chunks == len(tokens)
    assert result.first_token_s is not None
    assert result.first_token_s < result.elapsed_s


def test_deltas_preserve_provider_order_and_accumulate_to_the_same_result() -> None:
    from src.llm.gateway import invoke_model

    with StubServer(chunks=8, chunk_delay_ms=5) as stub:
        tokens: list[str] = []
        streamed = invoke_model(
            _client(stub.base_url), PROMPT, context=_context(), on_token=tokens.append,
        )

    assert "".join(tokens) == streamed.text
    assert streamed.text.startswith("# Notes")
    # A caller that does not ask for incremental delivery keeps the exact
    # non-streaming behaviour: one complete response, no deltas.
    with StubServer(chunks=8, chunk_delay_ms=0) as stub2:
        plain = invoke_model(
            _client(stub2.base_url, streaming=False), PROMPT, context=_context(),
        )
    assert plain.text == streamed.text
    assert plain.streamed_chunks == 0
    # An explicit streaming-disabled client asked for deltas still yields the
    # only content it produces (one aggregated delta), never fabricated ones.
    with StubServer(chunks=8, chunk_delay_ms=0) as stub3:
        one: list[str] = []
        disabled = invoke_model(
            _client(stub3.base_url, streaming=False), PROMPT,
            context=_context(), on_token=one.append,
        )
    assert disabled.text == streamed.text
    assert len(one) == 1


def test_usage_and_invocation_identity_survive_streaming() -> None:
    from src.llm.gateway import invoke_model

    with StubServer(chunks=4, chunk_delay_ms=5) as stub:
        context = _context()
        result = invoke_model(
            _client(stub.base_url), PROMPT, context=context, on_token=lambda _t: None,
        )

    assert result.context.invocation_id.startswith("inv-")
    assert result.usage.get("input_tokens", 0) > 0
    assert result.usage.get("output_tokens", 0) > 0
    assert result.usage.get("total_tokens", 0) >= result.usage.get("output_tokens", 0)


def test_cancellation_stops_consumption_and_raises() -> None:
    from src.llm.factory import TurnCancelledError
    from src.llm.gateway import invoke_model

    with StubServer(chunks=30, chunk_delay_ms=40) as stub:
        seen: list[str] = []
        cancelled = {"value": False}

        def on_token(token: str) -> None:
            seen.append(token)
            if len(seen) >= 3:
                cancelled["value"] = True

        started = time.monotonic()
        with pytest.raises(TurnCancelledError):
            invoke_model(
                _client(stub.base_url), PROMPT, context=_context(),
                on_token=on_token, cancellation_checker=lambda: cancelled["value"],
            )
        elapsed = time.monotonic() - started

    # 30 chunks at 40ms would take >1.2s if consumption had continued.
    assert 3 <= len(seen) < 30
    assert elapsed < 1.5


def test_broken_stream_is_an_error_not_a_success() -> None:
    from src.llm.gateway import invoke_model

    with StubServer(chunks=20, chunk_delay_ms=5, fail_after=3) as stub:
        seen: list[str] = []
        with pytest.raises(Exception):
            invoke_model(
                _client(stub.base_url), PROMPT, context=_context(), on_token=seen.append,
            )

    assert len(seen) <= 3
