# Context Engine P10 — Planner-Message & Ambiguity-Detection Extraction (Fifth Modularization Cut)

**Date:** 2026-08-31
**Scope:** `src/context/plan_messages.py` (new), `src/context/ambiguity.py` (new), `src/context/context_engine.py` (both extracted), new `src/tests/test_plan_messages.py` (10 contracts) + `src/tests/test_ambiguity.py` (8 contracts)
**Sources:** `docs/CONTEXT_ENGINE_P9_LAYER_POLICY.md` (extraction template + surface-preservation rule)

## 1. What moved

Two self-contained LLM-message-construction helpers moved out of the
engine:

| Concern | Owner now |
|---|---|
| Strict-output planner-prompt suffix (`_planner_prompt`) | `plan_messages.wrap_planner_prompt` |
| Planner-node messages (`build_planner_messages`) | `plan_messages.build_planner_messages` |
| Replanner-node messages (`build_replanner_messages` — completed/remaining sections, failures capped at 3, lessons capped at 2) | `plan_messages.build_replanner_messages` |
| Plan-reviser-node messages (`build_reviser_messages` — full plan + requested change) | `plan_messages.build_reviser_messages` |
| Advanced ambiguity detection (embedding similarity vs. a 26-string hint vocabulary, D2-cached) | `ambiguity.detect_ambiguity_advanced` |
| Deterministic vague/specific keyword fallback | `ambiguity.detect_ambiguity_fallback` |

Both are pure data in / messages out. The only engine coupling is the
**live** `_allow_embedding_compute` flag, which the
`_detect_ambiguity_advanced` delegate feeds per call — a contract that
pins the hard safety property: **deadline-bound turns never encode**.
With the flag off the detector returns the heuristic result without
even importing the embedder (a new contract asserts the embedder is
never touched); flipping the flag mid-session takes effect on the very
next call (another contract records the embedder being consulted
exactly once after the flip, via a monkeypatched `get_embedder`).

The engine keeps all six method names as thin delegates:
`src/agents/planner.py` calls the three builders on the engine
instance, `test_embedding_cache.py` pins
`eng._detect_ambiguity_advanced`, and the D27-registered
`_ambiguity_layer` builder calls the delegate — every seam works
unmodified.

### What deliberately did NOT move

The remaining big units — `__init__` (175 lines),
`_build_context_layers_inner` (120, D27-pinned registry),
`_build_ai_messages` (90, the coordination core), `compress` (59, ABC
entry), `get_status` (56) — are the engine's **stateful coordination
core**. Extracting them would produce a component that receives the
whole engine: a facade with no cohesion gain. The modularization
series stops here on principle, not on size: every remaining method
is cohesive with the instance state it mutates.

## 2. Verification (provider-free — zero LLM spend, zero tokens)

```bash
.venv/bin/python -m pytest src/tests/test_plan_messages.py \
  src/tests/test_ambiguity.py -q
# the areas P10 touched (incl. the embedder seam pinned by test_embedding_cache)
.venv/bin/python -m pytest src/tests/test_embedding_cache.py \
  src/tests/test_engine_smoke.py -q
# full suite (README command)
.venv/bin/python -m pytest src/tests -q \
  --ignore=src/tests/test_session_engines.py --basetemp=/tmp/pulseai-pytest
```

| Run | Result |
|---|---|
| Planner + ambiguity contracts (new) | **18 passed** |
| Touched areas (embedding cache + engine smoke) | 40 passed |
| Full suite (README command, clean run) | see section 3 |

## 3. Full-suite result

```text
6 failed, 1114 passed, 3 skipped in 214.07s
```

The 6 failures are IDENTICAL to the documented pre-existing baseline
(5× tests reading the deleted `ui/` catalog + 1×
`test_autonomous_runtime_contract.py::test_ai_node_builds_expected_first_sarvam_request_without_provider_call`).
**Zero regressions; +18 = the new contracts** (1096 → 1114 passed vs
the P9 run). `test_session_engines.py` (excluded from the default
command) passes 19/19.

## 4. Modularization series — complete

| Cut | Module | Engine delta |
|---|---|---|
| P6 | `usage_pressure.py` (+ metrics/build-events) | −~120 net |
| P7 | `feedback_memory.py` (feedback loop) | −~110 net |
| P8 | `history_shaper.py` (history pipeline) | −~70 net |
| P9 | `layer_policy.py` + `task_types.py` (layer policy) | −~353 net |
| P10 | `plan_messages.py` + `ambiguity.py` (planner msgs + detector) | −~122 net |

The engine went from **~2150 lines (P3) to ~1805 lines (P10)** — a net
reduction of ~345 lines, with every behavior-preserving cut backed by
its own contract file and a clean full-suite run. What remains is the
cohesive stateful core: construction, the builder-registry loop,
differential-cache orchestration, model reconfiguration, and telemetry
aggregation.

## 5. Honest limits (not claimed)

* **Behavior is preserved, not improved.** Logic moved verbatim; the
  only rename is `_planner_prompt` → `wrap_planner_prompt` (the old
  name collided with the `planner_prompt` string parameter inside the
  builders) — the engine's `_planner_prompt` staticmethod is kept as a
  delegate.
* **The ambiguity detector's embedding path remains unexercised end-to-end**
  (needs a real embedder; the sandbox exercises the flag-off and
  failover paths, which is exactly what production deadline-bound turns
  hit).
* **Cache hits on a real caching provider remain unproven** (P3 §5,
  unchanged — needs keys + a caching endpoint).
