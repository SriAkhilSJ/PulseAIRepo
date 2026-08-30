# Context Engine P3 — Hermes + OpenClaude Alignment (Usage-Driven Compaction, Cache-Break Detection, Memory Sanitization)

**Date:** 2026-08-30
**Scope:** `src/context/context_engine.py`, `src/context/prompt_cache_audit.py`, `src/graphs/chat_graph.py` (ai_node), new `src/tests/test_context_engine_parity.py` (20 behavior contracts)
**Sources:** `docs/HERMES_CONTEXT_MINUTE.md`, `docs/OPENCLAUDE_CONTEXT_MINUTE.md`, `HERMES_VS_PULSEAI_ARCHITECTURE.md`, `HERMES_ALIGNMENT_PLAN.md`, `docs/PULSEAI_CONTEXT_BENCH.md`

## 1. What was true before P3

The 2026-08-29/30 renovation had already landed P1 (lean tail), P2
(4-breakpoint cache scope + lineage + audit metering), P4 (tool-pair
guard), and the Hermes-parity `ContextEngine(ABC)` in
`src/context/engine.py`. The bench (`PULSEAI_CONTEXT_BENCH.md`) closed
two of its four gaps (400K tail, per-turn cache reorder).

Three alignment holes remained, all observable in code:

1. **The ABC was dead code.** Nothing imported `src/context/engine.py`;
   the concrete `ContextEngine` (2,032L) did not implement it. The
   Hermes token-state contract — `update_from_response`,
   `should_compress`, `compress`, `get_status`, `on_turn_complete` —
   existed but no engine consumed it. Two classes shared the name
   `ContextEngine`.
2. **The compaction decision was estimate-only.** The engine trimmed
   history against a static per-task budget computed from its OWN token
   counting — which degrades to a `chars/4` heuristic for unlisted
   models (measured for `sarvam-105b-conversations`; the tiktoken BPE
   download is blocked in offline sandboxes). If the estimate lied, the
   request overshot the real window and the provider 400'd. Hermes's
   engine owns the decision from the provider's ACTUAL usage
   (`threshold_percent=0.75` of the real window); Pulse had no such loop.
3. **Cache busting was silent.** `CachePrefixAudit` (D19) measured
   per-turn prefix stability but treated a REGRESSION of the stable
   prefix — the provider cache genuinely losing bytes, the cost
   multiplier OpenClaude `promptCacheBreakDetection.ts` (1027L) calls a
   "break" — as just another histogram bin. Small prefixes and true
   breaks were indistinguishable; nothing was emitted.

Also: memory layers (long-term, tool, reflections, staleness) injected
untrusted content into the prompt without the Hermes
`sanitize_memory_context` redaction pass (6k cap +
`redact_sensitive_text(force=True, redact_url_credentials=True)`).

## 2. What P3 changed

### 2.1 The concrete engine IS the ABC (`context_engine.py`)

```python
from src.context.engine import ContextEngine as BaseContextEngine
class ContextEngine(BaseContextEngine): ...
```

- `name` → `"layered"`; ABC abstract methods implemented:
  `update_from_response`, `should_compress`, `compress`, plus the
  default-extended `should_compress_info`, `on_turn_complete`,
  `on_session_reset`, `get_status`, `update_model`.
- Window application refactored into ONE path — `_apply_window(window,
  source)` — shared by `__init__`, `reconfigure_model`, and
  `update_model`, so the three entry points cannot drift.
  `update_model(model, context_length)` trusts an explicit window
  verbatim (bridge model registry); otherwise the discovery chain
  resolves it.
- `_ensure_compactor()` extracted: the per-turn path and the ABC
  `compress()` share ONE per-session `HistoryCompactor`, so
  anti-thrash state (ineffective streak, summary, LLM suppression) is
  one object.
- `compress(messages, current_tokens, ...)`: Hermes-parity entry.
  Accepts BaseMessage OR wire dicts (local `_wire_dicts_to_messages`
  converter — deliberately NOT `langchain messages_from_dict`, which
  speaks the checkpoint `{type, data}` serialization, not the wire
  format) and returns the same shape. Head/tail protected, AI/Tool
  pairs never split (P4 guard inside `trim`), lean tail keeps the
  newest 6 tool rounds verbatim.
- `get_status()`: unified telemetry — Hermes token state + window
  source + `usage_percent` + compaction counters + prompt-cache audit
  stats. One call for bridge/dashboard/diagnostics.
- `on_session_reset` clears P3 state (pressure flag, cache-break latch).

### 2.2 Actual-usage-driven compaction (Hermes Law 1's missing half)

`ai_node` (`chat_graph.py`, after `TokenTracker.record_call`):

```python
try:
    get_context_engine(config).update_from_response(call_usage.to_dict())
except Exception:
    pass
```

`TokenTracker.record_call` already prefers REAL provider metadata over
estimates, so the engine now sees the truth. Only the MAIN-agent call
feeds the engine — the task_manager classifier request is a small
planner call, not window pressure.

Engine side:

- `update_from_response(usage)`: records canonical
  prompt/completion/total buckets; recomputes
  `threshold_tokens = int(window * 0.75)`; **re-arms** the pressure
  episode when usage relaxes to ≤60% of the window.
- `should_compress(prompt_tokens=None)`: Hermes semantics — fires at/above
  75% of the REAL window; `should_compress_info` carries the human
  reason (anti-thrash message).
- `_apply_usage_pressure(history_budget)`, called from
  `_build_ai_messages` after `_allocate_budget`: while actual usage is
  above the threshold, the history budget is tightened toward
  `max(budget/2, lean_tail_floor)` for EVERY build of the episode —
  the tightening persists (reverting mid-episode would resend the
  oversized history into the same overflow); the COUNTER and receipt
  fire once. Re-arms on relaxation.

### 2.3 Cache-break detection (OpenClaude `promptCacheBreakDetection`)

`CachePrefixAudit` now tracks the session PEAK of the stable prefix
(absolute chars). A turn is a `cache_break` when the stable prefix
drops by **>5% of the peak request AND >8,000 chars (~2000 tokens at
the repo's chars/4 accounting)** below that peak — OpenClaude's
`MIN_CACHE_MISS_TOKENS 2000` + ">5% drop" rule, ported to the
provider-agnostic char metric this audit already uses. Tail growth (the
normal case) shrinks the ratio but never the absolute stable size, so
it can never fire. `stats()` gains `cache_breaks` + `last_cache_break`.

The engine converts a detected break into **exactly one**
`runtime.cache_break` receipt per session (latched, same contract as
the PBR-004 by-design bounding receipt): `{thread_id, turn, breaker,
break_msg_idx, dropped_chars, stable_ratio}` — the breaker owner
(`persona` / `layer:<name>` / `history:*`) tells you WHICH bytes moved.

### 2.4 Memory-layer sanitization (Hermes `sanitize_memory_context`)

`_long_term_memory_layer`, `_tool_memory_layer`, `_reflection_layer`,
and `_memory_validation_layer` now pass all memory content through
`sanitize_memory_context()` (redact secrets incl. URL credentials, cap
at 6,000 chars with head/tail truncation marker) before the content
reaches the prompt. Memory is untrusted data — it may have been stored
from a previous run on a different or adversarial workspace.

## 3. Verification (provider-free — zero LLM spend, zero tokens)

```bash
# P3 parity contracts (new)
uv run python -m pytest src/tests/test_context_engine_parity.py -q

# full context suite (12 files + smoke + parity + bench)
uv run python -m pytest src/tests/test_context_engine_parity.py \
  src/tests/test_bounded_scan.py src/tests/test_compaction.py \
  src/tests/test_prompt_cache_audit.py src/tests/test_context_budget.py \
  src/tests/test_cache_preservation.py src/tests/test_model_budgets.py \
  src/tests/test_git_context.py src/tests/test_embedding_cache.py \
  src/tests/test_degraded_memory.py src/tests/test_chunk_index.py \
  src/tests/test_repo_map.py src/tests/test_vector_memory.py \
  src/tests/test_engine_smoke.py src/tests/test_bridge_protocol_v2.py -q

# full suite (README command)
uv run python -m pytest src/tests -q \
  --ignore=src/tests/test_session_engines.py --basetemp=/tmp/pulseai-pytest
```

Results on this machine (Linux / Python 3.11 / bare venv, no
tree-sitter grammars beyond JS/TS installed, no API keys):

| Run | Result |
|---|---|
| Quick context bench (`test_bounded_scan` + `test_bridge_protocol_v2`) | **35 passed, 2.15s** |
| Context suite (11 files, pre-P3 baseline) | **173 passed, 2 skipped, 55.5s** |
| Full suite (pre-P3 baseline) | **1015 passed, 3 skipped, 6 failed** — all 6 = documented pre-existing noise (5× deleted `ui/` catalog, 1× `test_autonomous_runtime_contract`) |
| P3 parity contracts | **20 passed** |
| Context suite (post-P3, incl. parity + smoke) | **240 passed, 2 skipped, 1m44s** |
| Full suite (post-P3) | **1035 passed, 3 skipped, 6 failed, 3m28s** — the same 6 documented pre-existing failures as the baseline (zero regressions; +20 = the P3 parity contracts) |

## 4. Contract tests — what they pin

`test_context_engine_parity.py` (behavior contracts, no count/byte
snapshots):

- ABC: concrete engine `isinstance` the ABC; abstract methods callable;
  `on_session_reset` clears P3 state; `update_model` applies an
  explicit window verbatim (`threshold_tokens = 75%`); `get_status` is
  the unified surface (token state + `usage_percent` + compaction +
  prompt-cache keys).
- Usage decision: `update_from_response` tracks real buckets and never
  clobbers with zeros; `should_compress` fires exactly AT the 75%
  threshold and never without a known window; `should_compress_info`
  carries the reason.
- Pressure: tightens the history budget on a crossing, **persists**
  through the episode without stacking (counter bumps once), re-arms
  after ≤60% relaxation, fires again on a new crossing; integration —
  `build_ai_messages` sends strictly fewer tokens under pressure
  (150×4k-char human/ai exchanges, identical state, only the usage
  differs).
- `compress()`: tool pairs never split, newest exchange survives
  verbatim (lean tail), dict protocol round-trips dict-in/dict-out,
  compression actually reduces tokens, empty input → empty output.
- Cache break: fires on persona rewrite (breaker `persona`, dropped
  chars measured), does NOT fire on tail growth, does NOT fire on
  sub-noise wobble (<2000-token drop); integration — exactly ONE
  `runtime.cache_break` receipt per session (latched), payload carries
  `thread_id` + `breaker`.
- Sanitization: a planted `sk-…` secret never appears in the
  long-term/tool/reflection layer output; context survives redaction
  (not dropped); memory stays under the 8k cap in the layer.

## 5. Honest limits (not claimed)

- **Cache hits are still unproven on the real provider.** The audit
  measures byte-prefix stability provider-agnostically and now surfaces
  breaks as events, but Sarvam (custom OpenAI-compatible) does not
  honor Anthropic cache-control breakpoints. When a caching provider is
  configured, `get_status()["prompt_cache"]["hit_rate"]` is the
  number to watch (P2's `prompt_cache_plan` already emits markers for
  allowlisted providers behind `PULSEAI_PROMPT_CACHE`).
- **The usage-pressure loop is closed-loop only after the first
  response.** Turn 1 still trusts the estimate (there is no actual
  usage yet) — same as Hermes; the discovery chain + `PROVIDER_SAFE_LIMIT`
  margin are the turn-1 protection.
- **The god file is still the god file.** P3 added ~350 lines to
  `context_engine.py` (~2,400L now). The startup review's Week-3
  recommendation (split into node modules) remains open and is the
  right follow-up; P3 deliberately did NOT restructure, to keep the
  diff auditable against the 1,000+ green tests.
- **Narrow waist (Hermes Law 2, 31→8 tools) is out of scope** — that is
  tool resolution in `chat_graph.py`, not the context engine; it stays
  on the renovation's "Next (not yet)" list.
