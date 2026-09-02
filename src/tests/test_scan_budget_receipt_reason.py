"""The by-design receipt must name its own cause when the cause is a config guess.

Owner's host, 2026-09-02: `hi` came back as `workspace exceeds scan budget — bounded by design`, which reads
as a product limit. The real chain was `LLM_MODEL=auto` -> no entry in `src/context/model_budgets.py` ->
fallback window 8,192 -> `PROVIDER_SAFE_LIMIT` pinning `max_tokens` to 4,096 -> `context_budget` ~1,638 ->
a scan ceiling no ordinary repo can fit under. The bound was correct; the *number* was an assumption, and
the receipt said nothing about it, so the finding cost a round of investigation.

Two properties, both executed: the base reason string stays byte-identical (the benchmark contract counts
this receipt by its reason), and the cause rides behind it only when the window was never resolved.
"""
from __future__ import annotations

import pytest

LEGACY = "workspace exceeds scan budget — bounded by design"


class _Pool:
    """Just enough of a scan pool for the receipt path.

    `__getattr__` answers 0 for the many other accounting fields the payload reads, so this fake asserts
    the reason string without pinning every metric the receipt happens to carry today -- those are
    somebody else's contract.
    """

    def __init__(self) -> None:
        self.max_considered = 400
        self.truncated = False
        self.cancelled = False
        self.payloads: list[dict] = []

    def __getattr__(self, name: str):
        if name.startswith("payloads"):
            raise AttributeError(name)
        return 0

    def component_summaries(self):
        return []

    def emit_degraded(self, payload: dict) -> None:
        self.payloads.append(payload)


def _engine(source: str):
    try:
        from src.context.context_engine import ContextEngine
    except ModuleNotFoundError as exc:  # pragma: no cover - host gap, never a pass
        pytest.skip(f"engine not importable on this host: {exc}")

    engine = ContextEngine.__new__(ContextEngine)
    engine.context_window_source = source
    engine.context_window = 8_192
    engine.max_tokens = 4_096
    engine._active_pool = _Pool()
    engine._active_thread_id = "test-thread"
    engine._active_workspace = "."
    engine._by_design_receipt_emitted = False
    # The probe itself is covered elsewhere; here the question is only what the receipt says.
    engine._workspace_exceeds_budget = lambda *args, **kwargs: True
    return engine


def test_an_assumed_window_is_stated_in_the_receipt():
    engine = _engine("default")
    engine._emit_build_receipt()
    payload = engine._active_pool.payloads[0]
    reason = payload["reason"]
    assert reason.startswith(LEGACY), "the contract string stays the prefix the harness counts"
    assert "8,192 assumed" in reason and "token budget 4,096" in reason, reason
    assert "Naming LLM_MODEL" in reason and "LLM_CONTEXT_WINDOW" in reason, "name the knobs, not just the number"


def test_a_resolved_window_leaves_the_reason_byte_identical():
    for source in ("explicit", "update-model", "provider-cap"):
        engine = _engine(source)
        engine._emit_build_receipt()
        assert engine._active_pool.payloads[0]["reason"] == LEGACY, (
            f"when the window is real ({source}), the receipt must not editorialise"
        )


def test_still_one_receipt_per_session_with_the_added_text():
    engine = _engine("default")
    engine._emit_build_receipt()
    engine._emit_build_receipt()
    assert len(engine._active_pool.payloads) == 1, "count==1 is a benchmark contract, not a preference"
