# Live11 Repair Acceptance Matrix

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Duplicate submission prevented at the actual dispatch/session boundary | **PASS** | Durable submission ledger consulted before `_session()` mints and before the turn worker starts |
| 2 | One logical submission -> one session/turn | **PASS** | Bridge tests: one create + one prompt -> one worker; duplicate prompt -> no second worker |
| 3 | Duplicate `session_create` cannot mint a second session | **PASS** | Idempotent `record_session`; bridge duplicate test |
| 4 | Renderer reconnect cannot replay a completed submission | **PASS** | Terminal state durable; reload/claim tests; `running -> failed` on restart |
| 5 | Distinct intentional submissions remain possible | **PASS** | Distinct ids accepted in an existing session; same-session repeat allowed |
| 6 | Concurrent duplicate requests handled safely | **PASS** | 8-thread claim test accepts exactly one |
| 7 | Title completion cannot trigger a submission | **PASS by construction** | Title path emits only `session_info`; no ledger/dispatch path |
| 8 | Reservation without dispatch released | **PASS** | `reserved -> released` test |
| 9 | Dispatch/interruption -> uncertain, hold retained | **PASS** | `in_flight -> uncertain` test; no fabricated usage |
| 10 | Response without usage remains uncertain | **PASS** | Existing generation-boundary missing-usage test; adapter path |
| 11 | Usage without settlement recoverable without double charging | **PASS** | Uncertain commit test; second commit no-op |
| 12 | Repeated reconciliation idempotent | **PASS** | Second orphan sweep returns no events |
| 13 | Forced shutdown preserves durable state | **PASS** | `in_flight` persisted; startup sweep resolves it |
| 14 | Cancellation does not imply zero cost | **PASS** | Post-dispatch ambiguity remains uncertain; adapter path |
| 15 | Aggregate cost reconciles with invocation records | **PASS** | Generation-boundary replay: 3 records, 3 reservations, totals equal |
| 16 | No invocation silently omitted | **PASS** | Completed calls are all in `provider_invocations.jsonl`; the unresolved Live11 claim is visible in the guard + reservation, not hidden |
| 17 | Original generation-boundary suite passes | **PASS** | 15/15 |
| 18 | Broader offline battery | **PASS with one documented pre-existing failure** | 348 collected: 347 passed, 1 failed; the failure reproduces with the baseline bridge file; new suite re-run 25/25 |
| 19 | Historical P0.6.9 evidence intact | **PASS** | 41/41 checksums |
| 20 | Desktop typecheck | **ENVIRONMENT-BLOCKED (pre-existing)** | `npm run compile` fails on missing Electron namespace/typing in upstream files; no errors in changed files |
| 21 | Paid provider calls | **PASS** | 0 calls, ₹0.00 |

---

## Verdict

The mandatory offline criteria pass:

```text
LIVE11_DUPLICATE_AND_FINANCIAL_LIFECYCLE_OFFLINE_QUALIFIED
```

This is **not** live acceptance. No Electron run, no provider call, no
benchmark. P0.6.9 remains `P0.6.9_ACCEPTANCE_FAILED`; generation recovery remains
unproven live.

The desktop compile limitation is pre-existing and environment-specific
(`node_modules/electron` typings absent); it is not presented as a green check.
