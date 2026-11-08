# Financial Lifecycle Audit

## 1. Lifecycle

```text
reserved --dispatch never started--> released
reserved --mark_in_flight--> in_flight
in_flight --authentic usage--> reconciled (settled once)
in_flight --interruption/missing usage/timeout--> uncertain (hold retained)
```

`OrchestrationFinOpsGovernor`:

- `reserve()` checks the budget before dispatch.
- `mark_in_flight()` persists immediately before `invoke`.
- `commit_reservation()` is idempotent; a settled reservation is never charged
  twice.
- `mark_uncertain()` retains the hold and moves it to `_uncertain_reservations`.
- `reconcile_orphaned_reservations()`:
  - `in_flight` → uncertain;
  - `reserved` → released;
  - failure leaves the hold and reports it;
  - optional `reservation_ids` restricts a startup sweep to pre-process holds.
- `release_reservation()` is idempotent and uses the canonical reservation.

`src/finops/recovery.py`:

- `reconcile_workspace_finops()` scans task files with active reservations.
  By default it only touches reservations created before this process started;
  `force=True` is for shutdown.
- `reconcile_workspace_submissions()` marks abandoned `running` submissions
  failed.
- `reconcile_workspace()` returns both receipts.

Bridge:

- first workspace frame → startup sweep;
- `run()` finally → in-process governor reconciliation + forced workspace sweep;
- a forced kill leaves durable `in_flight`/`reserved`; the next process repairs.

---

## 2. Disposition table

| Event | Disposition | Evidence |
| --- | --- | --- |
| Reserved, never dispatched | released | `test_reserved_without_dispatch_is_released` |
| Dispatch started, response missing | uncertain + hold | `test_in_flight_becomes_uncertain_and_retains_hold` |
| Response received, usage missing | uncertain | generation-boundary missing-usage test / adapter path |
| Authentic usage received | settled at actual cost | adapter `commit_reservation` |
| Settlement already completed | no second settlement | `test_uncertain_commit_is_settled_once` |
| Forced termination | durable state; next startup resolves | `test_workspace_sweep_resolves_orphan_file` |
| Repeated reconciliation | idempotent | `test_reconciliation_is_idempotent` |
| Current-process invocation | not treated as orphan | `test_startup_sweep_skips_current_process_reservations` |

No uncertain reservation is treated as free. No usage or cost is fabricated.

---

## 3. Historical reservation

`res_d7990e4d3dc3` is persisted `in_flight`, with no usage, invocation or
settlement. It classifies as **uncertain** (dispatch may have occurred). It is
not released, and the historical evidence is unchanged. A future process on
that workspace would transition it to `uncertain`; that reconciliation is not
applied to historical evidence.

---

## 4. Ledger authority

Authoritative engineering chain:

```text
guard claim -> canonical financial_reservations hold
  -> provider_invocations.jsonl (physical call + usage + finish_reason)
  -> task FinOps JSON (settlement/aggregate)
  -> canonical reservation terminal status
```

`financial_call_ledger` is the legacy chat/agent table, not written by the
engineering gateway. No dual write was added. The historical Live11 empty table
is an integration gap, not a missing physical call.

---

## 5. Test evidence

`src/tests/test_live11_repair.py` (25 tests) covers every transition above.
`test_p0_6_9_universal_finops.py` (15 tests) still passes for the governed
gateway, reservations, settlements, and aggregates.

## 6. Readiness

The financial lifecycle controls are implemented, idempotent, and tested. The
historical hold remains truthfully uncertain; it does not block a fresh LIVE12
workspace.
