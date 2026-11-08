# Financial Reconciliation

## 1. Historical reservation

`res_d7990e4d3dc3` remains **uncertain**:

- persisted `in_flight`, ₹0.167204, 11598 tokens;
- no usage receipt, no invocation record, no settlement;
- classification: dispatch may have occurred, usage unavailable;
- **not released**, **not settled**, **not included** in any new run's totals;
- Live11 evidence unchanged.

## 2. Lifecycle controls

| Event | Disposition |
|---|---|
| Reserved, never dispatched | Released |
| Dispatch started, response missing | Uncertain (hold retained) |
| Response received, usage missing | Uncertain |
| Authentic usage received | Settled once at actual cost |
| Settlement already completed | No second settlement |
| Forced process termination | Durable `in_flight`/`reserved`; next startup reconciles |
| Current-process invocation | Excluded from startup orphan sweep |

`OrchestrationFinOpsGovernor.reconcile_orphaned_reservations()` and
`src/finops/recovery.py` implement the transitions. Reconciliation is idempotent.

### Shutdown sweep proof (offline, provider-free)

A reservation was created, marked `in_flight` and persisted, then a second
governor instance was loaded from the same storage and shutdown reconciliation
was run:

```text
before:  in_flight
loaded:  {'res_...': 'in_flight'}
events:  from_state=in_flight -> to_state=uncertain (bridge_shutdown)
active_reservations: {}
uncertain_reservations: {'res_...': 'uncertain'}
reserved_inr: 0.1   spent_inr: 0.0
```

An interrupted dispatch therefore becomes `uncertain` with its hold retained;
it is **not** released as free. The only release path is a reservation still in
`reserved`, where dispatch provably never started.

Residual audit note: `release_reservation()` itself does not refuse an
`in_flight` reservation, so a future caller could misuse it. No production path
does; the shutdown sweep uses the state-aware reconciliation above.

## 3. Authoritative record

```text
guard claim
  -> canonical financial_reservations hold
  -> provider_invocations.jsonl (call + usage + finish_reason)
  -> task FinOps JSON (settlement/aggregate)
  -> canonical reservation terminal status
```

`financial_call_ledger` is the legacy chat/agent table and is not written by the
engineering gateway. No dual write or second source of truth was added.

## 4. Budget

- Observed Live11 total: ₹0.037732.
- Worst-case 8192-output call: ₹0.153887.
- 5-dispatch task max: ₹0.769435.
- Auxiliary max measured: ₹0.005179 (historical, titling enabled).
- LIVE12 authorization: task ₹1.00, auxiliary ₹0.00 (titling off), total ₹1.00.
- Hard pre-dispatch refusal verified offline: ₹1.01 task reservation blocked at
  ₹1.00; ₹0.00 auxiliary gateway refuses before client construction.

## 5. Current tests

`src/tests/test_live11_repair.py` (25) and
`src/tests/test_p0_6_9_universal_finops.py` (15) cover the lifecycle and
governed gateway. `src/tests/test_live12_readiness.py` (17) covers the build
probe, autotitle-off chain, harness classification, auxiliary-wait
short-circuit and mid-turn visual sampling. No active/uncertain reservation is
created by the repair tests; each test uses an isolated workspace.

## 6. Known non-blocking defects (audited, not fixed here)

- Watchdog/turn-outcome contradiction (`src/bridge/__main__.py:1537`,
  `:1698-1705`): a stalled turn can still write a `completed` outcome. Needs a
  stall; a clean LIVE12 turn is unaffected. Watch `submissions.json` terminal
  state against the terminal frame.
- Different-prompt-while-pending renderer race
  (`crusorAIRendererService.ts:1759-1785`): needs a second, different prompt
  while `session_create` is in flight. LIVE12 sends one gesture only.
- `_run_turn` terminal write is covered by inspection, not by a bridge test
  (`test_live11_repair.py:70-73` stubs it). LIVE12 must verify
  `submissions.json` reaches a terminal state with the matching `turn_id`.
- `release_reservation()` does not refuse an `in_flight` hold (API misuse
  risk); no production path calls it that way.
- A reservation without a canonical id can move to `uncertain` in memory
  without persisting. New reservations always receive a canonical id.
