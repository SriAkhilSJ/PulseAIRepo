"""Law-1 visibility: the provider's prompt-cache hit count is captured,
merged, and PRINTED — and the request prefix is pinned byte-stable.

hermes' first invariant: a long-lived conversation reuses a cached prefix
every turn, and cost follows. Crusor's custom tier re-bills all bound tool
schemas on every call unless the provider's automatic prefix caching
engages; nobody could SEE whether it does (field 2026-09-10: 628k billed
over 15 calls with the estimate reading ~18.5k — the schemas' share was
invisible). The provider reports hits as LangChain
``usage_metadata.input_token_details.cache_read`` (OpenAI
``prompt_tokens_details.cached_tokens`` maps there; the raw OpenAI shape in
``additional_kwargs`` is the fallback).
"""
from langchain_core.messages import AIMessage, HumanMessage

from src.context.token_tracker import TokenTracker, TokenUsage


def _ai_with_usage(cached, input_tokens=1000, output_tokens=50, raw_openai=False):
    msg = AIMessage(content="ok")
    if raw_openai:
        msg.additional_kwargs["prompt_tokens_details"] = {"cached_tokens": cached}
        msg.usage_metadata = {
            "input_tokens": input_tokens, "output_tokens": output_tokens,
        }
    else:
        msg.usage_metadata = {
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "input_token_details": {"cache_read": cached},
        }
    return msg


# ── extraction ─────────────────────────────────────────────────────────────


def test_cache_read_extracted_from_langchain_standard_shape():
    usage = TokenTracker.record_call([HumanMessage(content="hi")],
                                     _ai_with_usage(8123), "m")
    assert usage.cached_tokens == 8123
    assert usage.prompt_tokens == 1000


def test_cache_read_extracted_from_raw_openai_shape():
    usage = TokenTracker.record_call([HumanMessage(content="hi")],
                                     _ai_with_usage(777, raw_openai=True), "m")
    assert usage.cached_tokens == 777


def test_no_cache_data_stays_zero_and_never_fails():
    plain = AIMessage(content="ok")
    plain.usage_metadata = {"input_tokens": 10, "output_tokens": 2}
    usage = TokenTracker.record_call([HumanMessage(content="hi")], plain, "m")
    assert usage.cached_tokens == 0


def test_garbage_cache_fields_degrade_to_zero():
    msg = _ai_with_usage("not-a-number")
    usage = TokenTracker.record_call([HumanMessage(content="hi")], msg, "m")
    assert usage.cached_tokens == 0


# ── merge: the turn total carries the cache truth ──────────────────────────


def test_merge_sums_cached_tokens():
    merged = TokenTracker.record_call([HumanMessage(content="a")],
                                      _ai_with_usage(500), "m")
    merged2 = TokenTracker.record_call([HumanMessage(content="b")],
                                       _ai_with_usage(700), "m")
    total = (merged + merged2).to_dict()
    assert total["cached_tokens"] == 1200
    assert TokenUsage.from_dict(total).cached_tokens == 1200


# ── the ai_node prints the hit when the provider reports one ───────────────


def _state(thread):
    return {
        "messages": [HumanMessage(content="do a thing")],
        "current_task": "do a thing",
        "execution_mode": "agent",
        "iteration_used": 0,
        "token_usage": {}, "turn_token_usage": {},
        "execution_trace": [], "plan": [], "incomplete_response_retries": 0,
        "grace_done": 0, "finish_nudges": 0, "verify_nudges": 0,
        "workspace": "/nonexistent",
    }


def _config(thread):
    return {"configurable": {"workspace": "/nonexistent", "thread_id": thread,
                             "execution_mode": "agent"}}


class _FakeEngine:
    def build_ai_messages(self, state, system_message):
        from langchain_core.messages import SystemMessage
        return [SystemMessage(content="PERSONA"), SystemMessage(content="LAYER")]


def _patch_provider(monkeypatch, replied):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "10")

    class _FakeLLM:
        model = "m"
        def bind_tools(self, tools):
            return self
        def invoke(self, messages, **kw):
            return replied

    import src.graphs.chat_graph as cg
    monkeypatch.setattr(cg, "get_llm", lambda provider, model, reasoning_config=None, **kw: _FakeLLM())
    monkeypatch.setattr(cg, "get_context_engine", lambda config: _FakeEngine())
    monkeypatch.setattr(cg.cost_router, "route", lambda t, p: ("groq", "m"))


def test_ai_node_prints_cache_hit_line(capsys, monkeypatch):
    _patch_provider(monkeypatch, _ai_with_usage(9000, input_tokens=12000, output_tokens=100))
    import src.graphs.chat_graph as cg

    out = cg.ai_node(_state("cache-t"), _config("cache-t"))
    assert out["token_usage"]["cached_tokens"] == 9000
    printed = capsys.readouterr().out
    assert "prompt cache: 9,000 of 12,000 prompt tokens served from cache (75%)" in printed


def test_ai_node_silent_when_provider_reports_no_cache(capsys, monkeypatch):
    replied = AIMessage(content="done")
    replied.usage_metadata = {"input_tokens": 500, "output_tokens": 20}
    _patch_provider(monkeypatch, replied)
    import src.graphs.chat_graph as cg

    cg.ai_node(_state("cache-s"), _config("cache-s"))
    assert "prompt cache:" not in capsys.readouterr().out


# ── byte-stability pins: the prefix the provider must match ────────────────


def test_binding_order_is_deterministic_for_identical_state(tmp_path):
    """Same state -> the SAME tool list ORDER, twice. A set leaking into the
    order would rotate the serialized tools array and bust the provider's
    cached prefix silently."""
    from src.graphs.chat_graph import _resolve_bound_tools

    config = {"configurable": {"thread_id": "stab", "workspace": str(tmp_path)}}
    state = {"current_task": "build a demo page"}
    first = [t.name for t in _resolve_bound_tools(state, config)]
    second = [t.name for t in _resolve_bound_tools(state, config)]
    assert first == second and len(first) > 20


def test_phase_narrowing_preserves_registry_order(tmp_path):
    """Phase allowlists FILTER the registry list — relative order survives
    (the narrowed request stays a PREFIX of the full one), it is never
    rebuilt from a set."""
    from src.graphs.chat_graph import _resolve_bound_tools

    config = {"configurable": {"thread_id": "stab2", "workspace": str(tmp_path),
                               "execution_phase": "deliver"}}
    state = {"current_task": "write the file now"}
    names = [t.name for t in _resolve_bound_tools(state, config)]
    config_full = {"configurable": {"thread_id": "stab2", "workspace": str(tmp_path)}}
    full = [t.name for t in _resolve_bound_tools({"current_task": "x"}, config_full)]
    it = iter(full)
    assert all(n in it for n in names), "phase narrowing must preserve registry order"
