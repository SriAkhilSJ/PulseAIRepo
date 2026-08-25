# Desktop Agent Instructions — STOP after Test 5 Attempt 6

**Updated:** 2026-08-25

**Repository:** `https://github.com/SriAkhilSJ/PulseAIRepo`

**Branch:** `arena/01a03741-pulseairepo`

**PR:** `https://github.com/SriAkhilSJ/PulseAIRepo/pull/9`

> **No provider-backed run is currently authorized.** Do not rerun Test 5, merge PR #9, delete branches, or begin Agentic UI work until the Attempt-6 postmortem repair is reviewed and explicitly authorized.

## Preserved Attempt-6 verdict

- Run ID: `test5-6`
- Workspace: `C:\test5-ws-attempt6`
- Runtime: operator-cancelled / FAIL
- Product: FAIL (zero files)
- Observed provider requests: 16
- Human interventions: 1 (founder cancelled after more than 180 seconds)
- Budget stop: false
- Safety requests: 0
- Merge/deletion: none

Preserve these locations exactly:

```text
C:\test5-ws-attempt5
C:\test5-ws-attempt6
bench-results\test5-5\
bench-results\test5-6\
```

Do not characterize the missing Attempt-6 `outcome.json` as a confirmed bridge crash. Manual cancellation occurred, the runner did not catch `KeyboardInterrupt`, and the wrapper used a PowerShell redirected `Start-Process` path already demonstrated to hang.

## Confirmed root cause

The first pre-delivery repair was bypassable:

1. `execute_code` remained exposed during forced-delivery mode.
2. execute-code-only provider turns were refunded from `iteration_used`.
3. The model used `execute_code(os.walk...)` repeatedly instead of writing.
4. Those paid requests therefore did not advance the same counter that enabled forced delivery.

This was a mechanical misuse of one Hermes behavior. Hermes' PTC refund lives inside a broader high-budget tool-loop guardrail system; copying the refund without equivalent no-progress enforcement was not safe for Pulse's 20-call paid harness.

## Repair under deterministic review

The branch repair must prove all of the following before another live authorization:

- every provider request advances Pulse's iteration counter, including `execute_code`;
- varied pre-delivery observations count together, not only exact repeated calls;
- forced delivery exposes only direct `write_file`, `edit_file`, and `copy_file` tools;
- one landed file restores normal capabilities;
- a runner-level no-file breaker cancels by its configured request threshold;
- operator Ctrl+C writes `outcome.json` with `operator_cancelled=true`;
- PowerShell wrapper output is inherited live, not redirected through the deadlocking `Start-Process` path;
- sensitive/destructive safety behavior remains unchanged.

## Allowed desktop work now

Only zero-credit deterministic validation explicitly provided by the Arena agent is allowed. It must not load `.env`, call Sarvam, run provider preflight, or modify preserved evidence.

## Stop rules

- No Test-5 Attempt 7 yet.
- No provider calls.
- No automatic retry.
- No PR merge.
- No branch deletion.
- No Agentic UI implementation.
- Preserve evidence and wait for founder review after deterministic receipts.
