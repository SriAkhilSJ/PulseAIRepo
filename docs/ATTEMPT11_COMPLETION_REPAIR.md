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

## Windows validation and follow-up

Windows evidence commit `9ea6a078` recorded `DETERMINISTIC_FAIL`: 142/145
focused tests passed, while protocol (7/7), generation, compilation, and diff
checks passed with zero provider traffic. All eight listed evidence hashes match.

Independent review does not accept the blanket “not code defects” explanation:

- two sleeping-child tests built commands with POSIX `shlex` quoting and were
  invalid under `cmd.exe`; these were test-portability defects;
- the Windows dialect guard rejected native `mkdir temp_app` even though the
  runtime guidance recommends that command; this was a source false positive.

The tests now construct native command lines with `subprocess.list2cmdline` on
Windows, and the guard permits bare native `mkdir` while continuing to reject
`mkdir -p`. The exact focused suite passes 145/145 provider-free on Arena.

Evidence qualification: `monitor.log` contains multi-minute gaps and a retry,
not the required 30-second heartbeat cadence. This does not alter the test
failures, but strict monitoring compliance must not be claimed.

### Windows revalidation

A clean revalidation at evidence commit `84b8e35b` passed:

```text
Focused tests:       145/145 passed in 356.15s
Protocol tests:        7/7 passed in 11.14s
Protocol generation:  current
Compilation:           PASS
Diff check:            PASS
Provider probes:       0
Provider requests:     0
Verdict:               DETERMINISTIC_PASS
```

All nine files listed by the evidence manifest match their committed SHA-256
values. `monitor.log` contains a separate heartbeat approximately every 30
seconds throughout the focused command. The evidence commit is a direct child
of instruction commit `8c9a57a0`, and repair `963eeac0` is an ancestor.

This closes the deterministic Windows gate only; it does not change Attempt
11's live product FAIL.

## Status

This repair remains deterministic-only. Attempt 11's historical product remains
FAIL and its evidence workspace must not be modified. No new provider run,
merge, branch deletion, or Agentic UI work is authorized.
