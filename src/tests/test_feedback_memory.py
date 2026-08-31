"""
Feedback Memory contracts (P7 extraction)
=========================================
Run: python -m pytest src/tests/test_feedback_memory.py -q

Behavior contracts for the extracted feedback-learning loop
(``src/context/feedback_memory.py``) — the same append-only JSONL store and
learned-weight nudge the layered engine uses, pinned where it now lives:

* legacy migration, debris tolerance, tail compaction, in-memory rotation
* learned weights: thresholds, sample gates, boost/demote direction,
  in-place mutation of the engine's relevance dict
* exactly-one-line-per-record appends (the retired full-file rewrite lost
  data under interleaved session engines — see test_session_engines.py)
* best-effort I/O: a broken store must never raise into boot or the graph

Provider-free, zero LLM spend.
"""
import json
import os
import pytest

from src.context import feedback_memory as fbm
from src.context.feedback_memory import FeedbackMemory
from src.context.context_engine import ContextEngine, TaskType


def _relevance() -> dict:
    """Fresh per-instance-style relevance dict (as the engine deep-copies)."""
    return {
        "good_layer": {t: 0.5 for t in TaskType},
        "bad_layer": {t: 0.5 for t in TaskType},
        "quiet_layer": {t: 0.5 for t in TaskType},
    }


def _records(n: int, layers, success: bool) -> list:
    return [
        {"timestamp": i, "task": f"t{i}", "success": success, "layers_used": layers}
        for i in range(n)
    ]


class TestStore:
    def test_legacy_json_array_is_migrated_and_parked(self, tmp_path):
        legacy = tmp_path / "context_feedback.json"
        legacy.write_text(json.dumps([{"task": "a"}, {"task": "b"}]), encoding="utf-8")
        store = FeedbackMemory(path=str(tmp_path / "context_feedback.jsonl"),
                               legacy_path=str(legacy))
        store.load()

        assert [r["task"] for r in store.history] == ["a", "b"]
        assert legacy.exists() is False
        assert (tmp_path / "context_feedback.json.bak").exists()
        lines = (tmp_path / "context_feedback.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2  # now JSONL

    def test_debris_lines_are_skipped_and_good_rows_kept(self, tmp_path):
        p = tmp_path / "fb.jsonl"
        p.write_text(
            json.dumps({"task": "ok", "success": True}) + "\n"
            + "{corrupt debris from a cross-process interleave" + "\n"
            + "\n"
            + json.dumps({"task": "also-ok", "success": False}) + "\n",
            encoding="utf-8",
        )
        store = FeedbackMemory(path=str(p))
        store.load()
        assert [r["task"] for r in store.history] == ["ok", "also-ok"]

    def test_compaction_keeps_the_newest_tail(self, tmp_path):
        p = tmp_path / "fb.jsonl"
        n = fbm.FEEDBACK_COMPACT_AT + 50
        p.write_text(
            "".join(json.dumps({"task": f"t{i}"}) + "\n" for i in range(n)),
            encoding="utf-8",
        )
        store = FeedbackMemory(path=str(p))
        store.load()

        keep = fbm.FEEDBACK_COMPACT_TO
        assert len(store.history) == keep
        lines = p.read_text().strip().splitlines()
        assert len(lines) == keep, "file was not actually rewritten"
        assert json.loads(lines[0])["task"] == f"t{n - keep}"

    def test_in_memory_history_rotates_but_the_file_keeps_every_row(
        self, tmp_path
    ):
        """In-memory history rotates past MAX_HISTORY -> ROTATE_TO, while
        the append-only file keeps every row (until the load-time
        FEEDBACK_COMPACT_AT compaction — a different, file-side bound)."""
        p = tmp_path / "fb.jsonl"
        store = FeedbackMemory(path=str(p))
        rel = _relevance()
        for i in range(fbm.MAX_HISTORY + 1):
            store.record({"timestamp": i, "task": f"t{i}", "success": True,
                          "layers_used": ["good_layer"]}, rel, TaskType)

        assert len(store.history) == fbm.ROTATE_TO  # in-memory rotated
        assert len(p.read_text().strip().splitlines()) == fbm.MAX_HISTORY + 1

    def test_record_appends_exactly_one_line(self, tmp_path):
        p = tmp_path / "fb.jsonl"
        store = FeedbackMemory(path=str(p))
        rel = _relevance()
        store.record({"timestamp": 1, "task": "one", "success": True,
                      "layers_used": ["good_layer"]}, rel, TaskType)
        store.record({"timestamp": 2, "task": "two", "success": True,
                      "layers_used": ["good_layer"]}, rel, TaskType)
        lines = p.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1])["task"] == "two"

    def test_broken_store_never_raises(self, tmp_path):
        # parent is a FILE -> makedirs/open must fail; record swallows it
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        store = FeedbackMemory(path=str(blocker / "fb.jsonl"))
        store.load()  # no raise
        store.record({"timestamp": 1, "task": "t", "success": True,
                      "layers_used": ["l"]}, _relevance(), TaskType)  # no raise
        store.append({"task": "t2"})  # no raise


class TestLearnedWeights:
    def test_below_min_records_no_learning(self):
        store = FeedbackMemory(path="/nonexistent-dir-xyz/fb.jsonl")
        store.history = _records(9, ["good_layer"], True)
        rel = _relevance()
        before = rel["good_layer"][TaskType.CHAT]
        store.apply_learned_weights(rel, TaskType)
        assert rel["good_layer"][TaskType.CHAT] == before

    def test_below_min_samples_no_learning(self):
        store = FeedbackMemory(path="/nonexistent-dir-xyz/fb.jsonl")
        store.history = _records(10, ["good_layer"], True) + [
            {"task": "x", "success": True, "layers_used": ["quiet_layer"]}
            for _ in range(4)  # only 4 samples for quiet_layer
        ]
        rel = _relevance()
        before = rel["quiet_layer"][TaskType.CHAT]
        store.apply_learned_weights(rel, TaskType)
        assert rel["quiet_layer"][TaskType.CHAT] == before

    def test_reliable_layer_boosted_unreliable_demoted_mid_is_untouched(self):
        store = FeedbackMemory(path="/nonexistent-dir-xyz/fb.jsonl")
        # good: 10/10 success (rate 1.0 > 0.70) -> boost
        # bad: 0/10 success (rate 0.0 < 0.40) -> demote
        # quiet: 5/10 (rate 0.5, in the dead band) -> untouched
        store.history = (
            _records(10, ["good_layer"], True)
            + _records(10, ["bad_layer"], False)
            + _records(5, ["quiet_layer"], True)
            + _records(5, ["quiet_layer"], False)
        )
        rel = _relevance()
        store.apply_learned_weights(rel, TaskType)

        assert rel["good_layer"][TaskType.CHAT] == pytest.approx(0.5 * 1.03)
        assert rel["bad_layer"][TaskType.CHAT] == pytest.approx(0.5 * 0.97)
        assert rel["quiet_layer"][TaskType.CHAT] == 0.5
        # every task type gets the same nudge
        assert all(rel["good_layer"][t] == rel["good_layer"][TaskType.CHAT]
                   for t in TaskType)

    def test_boost_caps_at_one_and_demote_stays_non_negative(self):
        store = FeedbackMemory(path="/nonexistent-dir-xyz/fb.jsonl")
        store.history = _records(12, ["good_layer"], True) + _records(12, ["bad_layer"], False)
        rel = {
            "good_layer": {t: 0.99 for t in TaskType},   # 0.99*1.03 > 1.0 -> capped
            "bad_layer": {t: 0.001 for t in TaskType},   # multiplicative demote, floored at 0
        }
        store.apply_learned_weights(rel, TaskType)
        assert rel["good_layer"][TaskType.CHAT] == 1.0
        assert rel["bad_layer"][TaskType.CHAT] == pytest.approx(0.001 * 0.97)
        assert rel["bad_layer"][TaskType.CHAT] >= 0.0

    def test_unknown_layer_is_skipped_not_a_keyerror(self):
        """Pre-extraction, a feedback row naming a layer missing from the
        relevance map (renamed/built-in swap) KeyErrored the turn's
        finalization. The module skips it — learning must never block."""
        store = FeedbackMemory(path="/nonexistent-dir-xyz/fb.jsonl")
        store.history = _records(12, ["ghost_layer"], True)
        rel = _relevance()
        store.apply_learned_weights(rel, TaskType)  # must not raise
        assert "ghost_layer" not in rel
        assert rel["good_layer"][TaskType.CHAT] == 0.5

    def test_missing_success_field_is_not_attributed(self):
        store = FeedbackMemory(path="/nonexistent-dir-xyz/fb.jsonl")
        store.history = [
            {"task": f"t{i}", "layers_used": ["good_layer"]} for i in range(20)
        ]  # no "success" key at all
        rel = _relevance()
        store.apply_learned_weights(rel, TaskType)
        assert rel["good_layer"][TaskType.CHAT] == 0.5


class TestEngineSurface:
    """The engine's documented surface still routes to the module."""

    def test_engine_aliases_point_at_module_constants(self):
        assert ContextEngine._FEEDBACK_COMPACT_AT == fbm.FEEDBACK_COMPACT_AT
        assert ContextEngine._FEEDBACK_COMPACT_TO == fbm.FEEDBACK_COMPACT_TO

    def test_engine_delegates_path_history_and_record(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))  # keep the real ~/.pulseai clean
        eng = ContextEngine(max_tokens=4000, model="gpt-4o", probe_window=False)

        target = tmp_path / "eng.jsonl"
        eng._feedback_path = str(target)  # re-point AFTER construction
        eng._feedback_history = []
        eng._last_layers_sent = ["task", "repo_map"]
        eng.record_feedback(True, task="pin")

        row = json.loads(target.read_text().strip().splitlines()[-1])
        assert row["task"] == "pin"
        assert row["success"] is True
        assert set(row["layers_used"]) == {"task", "repo_map"}
        assert eng._feedback_history[-1] is row or eng._feedback_history[-1] == row
