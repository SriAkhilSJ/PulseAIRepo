"""Streaming transport cleanup regression from desktop Test 5 attempt 8."""
from langchain_core.messages import HumanMessage

from src.llm.factory import RetryLLMProxy, provider_response_info


class _StreamingProvider:
    model = "sarvam-105b-conversations"

    def __init__(self):
        self.generator_closed = False
        self.generator = None

    async def _response_stream(self):
        try:
            yield "partial"
            # A real HTTP stream remains open until aclose is awaited.
            yield "unread"
        finally:
            self.generator_closed = True

    async def ainvoke(self, *args, **kwargs):
        self.generator = self._response_stream()
        await self.generator.__anext__()
        return "tool-call-message"

    def invoke(self, *args, **kwargs):  # pragma: no cover - async path required
        raise AssertionError("RetryLLMProxy unexpectedly used sync invoke")


def test_proxy_drains_async_generators_before_closing_request_loop():
    provider = _StreamingProvider()
    proxy = RetryLLMProxy(provider)

    assert proxy.invoke([HumanMessage(content="build")]) == "tool-call-message"
    assert provider.generator_closed is True


class _NativeStreamingProvider:
    """LangChain-shaped fake proving a single synchronous stream owner."""

    model = "sarvam-streaming-fake"
    streaming = True

    def __init__(self):
        self.chunks = []
        self.stream_closed = False
        self.ainvoke_called = False

    def invoke(self, *args, **kwargs):
        def stream():
            try:
                for chunk in ("{\"path\":", "\"index.html\"}"):
                    self.chunks.append(chunk)
                    yield chunk
            finally:
                self.stream_closed = True

        # A real LangChain invoke aggregates the streaming iterator before it
        # returns the final AIMessage. This fake makes that ownership visible.
        return "".join(stream())

    async def ainvoke(self, *args, **kwargs):  # pragma: no cover - must not run
        self.ainvoke_called = True
        raise AssertionError("native streaming provider used async invoke")


def test_streaming_provider_is_fully_consumed_and_closed_synchronously():
    provider = _NativeStreamingProvider()

    class Binding:
        """Streaming is intentionally visible only on nested ``bound``."""
        bound = provider
        model = provider.model

        def invoke(self, *args, **kwargs):
            return self.bound.invoke(*args, **kwargs)

        async def ainvoke(self, *args, **kwargs):
            return await self.bound.ainvoke(*args, **kwargs)

    proxy = RetryLLMProxy(Binding())

    assert proxy.invoke([HumanMessage(content="build")]) == '{"path":"index.html"}'
    assert provider.chunks == ['{"path":', '"index.html"}']
    assert provider.stream_closed is True
    assert provider.ainvoke_called is False


def test_provider_response_info_recognizes_token_limit_metadata():
    class Response:
        tool_calls = [{"name": "write_file", "id": "one", "args": {}}]
        response_metadata = {"finish_reason": "max_tokens"}

    assert provider_response_info(Response()) == {
        "finish_reason": "max_tokens",
        "incomplete": True,
        "tool_call_count": 1,
        "tool_names": ["write_file"],
        "content_chars": 0,
    }
