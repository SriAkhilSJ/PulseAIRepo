# Crusor P1A — Incremental Model Execution Streaming

**Date:** 2026-11-11
**Branch:** `feat/prompt-cache-stabilization` · **Starting HEAD:** `fb5bd528b40933346c4004a1490154683dc0d40e`
**Scope:** backend streaming integration only. No frontend redesign, no new Agent Core, no ModelGateway replacement, no paid provider calls.
**Verdict:** **PASS** for the P1A definition of done, with the caveats in §10.

---

## 1. The blocking path before this change

Every engineering model call went through one method, `ModelExecutionAdapter._dispatch_code_prompt` (`src/orchestration/model_adapter.py:1295`), and ended in:

```python
gateway_result = invoke_model(llm, prompt, context=gateway_context,
                              cancellation_checker=cancellation_checker,
                              invoke_kwargs=invoke_kwargs)
```

`invoke_model` called `llm.invoke(...)` with no callbacks. The provider client **was** constructed with `streaming=True` (`src/llm/factory.py:1368-1378`), so tokens arrived at the SDK and were then merged by LangChain into one response that nobody could observe. Consequences:

- during a 60 s generation the panel had **no liveness signal** between stage cards;
- `emit_progress` only fires at orchestrator stage/node boundaries (`src/orchestration/orchestrator.py:533+`);
- the plan card still said `0/2` while the model was writing the file (the visible defect in the field screenshot);
- cancellation could only stop the next *request*, not an in-flight stream.

## 2. New streaming architecture

```text
ChatOpenAI(streaming=True, stream_usage=True)          configured provider
        │  SSE deltas
        ▼
RetryLLMProxy.stream(...)                              single owner: abort + acceptance gate
        │  AIMessageChunk…
        ▼
ModelGateway.invoke_model(on_token=…)                  accumulates + forwards
        │  text deltas
        ▼
GenerationActivity (adapter)                           counts chars, throttled deltas, heartbeat
        │  GenerationUpdate(phase, elapsed, chars, node_id)
        ▼
chat_graph._generation_activity                         maps to the existing card + marks the plan node
        │  event_bus "agent.card" (ephemeral)
        ▼
bridge _forward_events → BridgeServer.emit             one NDJSON frame
        ▼
existing frontend (activity card)                      no renderer change
```

Design rules that keep it honest:

- **The gateway remains the only model boundary.** No provider is called from the adapter or the graph.
- **Accumulation is lossless.** Chunks are merged (`aggregate + chunk`); `invoke_model` returns the merged message, so callers that need a complete response see exactly what a non-streaming call would have returned. `stream_usage=True` puts the usage receipt on the final chunk, so FinOps still settles real tokens.
- **No model text reaches the UI.** `GenerationUpdate` carries phase, elapsed time, character count, target file and node id. Never prompt text, never generated source, never reasoning.
- **Cancellation is checked between chunks**, not only before dispatch.
- **Deltas are throttled** to 4/s and heartbeats to one per 3 s (max 200 per generation). A 60 s generation produces ~20 frames, not thousands.
- **Heartbeats are ephemeral.** The bridge forwards them but does not journal them; the stage reporter's snapshots remain the replayable record.

## 3. Files changed

| File | Change |
|---|---|
| `src/llm/gateway.py` | `invoke_model(..., on_token=..., invocation_id=...)`; native-stream consumption with per-chunk cancellation; chunk accumulation; `streamed_chunks/chars/first_token_s` on `InvocationResult`; `_can_stream()` capability check |
| `src/llm/factory.py` | `RetryLLMProxy.stream()` (single attempt, abort-handle lifecycle, acceptance `claim_dispatch`), `supports_streaming` property |
| `src/llm/scripted_model.py` | `stream()` now closes with a metadata-only chunk (usage + finish_reason), like a real provider |
| `src/orchestration/model_adapter.py` | `generation_observer` + `node_id` through `_dispatch_code_prompt`/`_call_model_for_implementation`/`repair_node`; `GenerationActivity` around the one paid dispatch; terminal close on success/failure/cancel |
| `src/orchestration/orchestrator.py` | accepts `generation_observer` and passes it to the adapter |
| `src/orchestration/generation_progress.py` | **new**: `GenerationUpdate`, `GenerationActivity` (counters, throttled deltas, bounded heartbeat), `generation_card()` |
| `src/orchestration/progress_events.py` | remembers the last real snapshot; `mark_generating(node_id)` re-projects the plan with the generating node `in_progress` |
| `src/graphs/chat_graph.py` | builds the observer; emits `agent.card` (activity, `ephemeral: true`); marks the plan node at generation start |
| `src/bridge/__main__.py` | ephemeral agent cards are forwarded but **not journaled** |
| `scripts/streaming_provider_stub.py` | **new**: deterministic OpenAI-compatible SSE fixture (loopback) |
| `src/tests/test_gateway_streaming.py` | **new**: 5 transport tests |
| `src/tests/test_engineering_streaming.py` | **new**: 7 adapter/observer tests |
| `src/tests/test_generation_progress_events.py` | **new**: 8 card/bridge/plan tests |
| `desktop/vscode/scripts/accept-crusorai-streaming-engine.mjs` | **new**: Electron acceptance |

No frontend file was modified. The activity card already renders `label` + `detail`.

## 4. Provider streaming support

- The configured path (`provider="custom"` → `ReasoningAwareOpenAI` → `ChatOpenAI`) is already constructed with `streaming=streaming_enabled(default=True)` and `stream_usage=True` (`factory.py:1368-1378`). The OpenAI-compatible wire path is therefore the one exercised by the fixture.
- `RetryLLMProxy.stream()` deliberately performs **one attempt**: a mid-stream retry would duplicate output, and the engineering adapter already enforces one metered dispatch per call (`model_adapter.py:1444-1452`). It registers the same abort handle as `invoke`, runs the same acceptance `claim_dispatch`, and unregisters in `finally`.
- Callers that do not pass `on_token` are untouched: chat still uses `invoke` + `_AgentTokenPump`, and any client without a real `stream` falls back to `invoke` (verified with `NonStreamingLLM` and with the repository's `Live10LLM` doubles).
- Anthropic/Gemini are not exercised here (not configured); the gateway is provider-agnostic because it consumes the LangChain `stream()` contract.

## 5. Event flow, identity and ordering

One dispatch produces one invocation id, published **before** the call and reused by the ledger (the adapter passes `invocation_id=` into the gateway so the id is not re-minted). Each update carries `session_id`, `turn_id`, `node_id`, `invocation_id`, elapsed time and characters. Deltas are delivered inline in provider order; heartbeats are emitted from one daemon thread and stop on close.

The activity card uses the stable id `${turnId}:activity`, so it updates **in place** rather than stacking. `mark_generating(node_id)` re-projects the last real plan snapshot with that node `in_progress`, so the plan card and the activity card agree during generation. Terminal plan states still come from the orchestrator.

## 6. Invocation and token-accounting evidence

- `test_engineering_streaming.py::test_invocation_id_is_consistent_with_the_finops_ledger` asserts the `started` update's invocation id is present in the **settled** ledger row, with non-zero input/output tokens.
- `test_gateway_streaming.py::test_usage_and_invocation_identity_survive_streaming` asserts usage survives the stream (`input_tokens > 0`, `output_tokens > 0`).
- The ledger row is still written by the adapter's existing `_ledger_record` (`status: settled`, tokens, cost, reservation id); streaming did not add a second accounting path.

## 7. Cancellation and failure handling

| Case | Behaviour |
|---|---|
| Stop during generation | `RetryLLMProxy.stream` / `gateway` check the cancellation predicate **after every chunk** and raise `TurnCancelledError`; consumption stops immediately |
| Adapter | closes the generation activity as `cancelled`, then re-raises; the existing FinOps path releases the reservation (explicit user cancellation is documented as unbilled) |
| Provider stream dies | the exception propagates as a normal invocation failure; the adapter closes as `failed` and the existing uncertain/release policy applies |
| Structured/invalid output | unchanged: `extract_generated_source` / `assert_provider_output_complete` still validate the accumulated text |
| Duplicate visible output | impossible: no model text is emitted to the UI, and the stream is single-attempt |
| Terminal events | unchanged: exactly one `turn_done`/`turn_failed` per turn; the activity card is presentation, never terminal state |

## 8. Deterministic transport tests

**`scripts/streaming_provider_stub.py`** speaks real OpenAI SSE (`chat.completion.chunk`, `[DONE]`, usage-only final chunk) on loopback, with configurable chunk count, delay and a `--fail-after` transport abort. No paid request is possible: the client's base URL is `127.0.0.1`.

20 tests, all passing:

| Test | Proves |
|---|---|
| `test_first_delta_arrives_before_the_call_returns` | streaming, not post-hoc splitting |
| `test_deltas_preserve_provider_order_and_accumulate_to_the_same_result` | order; accumulated == non-streaming response; no-`on_token` caller unchanged |
| `test_usage_and_invocation_identity_survive_streaming` | usage + invocation identity |
| `test_cancellation_stops_consumption_and_raises` | <30 of 30 chunks consumed; `TurnCancelledError` |
| `test_broken_stream_is_an_error_not_a_success` | truncated transport raises |
| `test_streamed_deltas_reach_the_observer_and_accumulate` | adapter deltas, parsed source, no double invoke |
| `test_internal_output_is_never_exposed_to_the_presentation_layer` | JSON/SECRET never in any update |
| `test_cancellation_stops_consumption_and_closes_as_cancelled` | cancelled phase, no completed |
| `test_non_streaming_client_stays_compatible` | fallback to `invoke`, zero deltas |
| `test_invocation_id_is_consistent_with_the_finops_ledger` | ledger reconciliation |
| `test_heartbeats_are_bounded_and_stop_on_close` | bounded + stops immediately |
| `test_heartbeat_carries_generation_progress` | chars in the heartbeat |
| card/bridge tests (8) | stable activity id; no prompt text; plan `in_progress`; ephemeral cards not journaled |

Regression suites: `test_invocation_reconciliation.py`, `test_model_adapter_qualification.py`, `test_canonical_runtime_increment2.py`, `test_scripted_model_seam.py` — all pass except the pre-existing stale test noted in §10.

## 9. Electron acceptance

`accept-crusorai-streaming-engine.mjs` runs the **real** app, bridge, canonical runtime, orchestrator, adapter and gateway. The only substitution is the provider: the local SSE stub (`LLM_PROVIDER=custom`, `CUSTOM_BASE_URL=http://127.0.0.1:<port>/v1`). `CRUSORAI_ORCHESTRATOR_MOCK` and `CRUSORAI_TEST_MODE` are explicitly **unset** — this is not a scripted orchestrator.

Observed in the UI while the request was still streaming:

```text
Understanding request
Working on task_notes | 0/2 steps · 0%
Generating notes.md   | 0s · waiting for first token
Generating notes.md   | 1s · 4 chars received
Generating notes.md   | 1s · 7 chars received
Generating notes.md   | 1s · 10 chars received
Generating notes.md   | 2s · 13 chars received
```

and the plan at the same moment:

```text
task_notes        | is-in_progress
task_verification | is-pending
```

Checks (evidence in `bench-results/phase-3.3-canonical-runtime/logs/electron-p1a/acceptance.json`):

- live activity arrives during generation (≥3 distinct states, first at ~4.5 s, turn ended at ~14 s);
- the activity names the generating target;
- character progress advances **before** the turn ends;
- the updates contain runtime state only (no code fence, no `def `);
- the plan marks the generating node `in_progress` and claims no completion while generating;
- the provider stub served the request (request counter > 0);
- cancellation pressed while the stream was in flight → **Run cancelled** receipt, no failed/unknown label;
- plan card preserved; one terminal frame per turn.

## 10. Remaining limitations

1. **No token text is streamed to the chat for engineering generation.** The model's output is a file body or structured plan; painting it as assistant prose would violate the product rules. What streams is truthful *execution* state (elapsed, characters, target). The chat/tool path keeps its existing token streaming.
2. **The activity card can keep the last "Generating …" label** until the next stage snapshot overwrites it (typically within a second). The terminal receipt remains the authority; a future pass could expressly retire the generation label on failure/cancel.
3. **Heartbeat cadence is 3 s** (bounded, 200 max). It is not configurable from settings yet.
4. **The Electron evidence uses the loopback SSE fixture, not the configured paid provider.** Real-provider behavior (chunk sizes, first-token latency) remains unmeasured; the earlier qualification run is still `FAIL` for reasons unrelated to streaming (contract gate, since fixed in P0).
5. **Streaming bypasses `RetryLLMProxy`'s retry loop by design** (single attempt). Engineering already enforced one paid dispatch; chat still uses retries.
6. **Pre-existing stale test:** `test_generation_boundary.py::TestRecoveryBudget::test_cancellation_stops_before_recovery` expects one prompt while `cancellation_checker` is always true, but both HEAD's gateway and adapter raise before dispatch. It failed before this change and is left untouched.
7. **First-run Copilot sign-in modal** still appears on a fresh Electron profile and is dismissed by the harness; it is a separate product issue.
8. The plan's `in_progress` marker is derived from the last real snapshot, so if generation starts before the first plan snapshot exists, the row appears at the next snapshot rather than instantly.

---

## Definition of done — mapping

| Requirement | Status |
|---|---|
| Real streaming-capable response consumable incrementally through the existing gateway | Met (SSE transport + 5 tests) |
| Through the engineering execution path | Met (adapter observer + 7 tests) |
| Frontend receives truthful updates while execution is still running | Met (Electron, timestamps in §9) |
| Accumulated result remains correct | Met (equality test + parsed source) |
| No paid API requests | Met (`127.0.0.1` stub, `rows=0` for the paid ledger) |

**Deliverable:** this report. Tracker: B-LIVE-003 remains open for *text* streaming; the "frozen during generation" half is closed and recorded in `docs/BUGS_AND_LIMITATIONS.md`.
