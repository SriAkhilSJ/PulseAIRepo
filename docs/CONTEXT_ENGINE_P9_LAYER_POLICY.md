# Context Engine P9 — Layer-Policy Extraction (Fourth Modularization Cut)

**Date:** 2026-08-31
**Scope:** `src/context/task_types.py` (new), `src/context/layer_policy.py` (new), `src/context/context_engine.py` (policy extracted + `TaskType` relocated), new `src/tests/test_layer_policy.py` (16 behavior contracts)
**Sources:** `docs/CONTEXT_ENGINE_P8_HISTORY_SHAPER.md` (extraction template), `src/tests/test_review_autopsy_fixes.py` (D26/D27 AST contracts that shape the seam)

## 1. What moved

The layer **POLICY** — which built layers survive, in what order they
are emitted, and how much budget each task type gets — moved out of
`context_engine.py` into `src/context/layer_policy.py`:

| Concern | Owner now |
|---|---|
| `TaskType` enum (9 task types) | `task_types.py` (engine re-exports; every existing `from ... import TaskType` works unchanged) |
| Per-task budget split (`_allocate_budget` ratios) | `layer_policy.allocate_budget` |
| Layer attribution (`_infer_layer_name`: metadata tag → header-prefix fallback → "unknown") | `layer_policy.infer_layer_name` |
| Relevance scoring (60/30/10 with embedding gating; deterministic fallback) | `layer_policy.score_and_sort_layers` |
| Semantic near-duplicate removal (embedding-gated, sim > 0.88) | `layer_policy.deduplicate_layers` |
| D23 volatile-tail placement (`_position_volatile_tail`) | `layer_policy.position_volatile_tail` |
| D19 canonical emission order (`_emission_sort_key`, `_BUILDER_ORDER`) | `layer_policy.emission_sort_key` / `BUILDER_ORDER` |
| Score-driven fit + canonical assembly (`_assemble_hierarchical`) | `layer_policy.assemble_hierarchical` |
| Layer compression (`_compress_layer`: repo-map symbol strip, proportional truncation, binary-search convergence) | `layer_policy.compress_layer` |
| The relevance map, volatile-tail preamble, emission order | module constants (`LAYER_RELEVANCE_BASE`, `VOLATILE_TAIL_PREAMBLE`, `BUILDER_ORDER`, `VOLATILE_LAYERS`) |

The engine keeps every pre-P9 method name as a **thin delegate** that
feeds the module its LIVE dependencies per call: `self.model`, the
per-instance `LAYER_RELEVANCE` dict (feedback learning mutates it
mid-session), `_allow_embedding_compute`, `_volatile_tail`, `max_tokens`.
Nothing is captured — the same no-stale-state rule as P7/P8.

### Why `TaskType` had to move first

`TaskType` sat in the engine **below** the import block. The policy
module needs its members at import time (they key the relevance map),
and the engine imports the policy at module top — a policy-side import
of the engine would hit a partially-initialized module and die. Extract
`TaskType` into `task_types.py` (zero dependencies) and re-export from
the engine: 8 test files import it from the engine and keep working
verbatim.

### What deliberately did NOT move

The 16 `_x_layer` content builders **stay on the engine class**. Two
hard reasons, both pinned by tests:

1. **D27 AST contract** (`test_review_autopsy_fixes.py`): parses
   `context_engine.py`, finds `_build_context_layers_inner` **in the
   engine class body**, reads the `{"name": self._x_layer, ...}`
   registry out of it, and asserts every registered method exists on
   `ContextEngine` with the exact `(self, state)` signature. Moving the
   builders to a module would require rewriting that audit contract.
2. **State coupling**: the builders read `memory_manager` (7×),
   `_active_thread_id` (4×, re-stamped per build), the ambiguity
   detector pair, the feedback store, the layer cache, and
   `_last_layers_sent`. They are the engine's content — cohesive where
   the state lives.

The class-attribute constants are kept as **aliases, not copies**
(`VOLATILE_TAIL_PREAMBLE`, `VOLATILE_LAYERS`, `_BUILDER_ORDER`,
`LAYER_RELEVANCE`): `cache_preservation.py` and tests read them at the
class level, and `__init__`'s `copy.deepcopy(type(self).LAYER_RELEVANCE)`
per-instance isolation is untouched — a new contract pins that engine
mutations never reach the module-level base.

## 2. Verification (provider-free — zero LLM spend, zero tokens)

```bash
.venv/bin/python -m pytest src/tests/test_layer_policy.py -q
.venv/bin/python -m pytest src/tests/test_embedding_cache.py \
  src/tests/test_engine_smoke.py src/tests/test_prompt_cache_audit.py \
  src/tests/test_git_context.py src/tests/test_volatile_tail.py \
  src/tests/test_review_autopsy_fixes.py src/tests/test_chunk_index.py \
  src/tests/test_context_budget.py src/tests/test_session_engines.py \
  src/tests/test_feedback_memory.py -q
.venv/bin/python -m pytest src/tests -q \
  --ignore=src/tests/test_session_engines.py --basetemp=/tmp/pulseai-pytest
```

| Run | Result |
|---|---|
| Layer-policy contracts (new) | **16 passed** |
| All P9-pinned surfaces (see command above, incl. the D26/D27 AST audits) | **170 passed, 2 skipped** |
| Full suite (README command, clean run) | see section 3 |

## 3. Full-suite result

```text
6 failed, 1096 passed, 3 skipped in 251.48s
```

The 6 failures are IDENTICAL to the documented pre-existing baseline
(5× tests reading the deleted `ui/` catalog + 1×
`test_autonomous_runtime_contract.py::test_ai_node_builds_expected_first_sarvam_request_without_provider_call`).
**Zero regressions; +16 = the new policy contracts** (1080 → 1096
passed vs the P8 run). `test_session_engines.py` (excluded from the
default command) passes 19/19.

## 4. Modularization series so far

| Cut | Module | Engine delta |
|---|---|---|
| P6 | `usage_pressure.py` (+ metrics/build-events) | −~120 net |
| P7 | `feedback_memory.py` (feedback loop) | −~110 net |
| P8 | `history_shaper.py` (history pipeline) | −~70 net |
| P9 | `layer_policy.py` + `task_types.py` (layer policy) | −~230 net |

The engine is now at **~1927 lines** (from ~2150 at P3). Remaining
large units: the 16 content builders (deliberately engine-resident per
§1) and the `_build_context_layers` orchestration with its
differential cache — the orchestration reads the most mutable state
(`_layer_cache`, `_last_state_hash`, `_active_state_hash`, pressure),
so it is the natural next bundle, or the builders can be re-audited
together with a D27 contract update if the owner prefers a module
home for content too.

## 5. Honest limits (not claimed)

* **Behavior is preserved, not improved.** Logic moved verbatim; the
  only structural decision is `TaskType`'s home (mechanical
  re-export, zero semantic change).
* **The builders did not move** — see §1 for why. P9 is the policy
  half of the "layer builders + budget allocation" queue item.
* **Cache hits on a real caching provider remain unproven** (P3 §5,
  unchanged — needs keys + a caching endpoint).
