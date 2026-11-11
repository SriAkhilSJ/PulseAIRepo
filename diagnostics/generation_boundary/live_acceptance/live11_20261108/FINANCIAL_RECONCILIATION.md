# Financial Reconciliation — Live Run

**Result: FAILED.** The authorized ₹2.00 ceiling held, but the run ended with a
second, duplicate turn whose source reservation was left `in_flight`, and with
4 acceptance-guard claims against 3 provider invocation records.

All amounts are INR.

---

## 1. The four guard claims

`acceptance_dispatch.json`:

| Claim | Model | Turn | Matching invocation record? |
| --- | --- | --- | --- |
| 1 | `z-ai/glm-5.3-flash` | first turn, source | yes — `inv_b5f9df87…` |
| 2 | `z-ai/glm-5.3-flash` | first turn, tests | yes — `inv_632e6d84…` |
| 3 | `qwen/qwen3.7-flash` | first turn, title | yes — `inv_03ac9793…` |
| 4 | `z-ai/glm-5.3-flash` | **second (duplicate) turn, source** | **no** |

Guard: `dispatches_used=4`, `max_dispatches=5`, `dispatches_remaining=1`.
The guard itself worked; the problem is that a fourth claim existed at all and
never reached a terminal record.

---

## 2. Settled provider invocations

`provider_invocations.jsonl` — 3 records, all `settled`:

| Purpose | Reservation | Input | Output | Actual cost |
|---|---|---|---|---|
| `node_task_duration` | `res_d6bcfb8c9a51` | 513 | 1155 | ₹0.023767 |
| `node_task_tests_test_duration` | `res_9ad5a0510141` | 692 | 326 | ₹0.009156 |
| `session_title` (aux) | `res_2a7451171393` | 461 | 64 | ₹0.004809 |

**Settled total: ₹0.037732** (engineering ₹0.032923 + aux ₹0.004809).
Each has one authentic usage receipt and one settlement. No duplicate settlement.

---

## 3. The unresolved second turn

At 08:18:13.438 the app started a second session
(`session-93a28e6c97e544de9613d2b1a31a2282`) and turn
(`turn-9005244b5df841d9b7a07c97e5e9617b`) with the exact same prompt.

Its FinOps file:

```json
{
  "accounting": {"budget_inr": 1.8, "spent_inr": 0.0, "calls_count": 0},
  "active_reservations": {
    "res_d7990e4d3dc3": {
      "amount_inr": 0.167204,
      "tokens": 11598,
      "purpose": "node_task_duration",
      "status": "in_flight"
    }
  },
  "settled_reservations": {},
  "uncertain_reservations": {}
}
```

The canonical `financial_reservations` table confirms:

```text
res_d6bcfb8c9a51  reconciled
res_9ad5a0510141  reconciled
res_2a7451171393  reconciled
res_d7990e4d3dc3  in_flight   <-- unresolved
```

Electron was stopped at 08:18:14.556, about 1.1 s after the claim, killing the
call before any usage receipt or settlement. The hold was not converted to
`uncertain` because the process was terminated; for acceptance it is an
**unresolved active hold**.

The fourth claim has **no** invocation record and **no** settlement. The actual
provider billing for it is unknown. The reservation amount (₹0.167204) is the
upper-bound exposure.

---

## 4. Totals

| Metric | Value |
| --- | --- |
| Settled actual spend | **₹0.037732** |
| Unresolved in-flight hold | ₹0.167204 |
| Upper-bound exposure | **₹0.204936** |
| Authorized ceiling | ₹2.00 |
| Breach | **No** |
| Duplicate settlement | No |
| Hidden completed invocation | No |
| Active reservation at terminal reconciliation | **1** |

Even at the upper bound, spend is far below ₹2.00. The failure is reconciliation
and duplicate submission, not a budget breach.

---

## 5. Budget enforcement (pre-dispatch)

The run used a hard decomposition, verified before launch by an offline
provider-free check (`preflight_budget.json`):

| Lane | Cap | Enforcement |
| --- | --- | --- |
| Engineering task | ₹1.80 (`CRUSORAI_TASK_BUDGET_INR`) | `OrchestrationFinOpsGovernor.reserve()` rejects before dispatch |
| Auxiliary / title | ₹0.20 (`CRUSORAI_AUX_BUDGET_INR`) | `GovernedProviderGateway` reserves before client construction/invoke |
| Turn/session | ₹2.00 | bridge CostGovernor limits |

Preflight proof (no provider calls):

- engineering reserve of ₹1.81 with a ₹1.80 budget → `BudgetExhaustedError`;
- a second reserve exceeding the remaining ₹0.10 → `BudgetExhaustedError`;
- aux max-cost estimate ₹1.85 against a ₹0.20 budget → refused before the client
  factory was reached (`aux_client_factory_not_reached=true`).

First-turn actuals (₹0.032923 task, ₹0.004809 aux) and the second-turn hold
(₹0.167204 task) all fit their lanes. The caps were enforced; the duplicate
submission was not prevented by the financial layer because it was a new turn
with a fresh ₹1.80 task budget, not a single call exceeding a cap.

---

## 6. Invariant checks

| Required invariant | Result |
| --- | --- |
| Claims equal physical provider invocations | **FAIL** — 4 claims, 3 records |
| Every invocation has one terminal financial disposition | **FAIL** — 1 in-flight reservation |
| Successful invocations have authentic usage and settlement | PASS — 3/3 |
| Missing usage classified uncertain, never free | **FAIL/UNRESOLVED** — the killed call is `in_flight`, not `uncertain` |
| No duplicate settlement | PASS |
| No hidden provider invocation | PASS for completed calls; the fourth claim is visible but unresolved |
| No active reservation after terminal reconciliation | **FAIL** — `res_d7990e4d3dc3` |
| No uncertain reservation for a passing verdict | **FAIL** — unresolved hold |
| Total provider spend does not exceed ₹2.00 | PASS — ₹0.037732 settled, ≤₹0.204936 exposure |

---

## 7. Evidence-quality notes

- The harness's `financial.orchestrator` classification covers the **first
  turn only** and reports `ok=true`; it does not include the second turn.
- `session_financials` does expose the second turn and reports
  `active_count=1` and total settled ₹0.037732.
- The harness's `cost_governance` lane was **unavailable**
  (`no such table: financial_reservations`) because it read
  `home/sessions.db`; the canonical financial tables live in the workspace
  `.crusorai/sessions.db`, preserved at
  `evidence_workspace/finops/sessions.db`.
- The canonical `financial_call_ledger` table is empty; the three calls are
  recorded in `provider_invocations.jsonl` and the per-task FinOps JSON files.
  This is a ledger-coverage gap, not evidence of a hidden cheap call.

None of these notes change the verdict: the run has one unresolved physical
claim and one active reservation.
