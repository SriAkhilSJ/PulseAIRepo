# Deterministic Output-Limit Recovery Repair

Date: 2026-08-25  
Scope: provider-free repair after Test-5 Attempt 10

## Status and limits

This change repairs existing Pulse control flow; it does not redesign the graph. It uses no provider calls and does not establish a live runtime/product PASS. Attempt 10 remains `RUNTIME_FAIL / PRODUCT_FAIL`. PR #9 remains unmerged.

## Failure addressed

LangChain streaming chunk addition can concatenate repeated string metadata. Two terminal chunks carrying `finish_reason="length"` can therefore yield `lengthlength`. Pulse previously tested the merged value against a fixed set, misclassified it as complete, and finalized an empty response. The evidence runner then lost diagnostic detail when a Windows console heartbeat raised `OSError 22`.

## Repairs

### Finish metadata and bounded telemetry

`src/llm/factory.py` now:

- preserves `raw_finish_reason`;
- derives a canonical `finish_reason` by collapsing only exact repetitions of known terminal reasons;
- does not use broad substring matching;
- records content and reasoning character counts without recording hidden reasoning text;
- records normalized input/output/total token counters when providers expose them; and
- retains bounded tool names/counts without tool arguments.

### Dedicated output-limit continuation

`src/graphs/chat_graph.py`, `src/graphs/gates.py`, and `src/graphs/state.py` now:

- mark canonical output-limit responses incomplete;
- track a dedicated per-turn incomplete-response counter;
- allow at most three continuation calls after the initial incomplete response;
- use a concise output-limit-specific nudge that requests a small complete boundary; and
- reset the counter after a complete response.

Tool-bearing incomplete responses still route through `SafeToolNode`, which emits one paired error `ToolMessage` per call and does not execute partial arguments. The new text/empty-response path does not weaken this safety contract.

### Runner evidence preservation

`scripts/run_bridge_turn.py` now:

- treats heartbeat printing as best-effort observability;
- catches console `OSError` and appends bounded evidence to `runner_console_fallback.log`;
- keeps bridge transport running after heartbeat failure; and
- stores a bounded `runner_traceback` in `outcome.json` for runner exceptions.

### Custom OpenRouter budget discovery

`src/context/model_budgets.py` recognizes an `openrouter.ai` host configured through Pulse's generic custom/OpenAI-compatible route. Unknown models then use OpenRouter's existing public catalog probe and cache rather than silently falling to the generic 8,192-token window. Other custom hosts retain existing behavior.

## Deterministic verification

Focused suite (including bridge and desktop protocol boundaries):

```text
70 passed in 3.83s
```

Command:

```bash
pytest -q \
  src/tests/test_retry_proxy_stream_cleanup.py \
  src/tests/test_output_limit_recovery.py \
  src/tests/test_model_budgets.py \
  src/tests/test_run_bridge_turn.py \
  src/tests/test_autonomous_runtime_contract.py \
  src/tests/test_bridge.py \
  src/tests/test_desktop_sidecar_architecture.py
```

Full runtime suite:

```text
997 passed, 3 skipped, 4 failed
```

The four failures are outside the changed focus. A detached baseline at `b83b9669` reproduces the three repo-map/session-engine failures under the same environment; the chunk-index thread assertion is suite-order-sensitive and passes when isolated. The focused repair suite is green. No provider request was issued by these repair tests.

## Evidence rule

These results prove deterministic normalization, routing, safety, budget discovery, and runner fallback behavior only. A future live attempt requires separate authorization and independent evidence review.
