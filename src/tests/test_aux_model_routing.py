"""Pins for D21: auxiliary-model maintenance routing (hermes curator
invariant, §29 — aux "never touches the main session's prompt cache").

Contract:
- housekeeping calls (task classification, opt-in giant-output summaries)
  bill the AUXILIARY client, not the flagship
- aux resolution: env override -> per-provider cheap table -> main fallback
  (unknown providers degrade to main = identical behavior, never breakage)
- each aux call owns a DISTINCT request client, so cancellation cannot poison
  future turns or unrelated sessions
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
def test_aux_client_is_distinct_and_request_owned(monkeypatch):
    monkeypatch.setattr(settings, "AUX_LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "AUX_LLM_MODEL", "llama-3.1-8b-instant")

    builds: list[tuple[str, str]] = []

    class _Client:
        def __init__(self, number):
            self.number = number

        def invoke(self, *args, **kwargs):
            return self.number

    def _build(provider, model):
        builds.append((provider, model))
        return _Client(len(builds))

    monkeypatch.setattr(factory, "get_llm", _build)
    aux1 = factory.get_auxiliary_llm()
    aux2 = factory.get_auxiliary_llm()
    assert aux1 is not aux2
    assert aux1.invoke([]) == 1
    assert aux1.invoke([]) == 2
    assert aux2.invoke([]) == 3
    assert builds == [("groq", "llama-3.1-8b-instant")] * 3


def test_aux_client_wraps_retry_policy(monkeypatch):
    class _Client:
        model = "aux"

        def invoke(self, *args, **kwargs):
            return "ok"

    proxy = RetryLLMProxy(_Client())
    monkeypatch.setattr(factory, "get_llm", lambda provider, model: proxy)
    assert factory.get_auxiliary_llm().invoke([]) == "ok"


def test_task_manager_prefers_aux_falls_back_to_main(monkeypatch):
    """Updated to the hermes-auxiliary-discipline lane: the classifier builds
    via get_llm with the RESOLVED aux route and an env budget; a failed aux
    build falls back to the exact main config."""
    import src.graphs.chat_graph as cg

    monkeypatch.setenv("AUX_LLM_PROVIDER", "groq")
    monkeypatch.setenv("AUX_LLM_MODEL", "llama-3.1-8b-instant")
    monkeypatch.delenv("PULSEAI_CLASSIFIER_ATTEMPTS", raising=False)
    monkeypatch.delenv("PULSEAI_CLASSIFIER_TIMEOUT_S", raising=False)

    called: dict[str, tuple] = {}

    def _fake_get_llm(provider, model, max_attempts=None, request_timeout=None):
        called.setdefault("aux", []).append(
            (provider, model, max_attempts, request_timeout)
        )
        if provider == "groq" and model == "llama-3.1-8b-instant":
            return "AUX-PROXY"
        return "MAIN"

    monkeypatch.setattr(cg, "get_llm", _fake_get_llm)
    assert cg._task_manager_llm("groq", "M") == "AUX-PROXY"
    provider, model, attempts, timeout = called["aux"][-1]
    assert (provider, model) == ("groq", "llama-3.1-8b-instant")
    assert attempts == 1 and timeout == 10.0  # the env budget defaults

    # aux build fails -> the MAIN config is used exactly, with no budget
    def _boom(provider, model, max_attempts=None, request_timeout=None):
        if model == "llama-3.1-8b-instant":
            raise RuntimeError("provider down")
        called["hit"] = (provider, model)
        return "MAIN"

    monkeypatch.setattr(cg, "get_llm", _boom)
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
