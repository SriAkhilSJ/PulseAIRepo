"""Streaming transport cleanup regression from desktop Test 5 attempt 8."""
from langchain_core.messages import HumanMessage

from src.llm.factory import RetryLLMProxy


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
