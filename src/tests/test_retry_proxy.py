"""RetryLLMProxy pre-send guard: explicit cap vs AUTO (PROVIDER_SAFE_LIMIT=0).

AUTO mode must resolve the SAME number the ContextEngine budgeted with —
the whole point is that engine and guard can never disagree.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import settings
from src.context import model_budgets as mb
from src.llm.factory import RetryLLMProxy


class _StubLLM:
    def __init__(self, model="gpt-4o"):
        self.model = model
        self.sent = None

    def invoke(self, *args, **kwargs):
        self.sent = args[0] if args else kwargs.get("messages")
        return "ok"


def test_safe_limit_explicit(monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_SAFE_LIMIT", 12345)
    proxy = RetryLLMProxy(_StubLLM())
    assert proxy._safe_limit() == 12345


def test_safe_limit_auto_uses_discovered_window_and_memoizes(monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_SAFE_LIMIT", 0)
    calls = {"n": 0}

    def fake_resolve(model, provider=None, allow_network=True):
        calls["n"] += 1
        return (200_000, "test")

    monkeypatch.setattr(mb, "resolve_context_window", fake_resolve)
    proxy = RetryLLMProxy(_StubLLM("claude-3-5-sonnet"))
    assert proxy._safe_limit() == 200_000 - 4_096
    assert proxy._safe_limit() == 200_000 - 4_096
    assert calls["n"] == 1, "auto limit must be memoized (no per-invoke disk/network)"


def test_guard_trims_at_auto_limit(monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_SAFE_LIMIT", 0)
    monkeypatch.setattr(
        mb, "resolve_context_window",
        lambda model, provider=None, allow_network=True: (5_000, "test"),
    )
    # auto limit = max(5000 - 4096, 4096) = 4096 tokens
    llm = _StubLLM("gpt-4o")
    proxy = RetryLLMProxy(llm)
    big = "lorem ipsum dolor sit amet " * 200  # ~1200 tokens per message
    messages = [SystemMessage(content="SYS")] + [
        HumanMessage(content=f"{i}: {big}") for i in range(20)
    ]
    result = proxy.invoke(messages)
    assert result == "ok"
    assert llm.sent is not None
    assert len(llm.sent) < len(messages), "oversized payload was NOT trimmed"
    # Head (system) and tail (recent) must survive middle-out trimming.
    assert llm.sent[0].content == "SYS"
    assert llm.sent[-1].content.startswith("19:")
