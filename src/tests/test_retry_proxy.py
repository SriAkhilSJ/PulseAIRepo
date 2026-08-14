"""RetryLLMProxy pre-send guard: explicit cap vs AUTO (PROVIDER_SAFE_LIMIT=0).

AUTO mode must resolve the SAME number the ContextEngine budgeted with —
the whole point is that engine and guard can never disagree.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import settings
from src.context import model_budgets as mb
from src.context.model_budgets import usable_window_budget
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
    assert proxy._safe_limit() == usable_window_budget(200_000)
    assert proxy._safe_limit() == usable_window_budget(200_000)
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


# =====================================================================
# Round-13 fixes (both proven pre-fix in adversarial experiments)
# =====================================================================

import threading


def test_auto_limit_memoization_is_thread_safe(monkeypatch):
    """Pre-fix proof: two racing threads BOTH resolved (calls == 2).
    Double-checked locking must make it exactly one."""
    monkeypatch.setattr(settings, "PROVIDER_SAFE_LIMIT", 0)
    entered = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def gated_resolve(model, provider=None, allow_network=True):
        calls["n"] += 1
        entered.set()
        release.wait(2)
        return (131_072, "test")

    monkeypatch.setattr(mb, "resolve_context_window", gated_resolve)
    proxy = RetryLLMProxy(_StubLLM("m/unknown"))
    results = []

    t1 = threading.Thread(target=lambda: results.append(proxy._safe_limit()))
    t1.start()
    assert entered.wait(2)          # t1 is inside resolve, holding the lock
    t2 = threading.Thread(target=lambda: results.append(proxy._safe_limit()))
    t2.start()                      # must block on the lock, not re-resolve
    release.set()
    t1.join(); t2.join()
    assert calls["n"] == 1, f"race re-resolved: {calls['n']} calls"
    assert results == [usable_window_budget(131_072)] * 2


class _NoModelAttrs:
    """A provider object exposing no model/model_name/model_id attr."""

    def invoke(self, *a, **k):
        return "ok"


def test_model_extraction_falls_back_to_llm_model():
    proxy = RetryLLMProxy(_NoModelAttrs())
    assert proxy.model == settings.LLM_MODEL


def test_auto_lockstep_holds_when_provider_hides_model_attr(monkeypatch):
    """The silent amputation from the round-13 experiment: provider hides
    its model attr -> proxy used to resolve the 4,096 unknown default while
    the engine budgeted 126,976. With the settings fallback they agree."""
    monkeypatch.setattr(settings, "PROVIDER_SAFE_LIMIT", 0)
    monkeypatch.setattr(
        mb, "resolve_context_window",
        lambda model, provider=None, allow_network=True: (131_072, "test"),
    )
    from src.context.context_engine import ContextEngine
    eng = ContextEngine(model=settings.LLM_MODEL, llm=None, memory_manager=None)
    proxy = RetryLLMProxy(_NoModelAttrs())
    assert proxy._safe_limit() == eng.max_tokens == usable_window_budget(131_072)


def test_missing_model_is_never_silent(monkeypatch, capsys):
    """Round-14 nit: even the pathological case (no provider attr AND an
    empty LLM_MODEL) must announce itself, not pass silently."""
    monkeypatch.setattr(settings, "LLM_MODEL", "")
    proxy = RetryLLMProxy(_NoModelAttrs())
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "no model name available" in out
    # And it must not *lie* either: model stays falsy rather than inventing one.
    assert not proxy.model


def test_fallback_log_announces_the_model_used(capsys):
    proxy = RetryLLMProxy(_NoModelAttrs())
    out = capsys.readouterr().out
    assert "falling back to LLM_MODEL" in out
    assert proxy.model == settings.LLM_MODEL
