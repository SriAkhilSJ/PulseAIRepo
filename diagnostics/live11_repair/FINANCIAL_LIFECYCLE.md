# Financial Lifecycle and Ledger Source of Truth

## 1. Reservation state machine

```text
                 reserve()
                    |
                    v
                reserved  -------------------- dispatch never started ----> released
                    |
                    | mark_in_flight() immediately before invoke
                    v
                in_flight
                 /      \
     authentic usage     process dies / no receipt / timeout
          |                     |
          v                     v
      reconciled            uncertain
      (settled once)        (hold retained; never free)
```

Every transition is written to the task FinOps JSON atomically and, for
orphan reconciliation, to `.crusorai/finops/lifecycle.jsonl`.

### Live11's orphan

`res_d7990e4d3dc3`, ₹0.167204, 11598 tokens, `status=in_flight`, `spent_inr=0`.
The worker was killed after `mark_in_flight()` and before any response/usage.
No receipt exists, so the only honest terminal state is `uncertain` (hold
retained), not `released` and not a fabricated settlement.

---

## 2. Recovery implementation

`src/orchestration/finops_governor.py`

```python
reconcile_orphaned_reservations(reason)
    active + status == "in_flight" -> mark_uncertain(); retain hold
    active + status == "reserved"  -> release_reservation(); proven no dispatch
    failure                         -> keep hold, report reconciliation failure
```

- Idempotent: a second call sees no active reservations.
- Never invents usage or cost.
- `commit_reservation()` already ignores a duplicate settlement; a late authentic
  usage receipt can still settle an `uncertain` reservation exactly once.
- `release_reservation()` and `commit_reservation()` are idempotent through the
  canonical `BudgetGovernor`.

`src/finops/recovery.py`

- `reconcile_workspace_finops(workspace)`: scans every `*_finops.json` with
  active reservations, constructs the real governor, applies the transitions,
  and records failures without freeing the hold.
- `reconcile_workspace_submissions(workspace)`: `running -> failed` for a
  previous process, so a reconnect cannot replay.
- `reconcile_workspace()`: both, one receipt.

Bridge wiring (`src/bridge/__main__.py`)

- `_reconcile_workspace_once()` runs on the first workspace-bearing frame
  (before any turn starts) and repairs prior-process state.
- `_reconcile_on_shutdown()` runs the in-process governor first, then the
  workspace sweep, in `BridgeServer.run()`'s `finally`.
- A forced kill cannot run the hook; the next process's startup sweep resolves
  the durable file. Neither path fabricates a receipt.

---

## 3. Shutdown / timeout behavior

| Situation | Behavior |
| --- | --- |
| Clean bridge shutdown | `shutdown` frame sets `_shutdown`; `run()` finally reconciles active in-flight holds to uncertain and sweeps known workspaces |
| stdin closes | same `finally` path |
| Forced process termination | no in-process hook; durable `in_flight`/`reserved` state remains; next startup sweep releases `reserved`, marks `in_flight` uncertain |
| Provider timeout / post-dispatch error | existing adapter path marks `uncertain` and writes an `uncertain` invocation record |
| Cancellation | adapter treats it as post-dispatch ambiguity where applicable; never assumes zero cost |
| Slow auxiliary title | governed separately; cannot make a core call free or bypass the task budget |

An interrupted call is never classified as free.

---

## 4. Invocation observability

`src/finops/invocation_context.py` and the adapter now write, where available:

- `submission_id` (contextvar from the bridge's turn),
- `session_id`, `turn_id`, `workspace_id`,
- `invocation_id`, `reservation_id`,
- `started_at` (dispatch start), `response_received_at`,
- provider, model, `requested_output_tokens`,
- `input_tokens`, `output_tokens`, `cached_tokens`,
- literal `finish_reason` (raw or canonical),
- `usage_receipt_present`,
- `actual_cost_inr/usd`,
- `status` (`settled`, `uncertain`, `released`).

Unknown values remain `None`/empty — they are never fabricated. `finish_reason`
was previously missing entirely from the engineering invocation record; Live10
and Live11 could only infer truncation from the error string. The adapter now
records the provider's finish reason on the settled/uncertain record, including
`length` on a truncated-but-paid call.

---

## 5. Authoritative financial record

There is **one authoritative chain** for engineering turns:

```text
guard claim (attempt admission)
    -> canonical financial_reservations row (hold)
    -> provider_invocations.jsonl (physical call attribution + usage)
    -> task FinOps JSON (reservation/settlement/aggregate)
    -> canonical financial_reservations status (reconciled/released/uncertain)
```

- `provider_invocations.jsonl` is the authoritative **invocation** record
  (one line per physical call attempt that reached the gateway).
- The per-task `*_finops.json` is the authoritative **task aggregate** and
  reservation state.
- The canonical `financial_reservations` table is the durable hold/settlement
  ledger.
- `financial_call_ledger` is a **legacy chat-lane table**. It is written by
  `src/agents/cost_governance.record_call()` for chat/agent calls, not by the
  engineering `OrchestrationFinOpsGovernor`. Live11's empty engineering
  `financial_call_ledger` is therefore an integration gap, not a missing
  physical call: the three calls are present in `provider_invocations.jsonl`
  and the task FinOps files.

The repair does **not** write a second competing call ledger. The engineering
records above remain the source of truth. A future consolidation could project
them into `financial_call_ledger`, but that is an explicit migration, not a
silent dual write.

### Reconciliation rules

| Record | Proves |
| --- | --- |
| Guard claim | an attempt was admitted under the acceptance budget |
| Invocation record | a physical call reached the governed gateway |
| Usage fields | what the provider reported |
| Task FinOps settlement | what the task charged |
| Canonical reservation | the durable hold's terminal state |

Live11's 4 claims vs 3 invocation records remains a historical fact: the fourth
claim (duplicate turn) was killed between claim and response and left the hold
`in_flight`. The repair makes that same state resolve to `uncertain` on the next
startup, with the hold retained and no invented cost.
