"""Contract tests: the compaction status surface (Hermes parity, P0 cut).

Covers the three seams added to close the Hermes deltas:

1. ``resolve_model_threshold`` — per-model threshold overrides, longest
   substring wins, one-time config snapshot (hermes-agent
   ``context_compressor.resolve_model_threshold``, re-read at 4dac5f2).
2. ``context.status`` events — the engine speaks when a pressure episode is
   open (pre_api/compress), reports the terminal edge ONLY when the history
   pipeline actually reclaimed something, and warns ONCE per episode when
   compaction is blocked while real usage sits at/over the threshold
   (the #62625 silent-overflow fix).
3. Bridge projection — ``context.status`` maps to the ``context_status``
   wire frame with identity fields and a payload passthrough.

Everything here is provider-free: no LLM, no network, no embeddings.
"""
import os

import pytest

from src.context.context_engine import ContextEngine
from src.context.engine import ContextEngine as BaseContextEngine
from src.context.engine import resolve_model_threshold


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Capture:
    """Stands in for the event-bus singleton; records (type, payload)."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event_type: str, payload: dict):
        self.events.append((event_type, dict(payload)))


@pytest.fixture()
def captured(monkeypatch):
    from src.dashboard import event_bus as bus_module
    cap = _Capture()
    monkeypatch.setattr(bus_module.event_bus, "emit", cap)
    return cap


def _engine(thread_id: str = "s-status-test") -> ContextEngine:
    return ContextEngine(max_tokens=4000, llm=None, memory_manager=None, thread_id=thread_id)


def _arm_pressure(engine: ContextEngine, window: int = 1000, prompt: int = 800) -> None:
    """Give the engine a real window and REAL usage at/over the threshold."""
    engine._apply_window(window, "test")
    engine.update_from_response({"prompt_tokens": prompt, "completion_tokens": 10})


# ---------------------------------------------------------------------------
# 1. resolve_model_threshold
# ---------------------------------------------------------------------------

def test_longest_substring_wins():
    thresholds = {"glm-5.2": 0.60, "glm-5.2-1M": 0.50}
    assert resolve_model_threshold("glm-5.2-1M", thresholds, 0.75) == 0.50
    assert resolve_model_threshold("glm-5.2", thresholds, 0.75) == 0.60


def test_no_match_returns_default():
    assert resolve_model_threshold("gpt-x", {"glm-5.2": 0.5}, 0.75) == 0.75
    assert resolve_model_threshold("gpt-x", {}, 0.75) == 0.75
    assert resolve_model_threshold("gpt-x", None, 0.75) == 0.75
    assert resolve_model_threshold(None, {"glm": 0.5}, 0.75) == 0.75


# ---------------------------------------------------------------------------
# 2. Per-model thresholds through update_model (ABC + layered engine)
# ---------------------------------------------------------------------------

class _MinimalEngine(BaseContextEngine):
    """The ABC is abstract; the smallest honest signer of the contract."""

    @property
    def name(self) -> str:
        return "minimal"

    def update_from_response(self, usage):
        pass

    def should_compress(self, prompt_tokens=None) -> bool:
        return False

    def compress(self, messages, current_tokens=None, focus_topic=None, force=False, memory_context=""):
        return messages


def test_abc_update_model_applies_override_and_snapshots_config():
    eng = _MinimalEngine()
    eng.model_thresholds = {"glm-5.2-1M": 0.50, "glm-5.2": 0.60}
    eng.update_model("glm-5.2-1M", 1_000_000)
    assert eng.threshold_percent == 0.50
    assert eng.threshold_tokens == 500_000
    # Switching to a model with NO override falls back to the CONFIGURED
    # default (0.75), never to the previous model's override (0.50).
    eng.update_model("some-other-model", 100_000)
    assert eng.threshold_percent == 0.75
    assert eng.threshold_tokens == 75_000
    # Repeated switches keep falling back to the config snapshot.
    eng.update_model("glm-5.2", 200_000)
    assert eng.threshold_percent == 0.60
    eng.update_model("some-other-model-2", 100_000)
    assert eng.threshold_percent == 0.75


def test_layered_engine_update_model_syncs_fuel_gauge():
    eng = _engine()
    eng.model_thresholds = {"test-model": 0.50}
    eng.update_model("test-model", 10_000)
    assert eng.threshold_percent == 0.50
    # threshold_tokens AND the UsagePressure copy must agree — otherwise the
    # gauge decides with a stale percent while get_status reports the new one.
    assert eng.threshold_tokens == 5_000
    assert eng._pressure.threshold_percent == 0.50
    eng.update_model("unrelated-model", 10_000)
    assert eng.threshold_percent == 0.75
    assert eng._pressure.threshold_percent == 0.75
    assert eng.threshold_tokens == 7_500


# ---------------------------------------------------------------------------
# 3. context.status events
# ---------------------------------------------------------------------------

def test_pressure_build_emits_pre_api_and_start_but_no_false_done(captured):
    eng = _engine()
    _arm_pressure(eng)
    # A real build path records `fired` in _apply_usage_pressure; emulate it.
    eng._apply_usage_pressure(history_budget=400)
    assert eng._pressure_fired_this_build is True

    pre_stats = eng._maybe_emit_compaction_start()
    kinds = [(t, p.get("phase")) for t, p in captured.events]
    assert ("context.status", "pre_api") in kinds
    assert ("context.status", "compress") in kinds
    start_payload = [p for t, p in captured.events if p.get("phase") == "compress"][0]
    assert start_payload["message"].startswith("🗜️ Compacting context")
    assert start_payload["thread_id"] == "s-status-test"

    # No-op pipeline: stats did not move, so the terminal edge stays silent.
    eng._maybe_emit_compaction_done(pre_stats)
    assert [p for _, p in captured.events if p.get("phase") == "compacted"] == []


def test_done_event_fires_only_when_pipeline_reclaimed(captured):
    eng = _engine()
    _arm_pressure(eng)
    pre_stats = eng._shaper.stats()
    eng._maybe_emit_compaction_done(pre_stats)
    assert captured.events == []  # nothing moved -> silence

    moved = dict(pre_stats, prunes=pre_stats.get("prunes", 0) + 1)
    eng._shaper._compactor.stats.update(moved) if eng._shaper._compactor else None
    if eng._shaper._compactor is None:
        # No compactor yet: seed a minimal fake with the exact surface
        # HistoryShaper.stats() reads (stats dict, summary, llm_suppressed).
        class _Fake:
            def __init__(self):
                self.stats = {"prunes": 1, "structural_compactions": 0, "llm_summary_calls": 0,
                              "llm_suppressed": 0, "ineffective_streak": 0, "summary_chars": 0,
                              "placeholders": 0, "placeholder_chars_reclaimed": 0}
                self.summary = ""
                self.llm_suppressed = False
        eng._shaper._compactor = _Fake()
    eng._maybe_emit_compaction_done(pre_stats)
    phases = [p.get("phase") for _, p in captured.events]
    assert "compacted" in phases
    done_payload = [p for _, p in captured.events if p.get("phase") == "compacted"][0]
    assert done_payload["message"].startswith("✓ Context compaction complete")


def test_silent_engines_emit_nothing(captured, monkeypatch):
    eng = _engine()
    eng.emit_automatic_compaction_status = False
    _arm_pressure(eng)
    eng._apply_usage_pressure(history_budget=400)
    stats = eng._maybe_emit_compaction_start()
    eng._maybe_emit_compaction_done(stats)
    assert captured.events == []  # routine statuses suppressed by contract


def test_overflow_blocked_warns_once_per_episode(captured, monkeypatch):
    eng = _engine()
    _arm_pressure(eng, window=1000, prompt=900)  # 90% of the window
    eng._apply_usage_pressure(history_budget=400)
    monkeypatch.setenv("PULSEAI_COMPACTION", "off")

    trimmed = eng._compact_history([], 400)
    eng._warn_overflow_if_blocked(trimmed, history_budget=400)
    warnings = [p for _, p in captured.events if p.get("severity") == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["phase"] == "overflow_blocked"
    assert "PULSEAI_COMPACTION=off" in warnings[0]["message"]

    # Same episode again: latched — no duplicate toast.
    eng._warn_overflow_if_blocked(trimmed, history_budget=400)
    assert len([p for _, p in captured.events if p.get("severity") == "warning"]) == 1

    # Episode re-arms (usage relaxes <=60%): the latch clears.
    eng.update_from_response({"prompt_tokens": 100, "completion_tokens": 5})
    eng._warn_overflow_if_blocked(trimmed, history_budget=400)
    assert len([p for _, p in captured.events if p.get("severity") == "warning"]) == 1


def test_healthy_compaction_never_warns(captured, monkeypatch):
    """Pressure active but compaction keeps history under budget: silence."""
    eng = _engine()
    _arm_pressure(eng)
    eng._apply_usage_pressure(history_budget=400)
    monkeypatch.delenv("PULSEAI_COMPACTION", raising=False)

    class _Tiny:
        type = "system"
        content = "tiny"
        additional_kwargs = {}
        response_metadata = {}

    eng._warn_overflow_if_blocked([_Tiny()], history_budget=100_000)
    assert captured.events == []


# ---------------------------------------------------------------------------
# 4. Bridge projection
# ---------------------------------------------------------------------------

def test_bridge_projects_context_status():
    from src.bridge.__main__ import BridgeServer
    from src.runtime.identity import TurnIdentity

    identity = TurnIdentity.create(session_id="session-x", workspace=".")
    event = {
        "type": "context.status",
        "event_id": "evt-1",
        "timestamp": 1.0,
        "payload": {
            "thread_id": "session-x",
            "phase": "compress",
            "severity": "info",
            "message": "🗜️ Compacting context",
            "usage_percent": 80.0,
        },
    }
    frame = BridgeServer._project_event(event, identity)
    assert frame is not None
    assert frame["type"] == "context_status"
    assert frame["phase"] == "compress"
    assert frame["message"].startswith("🗜️")
    assert frame["session_id"] == identity.session_id
    assert frame["event_id"] == "evt-1"

    # Replay path: stored rows project too, so a resumed session keeps the history.
    stored = BridgeServer._project_stored_event({
        "type": "context_status", "event_id": "evt-2", "timestamp": 2.0,
        "session_id": "session-x",
        "payload": {"phase": "compacted", "message": "✓ done"},
    })
    assert stored is not None and stored["type"] == "context_status"

    # Unknown kinds still drop (the forwarder's contract).
    assert BridgeServer._project_event({"type": "mystery"}, identity) is None


def test_templates_match_the_captured_hermes_wording():
    """The marker phrase is load-bearing (gateway filters couple to it)."""
    assert "Compacting context" in ContextEngine.COMPACTION_START_STATUS
    assert ContextEngine.COMPACTION_DONE_STATUS.startswith("✓")
    assert "Pre-API compression" in ContextEngine.PRE_API_COMPRESSION_STATUS_TEMPLATE.format(tokens=1234)
