# Context Engine P7 — Feedback-Learning Extraction (Second Modularization Cut)

**Date:** 2026-08-31
**Scope:** `src/context/feedback_memory.py` (new), `src/context/context_engine.py` (feedback loop extracted), new `src/tests/test_feedback_memory.py` (14 behavior contracts)
**Sources:** `docs/CONTEXT_ENGINE_P6_EVENTS_MODULAR.md` (extraction template), `src/tests/test_session_engines.py` (the proven data-loss history this store exists to prevent), `AGENT_STARTUP_REVIEW.md` (Week-3 god-file split)

## 1. What moved

The feedback-learning loop — "after each task, record what layers were
actually sent, and nudge their relevance weights by observed
success/failure" — moved out of `context_engine.py` into
`src/context/feedback_memory.py::FeedbackMemory`:

| Concern | Owner now |
|---|---|
| JSONL store path (incl. legacy `context_feedback.json` migration) | `FeedbackMemory` |
| Load with debris tolerance (corrupt interleave lines skipped) | `FeedbackMemory` |
| Append-only single-line persistence (O_APPEND; the full-file rewrite was retired after two interleaved engines lost a row — `test_session_engines.py`) | `FeedbackMemory` |
| In-memory rotation (300 → 150) and file compaction (2000 → 1000, atomic temp-file replace, newest tail kept) | `FeedbackMemory` |
| Learned-weight nudge (≥10 records, ≥5 samples/layer, boost ×1.03 > 0.70 success, demote ×0.97 < 0.40, cap 1.0 / floor 0.0, all task types) | `FeedbackMemory.apply_learned_weights(dict, task_types)` |
| The `LAYER_RELEVANCE` dict itself | **still the engine** — the layer builders read it directly; the module only mutates it in place |
| Attribution snapshot (`_last_layers_sent` vs `_layer_cache` fallback) | **still the engine** — it is build state, not store state |
| Thread-safety | **still the engine's `_api_lock`** — `record_feedback` is unchanged as a public entry |

Surface preservation follows the P6 template: delegating properties
(`_feedback_history`, `_feedback_path`, `_legacy_feedback_path`) plus
class-attribute aliases (`_FEEDBACK_COMPACT_AT/TO` → module constants,
single source of truth in the module). The module reads its path and
history live on every operation — tests re-point `_feedback_path` and
reset `_feedback_history` **after** construction, and that keeps working.

`ContextEngine.__init__` is now `self._feedback = FeedbackMemory();
self._feedback.load()` — the constructor stays I/O-light (one store read,
best-effort, exactly as before).

## 2. Bug hardening found while extracting

The pre-extraction nudge loop read weights defensively
(`LAYER_RELEVANCE.get(layer_name, {}).get(task_type, 0.5)`) but WROTE
eagerly (`LAYER_RELEVANCE[layer_name][task_type] = ...`). A feedback row
naming a layer missing from the relevance map (renamed layer, built-in
swap, or the `_infer_layer_name` → `"unknown"` degradation path) with
≥5 attributed samples and a past-threshold success rate would therefore
**KeyError out of `record_feedback`** — i.e., take the turn's
finalization node down over learning bookkeeping. The module's contract
is "learning data must never block the graph", so unknown layers are now
skipped. This is the only behavioral delta, and it is in the safe
direction (a crash → a skipped nudge).

## 3. Verification (provider-free — zero LLM spend, zero tokens)

```bash
# new module contracts
.venv/bin/python -m pytest src/tests/test_feedback_memory.py -q
# the store's regression history (excluded from the default command on
# purpose, but this is exactly the area P7 touched)
.venv/bin/python -m pytest src/tests/test_session_engines.py -q
# engine surface consumers
.venv/bin/python -m pytest src/tests/test_engine_smoke.py \
  src/tests/test_compaction.py src/tests/test_prompt_cache_audit.py \
  src/tests/test_review_autopsy_fixes.py src/tests/test_review12_reverify.py -q
# full suite (README command)
.venv/bin/python -m pytest src/tests -q \
  --ignore=src/tests/test_session_engines.py --basetemp=/tmp/pulseai-pytest
```

| Run | Result |
|---|---|
| Feedback-memory contracts (new) | **14 passed** |
| `test_session_engines.py` (data-loss regressions, incl. compaction-bound test via the new aliases) | **all passed** |
| Engine-surface consumers (smoke, compaction, audit, autopsy, review12) | **all passed** |
| Full suite (README command) | see section 4 |

## 4. Full-suite result

Clean run (no concurrent test processes):

```text
6 failed, 1070 passed, 3 skipped in 216.41s
```

The 6 failures are IDENTICAL to the documented pre-existing baseline (P3
doc §3): 5× tests reading the deleted `ui/` catalog
(`ui/src/runtime/toolCatalog.ts` absent from the tree) + 1×
`test_autonomous_runtime_contract.py::test_ai_node_builds_expected_first_sarvam_request_without_provider_call`.
**Zero regressions; +14 = the new feedback-memory contracts** (1056 →
1070 passed vs the P6 run). `test_session_engines.py` (excluded from the
default command) passes 19/19 in isolation.

## 5. Honest limits (not claimed)

* **Second cut of many.** The god file is down by ~120 net lines; the
  layer builders and history-compaction cuts remain, each needing its own
  auditable commit.
* **Weight learning is still heuristic.** The nudge factors (×1.03 /
  ×0.97, dead band 0.40–0.70) are unchanged; P7 moved the mechanism, it
  did not retune it.
* **The store is per-`HOME`.** All engines of all sessions in a process
  (and dashboard/CLI processes sharing the user) share one store file —
  by design (cross-session learning), which is precisely why the
  append-only + debris-tolerant design is pinned by
  `test_session_engines.py`.
