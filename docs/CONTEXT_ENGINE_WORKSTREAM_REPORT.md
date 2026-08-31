# Context Engine Workstream Report — P3 → P10

**Date:** 2026-08-31
**Branch:** `arena/01a053f3-pulseairepo` → `main` (merged via PR #12, merge commit `7af80443`)
**Scope:** The "best context engine, every event running safely" workstream — Hermes/OpenClaude parity, event-safety state machines, feedback learning, the stale-proof history pipeline, the pure layer policy, and pinned never-encode ambiguity detection.

---

## 1. My work to this repo

### 1.1 Delivery table

| Increment | Commit | What landed | New module(s) | New contracts |
|---|---|---|---|---|
| **P3** | `40788c0c` | Hermes+OpenClaude alignment: usage-driven compaction, cache-break detection, memory sanitization | `prompt_cache_audit.py` | `test_context_engine_parity.py` (20) |
| **P6** | `c4b96921` | Event-safety contracts + first modularization cut (usage-pressure state machine extracted) | `usage_pressure.py` | `test_event_safety.py` (21) |
| **P7** | `1c072fd0` | Feedback-learning extraction + KeyError hardening | `feedback_memory.py` | `test_feedback_memory.py` (14) |
| **P8** | `a01127f3` | History-shaping extraction (stale-proof pipeline + compaction kill switch) | `history_shaper.py` | `test_history_shaper.py` (10) |
| **P9** | `bbf27323` | Layer-policy extraction + `TaskType` relocation (breaks the import cycle) | `task_types.py`, `layer_policy.py` | `test_layer_policy.py` (16) |
| **P10** | `c6b3be85` | Planner-message + ambiguity-detection extraction | `plan_messages.py`, `ambiguity.py` | `test_plan_messages.py` (10) + `test_ambiguity.py` (8) |

**Net result:** 8 new modules, 7 new contract suites, **99 behavior contracts** pinned, and the god file cut from **2032 → 1806 lines** (`context_engine.py`, ~226 lines extracted — ~11%) without a single regression at any full-suite gate.

### 1.2 Full-suite staircase (constant 6 failed / 3 skipped — all pre-existing)

```
1015 passed   pre-P3 baseline (at 4df51c1a, P1/P2/P4 already on main)
1056 passed   P6   (+21 event-safety contracts; +20 P3 parity already counted at 1035)
1070 passed   P7   (+14 feedback-memory contracts)
1080 passed   P8   (+10 history-shaper contracts)
1096 passed   P9   (+16 layer-policy contracts)
1114 passed   P10  (+18 planner + ambiguity contracts)
```

Every increment is a clean staircase: the +N at each step is exactly the count of new
behavior contracts, so a regression is structurally visible — a lost behavior shows up
as a *missing* pass, not a silently-different green number. **Zero provider spend** —
the entire workstream is verified against contracts and the pre-computed parity baselines,
never against a live LLM.

### 1.3 The six event-safety properties now pinned by contract

1. **Pair-atomic trimming** — `HistoryShaper.trim` never starts on a `ToolMessage`, and
   tool/result pairs are never split (the P4 guard, pinned at both enforcers + the engine
   path). P6 also fixed a real bug here: unanswered `tool_calls` survived compaction and
   would 400 the provider.
2. **Never-encode on deadline turns** — `ambiguity.py` pins that deadline-bound turns
   never take the encoding failover path (P10).
3. **Compaction kill switch** — `PULSEAI_COMPACTION=off` is a *public seam*
   (`compact(history, budget, kill_switch_trim=None)`), injected by the engine and pinned
   by the pre-P8 regression test (P8).
4. **Stale-state immunity** — the engine's model / inference policy / current task /
   session identity / window are **getters, never captured values** (P8).
5. **Non-blocking feedback** — the feedback loop is a store write that can't block or
   corrupt a turn; it exists specifically to prevent the data-loss history recorded in
   `test_session_engines.py` (P7).
6. **Measured cache-prefix stability** — `prompt_cache_audit.py` tracks the session PEAK
   of the stable prefix; a turn is a `cache_break` on a real, measured drop (ported from
   OpenClaude `promptCacheBreakDetection.ts`, MIN_CACHE_MISS_TOKENS 2000 + ">5% drop"),
   and fires a latched, scoped `runtime.cache_break` receipt (P3).

---

## 2. Why this path

**Parity before refactoring.** The desktop engine's decisions were *measured, not
guessed*: P3 first reproduced the Hermes/OpenClaude behavior (usage-driven compaction,
cache-break detection, memory sanitization) behind the base ABC's unchanged surface, so
the proven behavior existed in the tree and passed the full suite before a single line
was moved.

**Behavior-preserving extraction.** Each P6–P10 cut is a verbatim move of one cohesive
state machine out of the god file, gated by the pre-computed pass counts. That's why the
series shows a clean staircase — a regression is a missing pass, not a fuzzy diff. The
engine keeps the side effects (counters, log lines, receipts); the extracted module owns
only its state.

**The repo's own AST self-audits (D26/D27) as architecture spec.** They encode real
historical bugs, and they shaped every seam: builders stay on the engine, `TaskType`
moved to `task_types.py` to break the import cycle, constants became aliases, and the
kill switch is injected through the engine's public seam rather than hidden inside the
extracted module.

**The live-dependency rule.** Anything that changes per call is read per call — getters,
not captured values — with contracts pinning freshness. This is the anti-stale-state
property (#4 above).

**Provider-free verification with honest limits.** What can't be proven in a sandbox
(real cache hits, real embedding paths) is *documented as unproven*, not claimed. Every
increment shipped with zero LLM spend and its exact baseline pass counts.

**Stopping at the coordination core on principle.** A facade that receives the whole
engine to hand it back is indirection without cohesion; the extraction stopped at the
point where each remaining seam would be a wiring layer, not a state machine.

---

## 3. Other work that needs to be done

### Needs resources (blocked on credentials/environment)

* **Prove prompt-cache hits on a real caching provider.** The biggest unverified claim in
  the engine — the cache-break *detection* is pinned, but an actual cache *hit* has never
  been observed. Needs provider keys + a caching endpoint.
* **Exercise the embedding paths end-to-end.** The embedding cache and vector memory are
  contract-tested but never run against a live embedding model.

### Owner's call (product/policy decisions, not engineering)

* **The 6 pre-existing baseline failures.** 5× deleted `ui/` catalog tests
  (`ui/src/runtime/toolCatalog.ts` is absent from the tree) + 1×
  `test_autonomous_runtime_contract.py::test_ai_node_builds_expected_first_sarvam_request_without_provider_call`
  (request-shape drift). All six fail identically on the pre-P3 commit — they are
  baseline noise, but *removing or re-baselining them* is a decision for the owner.

### Optional / follow-up

* **Builder relocation** (the 16 layer builders staying on the engine) — requires a D27
  contract rewrite before any move is safe.
* **Re-baselining the `bench-results/test5-*` evidence trees** against the merged engine.
* **Multi-user feedback-store scoping** — the feedback store is currently single-scope.
* **A proper `HistoryCompactor._session_id` setter** rather than the current ad-hoc write.

---

## 4. Verification

* Merge state: **CLEAN / MERGEABLE**, no CI gates — merged with a standard merge commit
  (`7af80443`) so the full P3→P10 increment history is preserved on `main`.
* `origin/main` verified at `7af80443` (was `4df51c1a` before the merge).
* Full suite at P10 merge: **1114 passed, 3 skipped, 6 failed** (the 6 documented
  pre-existing baseline failures).
