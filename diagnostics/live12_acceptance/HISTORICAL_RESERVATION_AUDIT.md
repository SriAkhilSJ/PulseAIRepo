# Historical Reservation Audit — `res_d7990e4d3dc3`

Source: `diagnostics/generation_boundary/live_acceptance/live11_20261108/`
(unchanged).

---

## 1. Persisted evidence

Canonical `financial_reservations` row:

```text
reservation_id          res_d7990e4d3dc3
root_session_id         turn_turn-9005244b5df841d9b7a07c97e5e9617b
status                  in_flight
estimated_cost_inr      0.167204
estimated_tokens        11598
purpose                 node_task_duration
created_at              1794125893.593874
updated_at              1794125893.6093655
canonical_reservation   c2663432-6c5b-49
```

Per-task FinOps file
`turn_turn-9005244b5df841d9b7a07c97e5e9617b_finops.json`:

```json
"reserved_inr": 0.167204,
"spent_inr": 0.0,
"calls_count": 0,
"active_reservations": {"res_d7990e4d3dc3": {"status": "in_flight"}},
"settled_reservations": {},
"uncertain_reservations": {}
```

Provider invocation ledger: **no** record with
`reservation_id=res_d7990e4d3dc3`.

`financial_call_ledger`: **0** rows for this reservation.

There is no authentic usage receipt, no actual cost, and no settlement.

---

## 2. Classification

The reservation was created and marked `in_flight` immediately before the wire
dispatch. The process was killed before any response or usage receipt. The
dispatch **may** have reached the provider, but the evidence cannot prove
whether it did.

```text
classification: UNCERTAIN
```

This is **not** `released`: a released status would assert the provider was
never called, which the evidence cannot prove. It is **not** `settled`: there
is no authentic usage or cost.

The persisted state is `in_flight`; semantically it is an unresolved dispatch
whose only honest terminal state is `uncertain` with the hold retained.

---

## 3. Required handling

- Do **not** release it to make aggregates look balanced.
- Do **not** invent a usage receipt or an estimated final bill.
- A future process loading this task would transition it to `uncertain` through
  `OrchestrationFinOpsGovernor.reconcile_orphaned_reservations()`.
- The historical evidence must remain `in_flight`; reconciliation is not run
  against historical evidence and no historical file is modified.

The Live12 acceptance run will use a **fresh workspace**; this historical hold
is not part of the new run's reconciliation. Its unresolved status is reported
as a historical fact, not silently cleared.
