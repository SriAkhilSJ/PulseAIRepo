# Context Engine P8 — History-Shaping Extraction (Third Modularization Cut)

**Date:** 2026-08-31
**Scope:** `src/context/history_shaper.py` (new), `src/context/context_engine.py` (history pipeline extracted), new `src/tests/test_history_shaper.py` (10 behavior contracts)
**Sources:** `docs/CONTEXT_ENGINE_P6_EVENTS_MODULAR.md` + `docs/CONTEXT_ENGINE_P7_FEEDBACK_MEMORY.md` (extraction template + surface-preservation rule), `AGENT_STARTUP_REVIEW.md` (Week-3 god-file split)

## 1. What moved

The history-shaping pipeline — everything the engine does to raw
conversation history before it reaches the model — moved out of
`context_engine.py` into `src/context/history_shaper.py::HistoryShaper`:

| Concern | Owner now |
|---|---|
| Tool-output summarization (`_summarize_tool_messages` → `SmartSummarizer`) | `HistoryShaper.summarize_tool_messages` |
| D22 prune-first compaction (protected head/tail, structural drop only while over budget, iterative AUX summary, anti-thrash; `PULSEAI_COMPACTION=off` kill switch incl. landed-mutation omission) | `HistoryShaper.compact` |
| Turn-atomic budget trim (P4 pairing guard: never starts on a ToolMessage, pairs never split) | `HistoryShaper.trim` |
| Per-session compaction telemetry (`compaction_stats` / `get_status()["compaction"]`) | `HistoryShaper.stats` |
| The ONE per-session `HistoryCompactor` (shared by the per-turn path and the ABC `compress()` entry — one anti-thrash state) | `HistoryShaper.ensure_compactor` / `.compactor` |
| The engine's model / inference policy / current task / session identity / window | **getters** — never captured values |

The engine keeps the documented method names as thin delegations
(`_summarize_tool_messages`, `_compact_history`, `_trim_history`,
`compaction_stats`, `_ensure_compactor`) plus a read-only `_compactor`
property — the pre-P8 tests monkeypatch `eng._trim_history` on the
instance and read `eng._compactor`, and both keep working unchanged.

### Why getters, not values

The engine's `model` mutates mid-life (`update_model` /
`reconfigure_model` re-point it), `_current_task` moves per build, and
`_active_thread_id` is re-stamped per build for dashboard turns. A shaper
that captured `self.model` at construction would silently keep
token-counting with a **dead model** after a mid-session reconfigure.
`HistoryShaper` therefore takes six zero-arg getters, and the pinned
contracts prove it: a model getter that changes before first use creates
the compactor with the FRESH model, and a session getter that changes
between `ensure_compactor()` calls re-stamps the live compactor's
`_session_id`.

### Kill-switch seam

`compact(history, budget, kill_switch_trim=None)`: on the
`PULSEAI_COMPACTION=off` path the engine passes its own bound
`_trim_history`, so the legacy structural pipeline stays on the engine's
**public seam** — the pre-P8 kill-switch regression test
(`test_compaction.py::test_engine_compact_history_kill_switch`, which
monkeypatches `eng._trim_history` and asserts the no-compactor behavior)
passes unmodified, and any future engine-level override of trim is
respected rather than bypassed.

## 2. Verification (provider-free — zero LLM spend, zero tokens)

```bash
# new shaper contracts
.venv/bin/python -m pytest src/tests/test_history_shaper.py -q
# the areas P8 touched
.venv/bin/python -m pytest src/tests/test_compaction.py \
  src/tests/test_event_safety.py src/tests/test_context_engine_parity.py \
  src/tests/test_engine_smoke.py src/tests/test_session_engines.py \
  src/tests/test_context_budget.py -q
# full suite (README command)
.venv/bin/python -m pytest src/tests -q \
  --ignore=src/tests/test_session_engines.py --basetemp=/tmp/pulseai-pytest
```

| Run | Result |
|---|---|
| History-shaper contracts (new) | **10 passed** |
| Touched areas (compaction + event safety + parity + smoke + session engines + context budget) | **138 passed, 1 skipped** |
| Full suite (README command, clean run) | see section 3 |

## 3. Full-suite result

```text
6 failed, 1080 passed, 3 skipped in 209.74s
```

The 6 failures are IDENTICAL to the documented pre-existing baseline (P3
doc §3): 5× tests reading the deleted `ui/` catalog + 1×
`test_autonomous_runtime_contract.py::test_ai_node_builds_expected_first_sarvam_request_without_provider_call`.
**Zero regressions; +10 = the new shaper contracts** (1070 → 1080 passed
vs the P7 run). `test_session_engines.py` (excluded from the default
command) passes 19/19.

## 4. Modularization series so far

| Cut | Module | Engine delta |
|---|---|---|
| P6 | `usage_pressure.py` (P3 state machine) | −~120 net |
| P7 | `feedback_memory.py` (feedback loop) | −~110 net |
| P8 | `history_shaper.py` (history pipeline) | −~70 net |

Remaining large units in the god file, in decreasing entanglement:
`_allocate_budget` + the 16 layer builders (read the most engine state —
need a layer-context bundle), then the build orchestration itself
(`_build_ai_messages` / `_build_context_layers`), and the planner/replanner
message builders. Each remains its own auditable commit against the full
suite.

## 5. Honest limits (not claimed)

* **Behavior is preserved, not improved.** The pipeline logic is
  verbatim-moved; the only wiring decision is the kill-switch seam (which
  makes the legacy path MORE faithful to the public interface, not less).
* **The compactor is still poked at through a private attribute**
  (`_session_id` re-stamp) — inherited from the pre-P8 engine, unchanged.
  A proper setter would be the follow-up, ideally inside compaction.py.
* **Cache hits on a real caching provider remain unproven** (P3 §5,
  unchanged — needs keys + a caching endpoint).
