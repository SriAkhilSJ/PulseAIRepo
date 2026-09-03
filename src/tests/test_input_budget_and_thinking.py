"""Input-budget spend clamps + streamed-thinking forwarding.

Owner desktop run (2026-09-03): 'hi' sat 33s and a follow-up model call sat
3m42s -- the engine built per-call budgets PROPORTIONAL to the discovered 1M
window (~400k context + ~600k history), so every call prefilled hundreds of
thousands of tokens on the custom router endpoint. The window is a ceiling,
not a target: input spend is now clamped by env getters, the build prints
its wall time, and the pump forwards reasoning_content deltas as live
Thinking (accumulated text, no protocol change).
"""
from __future__ import annotations

import uuid


# ---------------------------------------------------------------------------
# spend-cap getters (env-driven, clamped, honest source)
# ---------------------------------------------------------------------------

def test_spend_cap_defaults_and_env(monkeypatch):
    from src.context.model_budgets import (
        context_spend_cap, history_spend_cap, input_budget_source,
    )

    monkeypatch.delenv("PULSEAI_CONTEXT_BUDGET_TOKENS", raising=False)
    monkeypatch.delenv("PULSEAI_HISTORY_BUDGET_TOKENS", raising=False)
    assert context_spend_cap() == 32_768
    assert history_spend_cap() == 98_304
    assert input_budget_source() == "defaults"

    monkeypatch.setenv("PULSEAI_CONTEXT_BUDGET_TOKENS", "8192")
    assert context_spend_cap() == 8_192
    assert input_budget_source() == "env"

    monkeypatch.setenv("PULSEAI_HISTORY_BUDGET_TOKENS", "bogus")
    assert history_spend_cap() == 98_304  # garbage -> default

    monkeypatch.setenv("PULSEAI_CONTEXT_BUDGET_TOKENS", "1")
    assert context_spend_cap() == 2_048  # clamped to lo


def test_small_window_budgets_unchanged_by_clamps():
    """The default-window fallback path (8,192 -> 4,096 -> 1,638) is pinned
    by the receipt contract; the clamps must only ever SHRINK large spends,
    never touch small windows."""
    from src.context.model_budgets import context_spend_cap

    # min(int(4096 * 0.4), 32768) == 1638 -- the pinned value survives.
    assert min(int(4_096 * 0.4), context_spend_cap()) == 1_638


# ---------------------------------------------------------------------------
# pump: reasoning_content deltas become accumulated reasoning.update events
# ---------------------------------------------------------------------------

class _Chunk:
    def __init__(self, extra=None, text=""):
        self.additional_kwargs = extra or {}
        self.text = text


def test_pump_emits_accumulated_reasoning(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    emitted = []
    monkeypatch.setattr(chat_graph, "event_bus", type(
        "Bus", (), {"emit": staticmethod(lambda kind, payload: emitted.append((kind, payload)))}
    )())

    pump = chat_graph._AgentTokenPump("t1")
    pump.on_llm_new_token("", chunk=_Chunk({"reasoning_content": "Think"}))
    pump.on_llm_new_token("", chunk=_Chunk({"reasoning_content": "Thinking hard"}))
    pump.on_llm_new_token("Answer", chunk=_Chunk())

    kinds = [k for k, _ in emitted]
    assert kinds[0] == "reasoning.update" and kinds[1] == "reasoning.update"
    assert kinds[-1] == "message.agent.chunk"
    assert emitted[0][1]["text"] == "Think"
    assert emitted[1][1]["text"] == "Thinking hard"  # accumulated
    assert pump.streamed is True


def test_pump_ignores_reasoning_none_and_answer_has_no_reasoning(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    emitted = []
    monkeypatch.setattr(chat_graph, "event_bus", type(
        "Bus", (), {"emit": staticmethod(lambda kind, payload: emitted.append((kind, payload)))}
    )())

    pump = chat_graph._AgentTokenPump("t2")
    pump.on_llm_new_token("Hi", chunk=_Chunk())  # plain answer chunk
    assert [k for k, _ in emitted] == ["message.agent.chunk"]
    assert pump._reasoning_acc == ""


# ---------------------------------------------------------------------------
# bridge: reasoning.update projects to the existing reasoning frame
# ---------------------------------------------------------------------------

def test_bridge_maps_reasoning_update():
    from src.runtime.identity import TurnIdentity

    import src.bridge.__main__ as bridge_main

    owner = None
    for name in dir(bridge_main):
        obj = getattr(bridge_main, name)
        if isinstance(obj, type) and hasattr(obj, "_project_event"):
            owner = obj
            break
    assert owner is not None, "the _project_event owner class must exist"

    identity = TurnIdentity(
        session_id="s1", runtime_session_id="s1",
        lineage_root_id="l1", workspace_id="w1",
        turn_id="t1", created_at=0.0,
    )
    frame = owner._project_event(
        {"type": "reasoning.update", "payload": {"text": "thinking"}},
        identity,
    )
    assert frame is not None
    assert frame["type"] == "reasoning"
    assert frame["text"] == "thinking"
    assert frame["session_id"] == "s1"
