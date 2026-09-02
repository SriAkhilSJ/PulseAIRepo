"""The receipt must name each bound on its own terms, and must not invent a link between them.

Owner's host, 2026-09-02: `hi` came back as `workspace exceeds scan budget — bounded by design`. That line is
true and it is about FILES: `context_engine.py:1031` constructs `ContextBudget()` with no arguments, so the walk
gets 1,000 entries to consider, 1,000 files, 16 MiB and 5 seconds, and a repo larger than that trips it while
preparing context. `PulseAIRepo` (with `desktop/vscode` under it) trips it immediately.

A separate, real defect sat next to it: `LLM_MODEL=auto` resolved no window, so the engine ran on the 8,192
fallback and `PROVIDER_SAFE_LIMIT` pinned `max_tokens` at 4,096 -- wrong for the token budgets, and invisible in
the receipt. An earlier revision of this code appended that window note to whichever reason fired, which made
the assumed window look like the cause of a file-count bound. It was not, and saying so was my error.

So these tests assert three things: the base string stays byte-identical (the benchmark contract counts this
receipt by its reason), each clause carries its own numbers, and the scan clause states explicitly that the
window is not its cause.
"""
from __future__ import annotations

import pytest

LEGACY = "workspace exceeds scan budget — bounded by design"


class _Pool:
    """Just enough of a scan pool for the receipt path.

    `__getattr__` answers 0 for the many other accounting fields the payload reads, so this fake asserts
    the reason string without pinning every metric the receipt happens to carry today -- those are
    somebody else's contract. The four fields the walk clause reads are set explicitly, because asserting
    "0 files" would pass against any wording.
    """

    def __init__(self) -> None:
        self.max_considered = 1_000
        self.max_files = 1_000
        self.max_bytes = 16 * 1024 * 1024
        self.max_elapsed = 5.0
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


def _engine(source: str, *, oversized: bool = True):
    try:
        from src.context.context_engine import ContextEngine
    except ModuleNotFoundError as exc:  # pragma: no cover - host gap, never a pass
        pytest.skip(f"engine not importable on this host: {exc}")

    engine = ContextEngine.__new__(ContextEngine)
    engine.context_window_source = source
    engine.context_window = 8_192
    engine.max_tokens = 4_096
    engine.context_budget = 1_638
    engine._active_pool = _Pool()
    engine._active_thread_id = "test-thread"
    engine._active_workspace = "."
    engine._by_design_receipt_emitted = False
    engine._workspace_exceeds_budget = lambda *args, **kwargs: oversized
    return engine


def test_assumed_window_is_stated_with_its_own_numbers():
    engine = _engine("default")
    engine._emit_build_receipt()
    reason = engine._active_pool.payloads[0]["reason"]
    assert reason.startswith(LEGACY), "the contract string stays the prefix the harness counts"
    assert "assumed window of 8,192" in reason, reason
    assert "max_tokens 4,096" in reason and "context budget 1,638" in reason, reason
    assert "Naming LLM_MODEL" in reason and "LLM_CONTEXT_WINDOW" in reason, "name the cure, not just the number"


def test_the_scan_clause_reports_the_walk_bound_it_actually_hit():
    engine = _engine("explicit")
    engine._emit_build_receipt()
    reason = engine._active_pool.payloads[0]["reason"]
    assert "walk bound: 1,000 entries to consider, 1,000 files, 16 MiB, 5.0s" in reason, reason
    assert "independent of the model window" in reason, (
        "the whole point: a file-count ceiling must not be blamed on the context window"
    )
    assert "assumed window" not in reason, "a resolved window gets no editorial at all"


def test_a_truncated_build_says_nothing_about_scan_bounds():
    """Truncation is its own reason; the walk clause belongs to the by-design case only."""

    engine = _engine("explicit")
    engine._active_pool.truncated = True
    engine._emit_build_receipt()
    reason = engine._active_pool.payloads[0]["reason"]
    assert "walk bound" not in reason, reason


def test_no_workspace_bound_no_receipt_at_all():
    engine = _engine("default", oversized=False)
    engine._emit_build_receipt()
    assert engine._active_pool.payloads == [], (
        "nothing was bounded, so nothing may be claimed: this is where a fabricated receipt would appear"
    )


def test_still_one_receipt_per_session_with_the_added_text():
    engine = _engine("default")
    engine._emit_build_receipt()
    engine._emit_build_receipt()
    assert len(engine._active_pool.payloads) == 1, "count==1 is a benchmark contract, not a preference"
