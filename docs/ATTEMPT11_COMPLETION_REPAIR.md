# Attempt 11 Completion-Integrity Repair

Date: 2026-08-25

Scope: deterministic source repair after independent review of live Test-5
Attempt 11. No provider request was made.

## Failures addressed

Attempt 11 proved output-limit recovery and runner liveness, but exposed four
remaining runtime defects:

1. LangChain repeated complete reasons remained visible as `stopstop` and
   `tool_callstool_calls`.
2. Windows terminal subprocesses inherited a legacy locale and encountered a
   `cp1252` Unicode writer failure.
3. The bridge could stop its asynchronous event forwarder without an explicit
   queue-drain boundary, risking a missing final `tool_call_end` frame.
4. The bridge treated any non-cancelled `stream_agent` return as
   `completed=true`, discarding `finalize_node.task_completed=false` and the
   honest unverified summary.

## Repair

### Complete finish-reason normalization

`src/llm/factory.py` now collapses exact repetitions for both incomplete and
complete canonical reasons, including `length`, `stop`, `tool_calls`,
`function_call`, `content_filter`, and `end_turn`. Raw provider/LangChain
metadata remains available separately.

### UTF-8 terminal transport

`src/tools/terminal_tools.py` now configures foreground and background
subprocess text pipes with explicit UTF-8 encoding and replacement decoding.
Unicode task text or output can no longer inherit Windows `cp1252` behavior and
strand `communicate()` writer threads.

### Paired event flush

`src/bridge/__main__.py` now pairs every event-queue `get()` with `task_done()`
and waits for the queue to drain before emitting `turn_done`. Provider and tool
results queued before graph return therefore precede the terminal frame.

### Honest graph completion

`stream_agent` now returns a string-compatible `AgentTurnResult` carrying the
finalize verdict. It captures the finalize message instead of retaining an
earlier “I will inspect” assistant response. The bridge uses that verdict for
`turn_done.completed`.

`finalize_node` also:

- falls back to `latest_instruction` when `current_task` is absent;
- marks unverified plans unsuccessful;
- does not store unverified work as a successful memory; and
- persists `task_status="unverified"` with `task_completed=false`.

Transport closure remains `turn_done`; incomplete task delivery is now reported
honestly as `completed=false` rather than being misrepresented as a runtime
PASS.

## Deterministic verification

Focused Attempt-11 and adjacent runtime contracts:

```text
145 passed in 25.52s
```

Full runtime suite:

```text
1005 passed, 3 skipped, 4 failed in 180.62s
```

The same four unrelated baseline/environment-sensitive failures documented
before this repair remain: one suite-order chunk-index thread assertion,
repo-map cache object identity, and two session-engine registry/wiring tests.
All 145 completion-repair, bridge, terminal, finish-reason, output-limit, and
model-budget tests pass.

## Status

This repair is deterministic-only. Attempt 11's historical product remains
FAIL and its evidence workspace must not be modified. No new provider run,
merge, branch deletion, or Agentic UI work is authorized.
