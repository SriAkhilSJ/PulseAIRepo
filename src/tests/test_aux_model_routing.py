"""Pins for D21: auxiliary-model maintenance routing (hermes curator
invariant, §29 — aux "never touches the main session's prompt cache").

Contract:
- housekeeping calls (task classification, opt-in giant-output summaries)
  bill the AUXILIARY client, not the flagship
- aux resolution: env override -> per-provider cheap table -> main fallback
  (unknown providers degrade to main = identical behavior, never breakage)
- the aux client is a DISTINCT, cached object from get_llm() results
- SmartSummarizer stays LLM-free unless SUMMARIZER_LLM=aux opts in
"""

from __future__ import annotations



import pytest

import src.config.settings as settings
from src.llm import factory
from src.llm.factory import RetryLLMProxy


# ------------------------------------------------------------- resolution
def test_aux_resolution_cheap_table_default(monkeypatch):
    monkeypatch.delenv("AUX_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AUX_LLM_MODEL", raising=False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "LLM_MODEL", "qwen/qwen3.6-27b")
    provider, model = settings.resolve_aux_llm()
    assert (provider, model) == ("groq", "llama-3.1-8b-instant")


def test_aux_resolution_env_override_wins(monkeypatch):
    monkeypatch.setenv("AUX_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AUX_LLM_MODEL", "gpt-4o-mini-custom")
    provider, model = settings.resolve_aux_llm()
    assert (provider, model) == ("openai", "gpt-4o-mini-custom")


def test_aux_resolution_unknown_provider_falls_back_to_main(monkeypatch):
    monkeypatch.delenv("AUX_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AUX_LLM_MODEL", raising=False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "custom")
    monkeypatch.setattr(settings, "LLM_MODEL", "my-local-model")
    provider, model = settings.resolve_aux_llm()
    assert (provider, model) == ("custom", "my-local-model")


# ---------------------------------------------------------------- factory
def test_aux_client_is_distinct_and_cached(monkeypatch):
    factory._aux_llm_cache.clear()
    monkeypatch.setattr(settings, "AUX_LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "AUX_LLM_MODEL", "llama-3.1-8b-instant")

    builds: list[tuple[str, str]] = []
    monkeypatch.setattr(
        factory, "get_llm",
        lambda provider, model: builds.append((provider, model)) or object(),
    )
    aux1 = factory.get_auxiliary_llm()
    aux2 = factory.get_auxiliary_llm()
    assert aux1 is aux2                           # cached client
    assert builds == [("groq", "llama-3.1-8b-instant")]  # built once, AUX settings
    main = factory.get_llm(provider="groq", model="qwen/qwen3.6-27b")
    assert aux1 is not main                       # the curator invariant
    assert builds[-1] == ("groq", "qwen/qwen3.6-27b")    # main model unchanged


def test_aux_client_wraps_retry_policy(monkeypatch):
    factory._aux_llm_cache.clear()
    monkeypatch.setattr(
        factory, "get_llm",
        lambda provider, model: RetryLLMProxy(object()),
    )
    assert isinstance(factory.get_auxiliary_llm(), RetryLLMProxy)


def test_task_manager_prefers_aux_falls_back_to_main(monkeypatch):
    import src.graphs.chat_graph as cg

    sentinel = object()
    monkeypatch.setattr(cg, "get_auxiliary_llm", lambda: sentinel)
    assert cg._task_manager_llm("groq", "M") is sentinel

    def _boom():
        raise RuntimeError("provider down")

    called: dict[str, tuple] = {}

    def _main(provider, model):
        called["hit"] = (provider, model)
        return "MAIN"

    monkeypatch.setattr(cg, "get_auxiliary_llm", _boom)
    monkeypatch.setattr(cg, "get_llm", _main)
    assert cg._task_manager_llm("groq", "M") == "MAIN"
    assert called["hit"] == ("groq", "M")     # exact main config preserved
    # monkeypatch reverts automatically at teardown.


# ------------------------------------------------------ summarizer wiring
@pytest.fixture()
def fresh_engine_key(monkeypatch):
    """Isolated session bucket so memoized engines never collide."""
    import src.graphs.chat_graph as cg
    key = "aux-test-session"
    with cg._ENGINES_LOCK:
        cg._ENGINES.pop(key, None)
    yield cg, key
    with cg._ENGINES_LOCK:
        cg._ENGINES.pop(key, None)


def test_summarizer_default_free_opt_in_uses_aux(fresh_engine_key, monkeypatch, tmp_path):
    cg, key = fresh_engine_key
    monkeypatch.setattr(settings, "SUMMARIZER_LLM", "")
    cfg = {"configurable": {"thread_id": key, "workspace": str(tmp_path)}}
    engine = cg.get_context_engine(cfg)
    assert engine.summarizer.llm is None      # default: zero LLM spend

    with cg._ENGINES_LOCK:
        cg._ENGINES.pop(key, None)
    monkeypatch.setattr(settings, "SUMMARIZER_LLM", "aux")
    sentinel = object()
    monkeypatch.setattr(cg, "get_auxiliary_llm", lambda: sentinel)
    engine = cg.get_context_engine(cfg)
    assert engine.summarizer.llm is sentinel  # opt-in: janitor-priced LLM


def test_summarizer_opt_in_aux_failure_degrades_to_free(fresh_engine_key, monkeypatch, tmp_path):
    cg, key = fresh_engine_key

    def _boom():
        raise RuntimeError("no aux provider key")

    monkeypatch.setattr(settings, "SUMMARIZER_LLM", "aux")
    monkeypatch.setattr(cg, "get_auxiliary_llm", _boom)
    cfg = {"configurable": {"thread_id": key, "workspace": str(tmp_path)}}
    engine = cg.get_context_engine(cfg)
    assert engine.summarizer.llm is None      # degraded, never broken
