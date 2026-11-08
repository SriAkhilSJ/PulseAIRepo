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
- Auxiliary max measured: ₹0.005179; configured cap ₹0.20.
- Recommended ceiling: **₹1.20** task+aux (or ₹1.00 with autotitle off).
- Hard pre-dispatch refusal verified offline.

## 5. Current tests

`src/tests/test_live11_repair.py` (25) and
`src/tests/test_p0_6_9_universal_finops.py` (15) cover the lifecycle and
governed gateway. No active/uncertain reservation is created by the repair
tests; each test uses an isolated workspace.
