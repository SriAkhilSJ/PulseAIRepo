# Pulse vs Hermes after Test 5 Attempt 10

**Date:** 2026-08-25  
**Pulse evidence:** `e344bc00e6de2961a2695d4fc7cfa7401ad64c87`  
**Pulse reviewed source:** `b11f30a6`  
**Hermes reviewed source:** `4032a15ad0d5f55f5c97f3fa59709ca28a992543`  
**Provider traffic used for this comparison:** zero

## Executive finding

Pulse now has the right high-level safety rule—finish metadata is retained,
output-limited tool calls are rejected, and tool execution is downstream of a
fully returned LangChain response. Attempt 10 exposed that the transport
boundary is still too opaque: LangChain aggregates streaming chunks before
Pulse sees them and concatenates repeated string metadata. Two chunks carrying
`finish_reason="length"` become `"lengthlength"`. Pulse compares only exact
known strings, so it classified the response as complete.

Hermes avoids this specific failure by owning the chunk accumulator. It assigns
the newest non-empty finish reason rather than generically merging metadata,
fully accumulates tool arguments, validates the final shape, closes the stream,
and only then enters finish/tool control flow.

A second, independent Attempt-10 boundary is in the harness. The runner wrote
the `llm.response` frame and then recorded `OSError: [Errno 22] Invalid
argument`. The evidence has no traceback. In `run_bridge_turn.py`, the immediate
post-write operation is the live heartbeat `print`; on Windows an invalid
inherited console handle can raise OSError 22. The bridge stderr contains no
corresponding graph exception. This is the strongest code-supported hypothesis,
not a proven stack location.

## What Pulse currently does

### Provider and stream ownership

`src/llm/factory.py` builds custom providers with LangChain `ChatOpenAI`.
`RetryLLMProxy.invoke()` detects `streaming=True` through nested runnable
bindings and calls synchronous `invoke()`. This is materially better than the
old `ainvoke()`/event-loop-shutdown path: LangChain consumes its stream before
returning, so Pulse cannot dispatch tools while the iterator is still open.

The limitation is ownership granularity. Pulse receives one aggregated
`AIMessage`; it does not see or validate individual provider chunks. It
therefore inherits LangChain's generic metadata merge semantics.

This behavior was reproduced provider-free with current `langchain-core`:

```python
one = AIMessageChunk(content="", response_metadata={"finish_reason": "length"})
two = AIMessageChunk(content="", response_metadata={"finish_reason": "length"})
assert (one + two).response_metadata["finish_reason"] == "lengthlength"
```

This exactly matches the committed Attempt-10 frame.

### Completion classification

`provider_response_info()` reads `finish_reason`/`stop_reason`, lowercases it,
and marks incomplete only on exact membership in:

```text
length, max_tokens, max_output_tokens, token_limit, incomplete
```

That works for canonical metadata but fails for repeated aggregation artifacts
such as `lengthlength`. Pulse emits the raw aggregated value in `llm.response`,
which made the defect observable, but no canonical/raw distinction exists.

### Graph behavior

After the model returns, `ai_node` repairs textual tool calls, calls
`provider_response_info()`, and marks an `AIMessage` with
`pulse_incomplete_response` when appropriate.

- Incomplete response with tool calls: `SafeToolNode` executes none and returns
  one paired error `ToolMessage` per call.
- Incomplete response without tool calls: `should_continue()` routes through
  `finish_gate` and back to `ai`, bounded by the normal iteration/nudge limits.
- Complete response with tool calls: normal safety and durable execution paths.

The paired-rejection path is sound for canonical output-limit reasons. Attempt
10 bypassed it because `lengthlength` was classified as complete. Since the
response also had no tool call, no unsafe mutation occurred.

### Output budgets and observability

Pulse binds an explicit delivery/forced-delivery output cap and emits bounded
request/response metadata. Remaining blind spots are:

- no raw-vs-canonical finish reason;
- no chunk count or terminal-chunk metadata;
- no bounded reasoning-character count;
- no response usage/input/output token fields in `llm.response`;
- unknown OpenRouter model IDs can fall back to an 8,192 context-window guess;
- generic `custom` provider identity prevents OpenRouter-specific budget/catalog
  behavior from being selected automatically.

Attempt 10's zero visible content plus output-limit finish reason is consistent
with reasoning/output-budget exhaustion, but current Pulse telemetry cannot
prove how many hidden reasoning or completion tokens were consumed.

## What current Hermes does

### It owns accumulation rather than trusting generic message addition

In `agent/chat_completion_helpers.py`, Hermes initializes separate accumulators
for visible content, reasoning, usage, and tool calls. For every chunk it:

1. updates stream diagnostics/activity;
2. appends text/reasoning deltas;
3. accumulates each tool name/id/argument string by index;
4. assigns `finish_reason = chunk_finish_reason` when a non-empty finish reason
   arrives;
5. retains usage from the terminal chunk.

Assignment is important: repeated `length` chunks leave canonical `length`.
They do not become `lengthlength`.

### It has a managed stream lifecycle

`agent/relay_llm.py` wraps provider streams in `ManagedLlmStream`.

- Raw provider iteration is driven by one owner.
- The raw stream's `close()` runs in `finally`.
- Relay async iterators receive `aclose()` before loop close.
- Abandoned/cancelled streams have an explicit `close()` path.
- Completion, cancellation, provider callback failure, and post-processing
  failure have separate outcomes.
- A single-writer fence rejects stale chunks from superseded attempts.

Hermes closes the stream before final response/tool dispatch and retains richer
diagnostics about chunks, bytes, timing, and response handles.

### It validates stream completeness before tool execution

Before constructing the final response, Hermes checks:

- zero usable chunks and no finish reason → `EmptyStreamError`;
- incomplete/unparseable tool argument JSON → repair if safe, otherwise mark
  truncation;
- tool call with no argument bytes and no finish reason → stream-drop handling;
- text delivered with no finish reason → partial-stream stub, not `stop`;
- finish reason `length` → output-limit handling;
- provider error-shaped SSE → provider error/retry path.

A tool call truncated by output limit is never executed.

### It separates different recovery cases

Hermes' conversation loop does not treat every empty/incomplete result alike.

- `length` with text and no tools: append a controlled continuation request,
  up to four attempts, then return a bounded partial failure.
- `length` with tool calls: do not append/execute the broken action; retry the
  same clean state up to four times and increase the output cap within a bound.
- stream ends without finish reason mid-tool: report a stream drop rather than
  falsely claiming output-budget exhaustion.
- visible repetition: stop instead of continuing a degenerate response.
- reasoning consumes the full budget with no visible answer: emit a targeted
  thinking-budget-exhausted failure rather than blindly burning retries.
- content filter/refusal: stop or use configured fallback rather than retrying
  the same deterministic refusal.

Hermes persists/cleans interrupted sequences before returning, preserving a
valid conversation state.

## Side-by-side matrix

| Concern | Pulse now | Hermes now | Consequence |
|---|---|---|---|
| Stream consumer | LangChain sync `invoke()` owns/drains | Hermes manually drives managed chunks | Pulse closes safely but cannot validate chunk semantics |
| Finish merge | LangChain generic dict/string merge | Last non-empty finish reason wins | Pulse produced `lengthlength`; Hermes would retain `length` |
| Canonicalization | Exact string set after aggregation | Provider transport + manual accumulator | Pulse missed an output limit |
| Empty stream | No dedicated final-response structural guard | Raises `EmptyStreamError` when no chunks/reason | Hermes retries/fails explicitly |
| Zero visible output + length | Generic graph finish nudge if classified | Dedicated length/reasoning-exhaustion logic | Hermes diagnosis/recovery is more precise |
| Truncated tool args | Rejects after final AIMessage is marked | Detects while assembling args; repairs/retries or fails | Both refuse execution, Hermes has richer distinctions |
| Output-cap retry | Fixed cap; generic bounded next turn | Separate text/tool retries; bounded cap increase | Hermes is more likely to recover without corrupting state |
| Missing finish reason | Falls through unless adapter supplies metadata | Distinguishes empty, text drop, and mid-tool drop | Pulse can accept ambiguous adapter output |
| Response telemetry | finish/count/names/content chars | chunks/bytes/timing/reasoning/usage + finish | Pulse cannot diagnose hidden-token exhaustion |
| Runner output failure | Heartbeat `print` can abort main evidence loop | Runtime diagnostics are isolated from core turn ownership | Attempt 10 likely lost request 2 at harness boundary |
| Persistence | LangGraph/checkpointer + tool result state | Explicit message/session persistence around every branch | Both can be durable; Hermes' abnormal branches are more explicit |

## Attempt-10 causal correction

The desktop receipt states that the runner raised OSError "when attempting to
process the malformed response." That is too strong.

What is proven:

1. Pulse emitted `llm.response` with `lengthlength`, `incomplete=false`, and an
   empty payload.
2. The runner persisted that frame.
3. The runner then caught OSError 22 and shut down the bridge.
4. No traceback, console transcript, monitor log, request 2, or bridge-side
   exception was preserved.

The malformed classification and runner OSError are therefore two confirmed
sequential facts, not a proven direct cause-and-effect chain. Code order makes
the runner's heartbeat output path a leading OSError candidate.

## Minimal repair plan without redesign

Pulse does not need a wholesale Hermes port. The smallest behavior-preserving
repair is:

1. **Canonical finish metadata.** Preserve `raw_finish_reason`; derive a
   canonical reason that recognizes exact repetition of a known token
   (`lengthlength` → `length`) without unsafe substring matching.
2. **Validate response shape.** Treat canonical output-limit + empty visible
   content/no tools as incomplete and route it to a dedicated bounded
   continuation message, not normal completion.
3. **Keep current tool safety.** Retain paired rejection and zero execution for
   incomplete tool calls.
4. **Improve bounded telemetry.** Add canonical/raw finish, response chunk
   count when available, reasoning-character count, and normalized usage counts.
5. **Harden the harness.** A failed console heartbeat must never kill the turn;
   write a fallback log and continue. Store a sanitized traceback for every
   `runner-error`.
6. **Recognize OpenRouter configuration.** Infer OpenRouter budget/profile
   behavior from the custom base URL without changing the public provider
   selection contract.
7. **Deterministic tests.** Reproduce LangChain's repeated metadata merge,
   prove request-2 continuation for empty output-limit responses, prove no tool
   execution, and inject OSError from heartbeat output while the runner keeps
   consuming frames.

No provider call is needed for these repairs. No live retry should be considered
until the deterministic contracts pass on Windows and the desktop evidence
workflow itself preserves monitoring, console, traceback, and product receipts.
