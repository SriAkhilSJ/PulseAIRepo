"""Does the warm-up actually fix the owner's case, and does it stay off the critical path?"""
import time
import pytest
from src.context import model_budgets as mb


def test_warm_up_applies_a_late_endpoint_answer_without_blocking_init(monkeypatch):
    from src.context.context_engine import ContextEngine
    import src.config.settings as settings

    monkeypatch.setattr(settings, "CUSTOM_BASE_URL", "http://127.0.0.1:20128/v1", raising=False)
    monkeypatch.setattr(mb, "_write_cache", lambda *a, **k: None)
    monkeypatch.setattr(mb, "_cache_get", lambda *a, **k: None)

    def slow_probe(model_name):
        time.sleep(0.4)  # the owner's real endpoint took 5.1s
        return 1_048_576

    monkeypatch.setattr(mb, "_probe_custom_endpoint", slow_probe)
    monkeypatch.setattr(mb, "resolve_context_window",
                        lambda *a, **k: (mb.MODEL_WINDOWS["default"], "default"))

    t0 = time.monotonic()
    engine = ContextEngine(model="auto", llm=None, memory_manager=None)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.35, f"init blocked on the endpoint ({elapsed:.2f}s) -- that is the bug we are avoiding"

    assert engine._meta_thread is not None, "no warm-up started"
    engine._meta_thread.join(timeout=5)
    assert engine.context_window == 1_048_576, engine.context_window
    assert engine.context_window_source == "custom-api", engine.context_window_source
    assert engine.max_tokens > 100_000, engine.max_tokens


def test_warm_up_defers_when_a_build_is_in_flight(monkeypatch):
    from src.context.context_engine import ContextEngine
    import src.config.settings as settings

    monkeypatch.setattr(settings, "CUSTOM_BASE_URL", "http://127.0.0.1:20128/v1", raising=False)
    monkeypatch.setattr(mb, "_write_cache", lambda *a, **k: None)
    monkeypatch.setattr(mb, "resolve_context_window", lambda *a, **k: (8_192, "default"))
    monkeypatch.setattr(mb, "_probe_custom_endpoint", lambda m: 200_000)

    engine = ContextEngine(model="auto", llm=None, memory_manager=None)
    engine._active_pool = object()  # a build is running
    engine._endpoint_retry_worker("auto")  # call directly: deterministic, no thread race
    assert engine.context_window != 200_000, "it must not mutate budgets mid-build"
