# Context Engine P6 — Event Safety Contracts + First Modularization Cut

**Date:** 2026-08-30
**Scope:** `src/context/usage_pressure.py` (new), `src/context/context_engine.py` (P3 state machine extracted), `src/context/smart_compressor.py` (pairing fix), `src/dashboard/event_bus.py` (replay-window fix), new `src/tests/test_event_safety.py` (21 behavior contracts)
**Sources:** `docs/CONTEXT_ENGINE_P3_HERMES_OPENCLAUDE.md` §5 (open follow-ups), `AGENT_STARTUP_REVIEW.md` (Week-3 god-file split; session/event isolation P0), `HERMES_ALIGNMENT_PLAN.md` (P0-E discipline: behavior contracts, not change-detectors)

## 1. Where the workstream stood

After P1 (lean tail), P2 (4-breakpoint scope + lineage + audit), P3
(usage-driven compaction, cache-break detection, memory sanitization) and
P4 (tool-pair guard) landed on `main`, two items were explicitly left open:

1. **The god file.** `context_engine.py` had grown to ~2,400 lines; P3
   deliberately did NOT restructure "to keep the diff auditable against the
   1,000+ green tests". The startup review's Week-3 recommendation (split
   into modules) was the named follow-up.
2. **"Every event running safely."** The event pipeline (EventBus +
   ApprovalQueue + engine receipts + tool-event pairing) carries every
   agent state change to dashboard SSE, bridge, and per-session
   subscribers. Its safety invariants (session isolation, bounded memory,
   pairing, latched scoped receipts, fail-closed approvals) were exercised
   piecemeal by individual suites but never pinned as one contract.

## 2. What P6 changed

### 2.1 First modularization cut: `src/context/usage_pressure.py`

The P3 usage-pressure state machine — the Hermes token-state contract
(`last_prompt/completion/total_tokens`, `threshold_tokens`) plus the
anti-thrash episode latch — moved out of the layered engine into one
auditable object, `UsagePressure`:

* `update(usage, window)` — canonical bucket ingest + 75% threshold
  recompute + ≤60% re-arm (Hermes `update_from_response` semantics).
* `at_threshold(tokens, window)` — `should_compress` decision.
* `tighten(history_budget, window) -> (budget, fired, floor)` — the
  per-build episode tightening; `fired` is True exactly on the FIRST
  crossing so the engine bumps its counter and logs once.
* `reset()` — episode close (engine `on_session_reset`).

The engine keeps ownership of the SIDE EFFECTS (counter, log line,
receipts) and owns nothing but the tracker for the state. The ABC
attribute surface is preserved by delegating properties
(`last_prompt_tokens`, `last_completion_tokens`, `last_total_tokens`,
`threshold_tokens`, `_usage_pressure_active`), so the base ABC's
`on_session_reset` writes and every existing caller/test are unchanged.
This is the template for the remaining god-file cuts (feedback learning,
layer builders, history compaction): one cohesive state machine per
module, engine as the façade.

Behavioral change: the bucket writes in `update_from_response` now happen
inside the engine's `_api_lock` (previously outside it) — concurrent
dashboard turns for the same session can no longer interleave half-written
usage buckets. Strictly safer, same single-threaded semantics.

### 2.2 Bug found by the new contracts: unanswered tool_calls survived compaction

`SmartCompressor._enforce_tool_pairing` was supposed to drop "unanswered
tool calls" — but its kept branch appended the ORIGINAL `AIMessage`, so a
pre-trimmed mid-turn history (the model asked for calls `b1`+`b2`, only
`b1`'s result exists in the checkpoint) came out of compaction still
carrying `b2`. OpenAI/Anthropic-compatible APIs reject a request whose
`tool_calls` are not all answered — the next request would 400. The fix
materializes a filtered copy (the same pattern the text-only branch
already used). The new contract test pins it: a corrupt input with an
orphan result first and one missing result now compacts to
`kept_calls == surviving_results` (strict, bidirectional).

### 2.3 Bug found by the new contracts: late-session replay dropped the newest events

`EventBus.subscribe()` replayed history head-first and broke on
queue-full (maxsize 200). A subscriber reconnecting to a busy session
replayed the OLDEST 200 of the 500 retained events and silently missed
the most recent 300 — a reconnected dashboard lost the latest state,
which is exactly the "events don't run safely" class of failure. Replay
now takes the tail that fits the queue: the newest events always win the
window, the internal history cap (500) is unchanged, and an empty queue
receiving ≤ maxsize items makes `put_nowait` total.

### 2.4 `src/tests/test_event_safety.py` — the "every event" contract

21 behavior contracts, no count/byte snapshots:

* **Session isolation** — live delivery and history replay are
  session-scoped; only the explicit `thread_id=None` admin subscription is
  global; an event with no session attribution is invisible to every
  session subscription (safe default — unattributable ≠ broadcastable);
  `clear(thread_id)` is session-scoped.
* **Bounded memory** — history capped at 500; replay window = newest 200;
  a dead (full, non-draining) subscriber is evicted without crashing the
  bus while healthy subscribers keep receiving; event ids are unique.
* **Tool-event pairing (P4 guard, pinned at both enforcers + engine path)**
  — no result stream starts on a `ToolMessage`; `SmartCompressor` is
  strictly bidirectional-paired even on pre-trimmed input;
  `trim_messages_to_budget` keeps its documented loose contract at every
  budget (100 → 100,000 sweep); the engine's `_trim_history` path keeps
  pairs under a tight budget.
* **Latched, scoped receipts** — `runtime.cache_break` carries only its
  six bounded metadata keys (no message bodies) scoped to the engine's
  `thread_id`; `runtime.degraded` fires exactly once per session no matter
  how many times the build path re-enters.
* **Approval safety** — cross-session resolve is rejected (the request
  stays pending for its owner); timeout resolves to DENY (never a stall,
  never an implicit approval); pending lists are session-scoped.

## 3. Verification (provider-free — zero LLM spend, zero tokens)

```bash
# new contracts
.venv/bin/python -m pytest src/tests/test_event_safety.py -q
# P3 parity (pins the extracted state machine)
.venv/bin/python -m pytest src/tests/test_context_engine_parity.py -q
# full context suite
.venv/bin/python -m pytest src/tests/test_context_engine_parity.py \
  src/tests/test_bounded_scan.py src/tests/test_compaction.py \
  src/tests/test_prompt_cache_audit.py src/tests/test_context_budget.py \
  src/tests/test_cache_preservation.py src/tests/test_model_budgets.py \
  src/tests/test_git_context.py src/tests/test_embedding_cache.py \
  src/tests/test_degraded_memory.py src/tests/test_chunk_index.py \
  src/tests/test_repo_map.py src/tests/test_vector_memory.py \
  src/tests/test_engine_smoke.py src/tests/test_bridge_protocol_v2.py -q
# full suite (README command)
.venv/bin/python -m pytest src/tests -q \
  --ignore=src/tests/test_session_engines.py --basetemp=/tmp/pulseai-pytest
```

| Run | Result |
|---|---|
| Event-safety contracts (new) | **21 passed** |
| P3 parity + engine smoke | **32 passed** (unchanged — extraction behavior-preserving) |
| Full context suite (15 files) | **240 passed, 2 skipped** (identical to P3 baseline) |
| Full suite (README command) | see section 4 below |

## 4. Full-suite result

```text
6 failed, 1056 passed, 3 skipped in 223.16s
```

The 6 failures are IDENTICAL to the documented pre-existing baseline (P3
doc §3): 5× tests reading the deleted `ui/` catalog
(`ui/src/runtime/toolCatalog.ts` absent from the tree) + 1×
`test_autonomous_runtime_contract.py::test_ai_node_builds_expected_first_sarvam_request_without_provider_call`
(verified failing on the pre-P6 commit as well). **Zero regressions;
+21 = the new event-safety contracts.**

Webview (unchanged, re-verified): `npx tsc -b` 0 errors, DOM 9/9.

## 5. Honest limits (not claimed)

* **The god file is smaller, not split.** Only one state machine moved
  (~180 lines net out of `context_engine.py`). The remaining cuts —
  feedback learning, the 16 layer builders, history compaction — each need
  their own auditable commit against the full suite. P6 proved the
  extraction template; it did not do the full Week-3 split.
* **The pairing fix changes one output edge case.** Pre-trimmed mid-turn
  histories that previously kept unanswered calls now drop them. Any
  consumer that depended on the unpaired shape (none in the tree; the
  provider itself forbids it) would notice — that is the point.
* **Replay is a WINDOW, not a log.** A subscriber reconnecting after more
  than 500 session events still does not get the full history; the window
  now always contains the NEWEST retained state, which is what a live UI
  needs. Full log durability lives in the LangGraph checkpoint store, not
  in the bus.
* **Cache hits remain unproven on a real caching provider** (P3 §5,
  unchanged — needs keys + a caching endpoint).
