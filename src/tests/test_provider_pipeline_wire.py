"""Wire-shape pins for the provider pipeline: the exact request each lane sends.

No network: httpx MockTransport answers with OpenAI-shaped payloads. What this
proves per lane — the client the factory builds for (base_url, model) sends a
well-formed OpenAI-compatible request (path, model, auth, messages) and the
pipeline parses the reply (content, reasoning lift, tool calls). Factory
arg-passing is pinned separately (test_velona_provider.py); together they cover
the pipeline short of a live key, which only the owner's machine has
(scripts/verify_llm.py runs that atom).
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.llm.factory import ReasoningAwareOpenAI, RetryLLMProxy


@pytest.fixture
def no_stream(monkeypatch):
    monkeypatch.setenv("CRUSORAI_LLM_STREAMING", "off")


def _completion(model: str, message: dict) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _mocked_lane(base_url: str, model: str, message: dict):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        body = json.loads(request.content.decode())
        seen["model"] = body.get("model")
        seen["messages"] = body.get("messages")
        return httpx.Response(200, json=_completion(model, message))

    transport = httpx.MockTransport(handler)
    llm = ReasoningAwareOpenAI(
        api_key="test-key",
        base_url=base_url,
        model=model,
        http_client=httpx.Client(transport=transport),
        http_async_client=httpx.AsyncClient(transport=transport),
        streaming=False,
        max_retries=0,
    )
    return seen, RetryLLMProxy(llm, max_attempts=1)


def test_main_lane_pareto_code_wire_shape(no_stream):
    seen, client = _mocked_lane(
        "https://openrouter.ai/api/v1",
        "openrouter/pareto-code",
        {"role": "assistant", "content": "OK", "reasoning_content": "thinking trace"},
    )
    out = client.invoke("Reply with exactly: OK")
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["model"] == "openrouter/pareto-code"
    assert seen["messages"] == [{"role": "user", "content": "Reply with exactly: OK"}]
    assert out.content == "OK"
    assert out.additional_kwargs.get("reasoning_content") == "thinking trace"
    assert out.tool_calls == []


def test_aux_lane_auto_beta_wire_shape(no_stream):
    seen, client = _mocked_lane(
        "https://openrouter.ai/api/v1",
        "openrouter/auto-beta",
        {"role": "assistant", "content": "OK"},
    )
    out = client.invoke("Reply with exactly: OK")
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["model"] == "openrouter/auto-beta"
    assert out.content == "OK"


def test_velona_lane_parses_tool_calls(no_stream):
    seen, client = _mocked_lane(
        "https://velona.in/v1",
        "openai/gpt-4o-mini",
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'},
                }
            ],
        },
    )
    out = client.invoke("Read a.txt")
    assert seen["url"] == "https://velona.in/v1/chat/completions"
    assert seen["model"] == "openai/gpt-4o-mini"
    assert out.tool_calls and out.tool_calls[0]["name"] == "read_file"
    assert out.tool_calls[0]["args"] == {"path": "a.txt"}
