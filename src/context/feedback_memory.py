"""P7: the feedback-learning loop, extracted from the layered engine.

The engine learns which context layers actually helped: after each task it
records one row (task, success, layers USED in the final build) into an
append-only JSONL store, and nudges its per-layer relevance weights up for
reliably-useful layers and down for reliably-useless ones.

Extracted behavior-preserved from ``context_engine.py`` (see
``docs/CONTEXT_ENGINE_P6_EVENTS_MODULAR.md`` for the template):

* **Append-only store.** One line per record, ``O_APPEND``. Session-scoped
  engines (and the dashboard + CLI processes) never overwrite each other's
  rows — the retired full-file rewrite lost data when two engines
  interleaved (proven in ``test_session_engines.py``). Readers skip debris
  lines defensively.
* **One-time migration** from the legacy full-rewrite JSON array store
  (legacy file renamed to ``*.bak`` after a successful copy).
* **Tail rotation.** In-memory history rotates past 300 -> 150; the file
  compacts past ``FEEDBACK_COMPACT_AT`` (2000) down to
  ``FEEDBACK_COMPACT_TO`` (1000) via an atomic temp-file replace, keeping
  the TAIL (most recent = most informative for the learned weights).
* **Learned weights.** With >=10 records, each layer with >=5 attributed
  samples is boosted (x1.03, cap 1.0) above a 0.70 success rate and demoted
  (x0.97, floor 0.0) below 0.40 — for every task type. The relevance dict
  itself stays engine-owned (the layer builders read it directly); this
  module only owns the persistence + the nudge computation.

Everything here is best-effort by design: any I/O failure is swallowed so
learning data can never block boot or the graph.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

FEEDBACK_COMPACT_AT = 2000
FEEDBACK_COMPACT_TO = 1000
# In-memory history rotation (keeps the working set small; the FILE keeps
# the full tail up to FEEDBACK_COMPACT_TO).
MAX_HISTORY = 300
ROTATE_TO = 150
# Learning thresholds (unchanged from the engine).
MIN_RECORDS_FOR_LEARNING = 10
MIN_LAYER_SAMPLES = 5
BOOST_THRESHOLD = 0.70
DEMOTE_THRESHOLD = 0.40
BOOST_FACTOR = 1.03
DEMOTE_FACTOR = 0.97


def default_feedback_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".pulseai", "context_feedback.jsonl")


def default_legacy_feedback_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".pulseai", "context_feedback.json")


class FeedbackMemory:
    """Owns the JSONL feedback store and the learned-weight nudge.

    ``path``/``legacy_path`` are plain mutable attributes on purpose: the
    engine exposes them (and tests re-point them at tmp dirs) AFTER
    construction, so every operation reads the current value live.
    """

    def __init__(
        self,
        path: Optional[str] = None,
        legacy_path: Optional[str] = None,
    ) -> None:
        self.path: str = path or default_feedback_path()
        self.legacy_path: str = legacy_path or default_legacy_feedback_path()
        self.history: List[dict] = []

    # -- load / migration ----------------------------------------------------

    def load(self) -> None:
        """Load history at boot (legacy migration first). Never raises."""
        self._migrate_legacy()
        self._read_store()

    def _migrate_legacy(self) -> None:
        # One-time migration from the legacy full-rewrite JSON array store.
        if not os.path.exists(self.path) and os.path.exists(self.legacy_path):
            try:
                with open(self.legacy_path, "r", encoding="utf-8") as f:
                    legacy = json.load(f)
                if isinstance(legacy, list):
                    os.makedirs(os.path.dirname(self.path), exist_ok=True)
                    with open(self.path, "w", encoding="utf-8") as f:
                        for record in legacy:
                            f.write(json.dumps(record) + "\n")
                    os.replace(self.legacy_path, self.legacy_path + ".bak")
            except Exception:
                pass  # learning data must never block boot

    def _read_store(self) -> None:
        if not os.path.exists(self.path):
            return
        history: List[dict] = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # debris from a cross-process interleave: skip, keep the rest
                    if isinstance(record, dict):
                        history.append(record)
        except Exception:
            return
        self.history = history
        self.compact_if_needed()

    # -- recording -----------------------------------------------------------

    def record(self, profile: dict, layer_relevance: Dict[str, Dict[Any, float]],
               task_types: Iterable[Any]) -> None:
        """One completed task: append the row, learn, persist exactly one
        line. Order matters and is preserved from the engine: in-memory
        append+rotate -> learned weights -> file append."""
        self.history.append(profile)
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[-ROTATE_TO:]
        self.apply_learned_weights(layer_relevance, task_types)
        self.append(profile)

    def append(self, profile: dict) -> None:
        """Append ONE record line. O_APPEND means concurrent session engines
        (and the dashboard + CLI processes) never overwrite each other's
        rows — unlike the retired full-file rewrite."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(profile) + "\n")
        except Exception:
            pass  # feedback is best-effort; never block the graph

    # -- compaction ----------------------------------------------------------

    def compact_if_needed(self) -> None:
        """Compaction bounds boot-time load cost; rotation keeps the tail
        (most recent = most informative for the learned weights)."""
        if len(self.history) <= FEEDBACK_COMPACT_AT:
            return
        self.history = self.history[-FEEDBACK_COMPACT_TO:]
        try:
            tmp = f"{self.path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for record in self.history:
                    f.write(json.dumps(record) + "\n")
            os.replace(tmp, self.path)  # atomic on POSIX + Windows
        except Exception:
            pass  # worst case: file stays long; never block boot

    # -- learning ------------------------------------------------------------

    def apply_learned_weights(
        self,
        layer_relevance: Dict[str, Dict[Any, float]],
        task_types: Iterable[Any],
    ) -> None:
        """Nudge the engine's LAYER_RELEVANCE based on historical
        success/failure. The dict is mutated in place (the layer builders
        read it directly from the engine)."""
        if len(self.history) < MIN_RECORDS_FOR_LEARNING:
            return

        layer_stats: Dict[str, dict] = defaultdict(lambda: {"success": 0, "failure": 0})

        for record in self.history:
            if record.get("success") is None:
                continue
            for layer_name in record.get("layers_used", []):
                key = "success" if record["success"] else "failure"
                layer_stats[layer_name][key] += 1

        for layer_name, stats in layer_stats.items():
            total = stats["success"] + stats["failure"]
            if total < MIN_LAYER_SAMPLES:
                continue
            success_rate = stats["success"] / total
            # Unknown/relocated layers (a layer a feedback row references
            # that no longer exists in the relevance map) have nothing to
            # nudge — skip. The pre-extraction engine would KeyError here
            # and take the turn's finalization node down with it; this
            # module's contract is "never block the graph".
            entry = layer_relevance.get(layer_name)
            if entry is None:
                continue
            # Boost layers with >70% success, demote <40%
            for task_type in task_types:
                current = entry.get(task_type, 0.5)
                if success_rate > BOOST_THRESHOLD:
                    entry[task_type] = min(1.0, current * BOOST_FACTOR)
                elif success_rate < DEMOTE_THRESHOLD:
                    entry[task_type] = max(0.0, current * DEMOTE_FACTOR)


def make_profile(
    success: bool,
    task: Optional[str],
    layers_used: Optional[List[str]],
    now: Optional[float] = None,
) -> dict:
    """Shape of one feedback row (kept here so the engine's only job is to
    supply the attribution snapshot)."""
    return {
        "timestamp": now if now is not None else time.time(),
        "task": task or "",
        "success": success,
        "layers_used": layers_used or [],
    }
