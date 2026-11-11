# Budget Requirements — LIVE12

All amounts INR. Pricing is the verified Velona catalog used by Live11.

---

## 1. Measured unit costs

| Item | Cost |
| --- | --- |
| `z-ai/glm-5.3-flash`, 512 input + 8192 output (worst-case per dispatch) | **₹0.153887** |
| `qwen/qwen3.7-flash`, 512 input + 64 output (aux title max) | **₹0.005179** |
| Live11 source (513/1155) | ₹0.023767 |
| Live11 tests (692/326) | ₹0.009156 |
| Live11 title (461/64) | ₹0.004809 |
| **Live11 observed total** | **₹0.037732** |

---

## 2. Minimum

| Scenario | Minimum |
| --- | --- |
| Normal path at Live11 observed rates | **₹0.037732** |
| One truncation + one bounded recovery + tests (3 × 8192 worst case) + aux | 3 × ₹0.153887 + ₹0.005179 = **₹0.466840** |

A practical authorization should not be set at the observed minimum; one
recovery can triple the source cost.

---

## 3. Maximum under the current dispatch budget

The acceptance harness plans at most **5 physical dispatches**:

```text
5 × ₹0.153887                  = ₹0.769435
aux title (measured max)        = ₹0.005179
total measured maximum          = ₹0.774614
```

If the auxiliary lane is capped at its configured ₹0.20 (rather than the
measured ₹0.005179):

```text
5 × ₹0.153887 + ₹0.20           = ₹0.969435
```

Recommended authorization ceiling: **₹1.20** (₹1.00 task + ₹0.20 auxiliary),
which leaves ~24% headroom over the measured maximum. If autotitle is disabled
for LIVE12, **₹1.00** is sufficient.

No recovery can exceed the 5-dispatch budget; `CRUSORAI_MAX_GENERATION_RECOVERIES`
is clamped 0–2 and every recovery consumes a dispatch and its own reservation.

---

## 4. Hard pre-dispatch enforcement

| Lane | Variable | Enforcement |
| --- | --- | --- |
| Task | `CRUSORAI_TASK_BUDGET_INR` | `OrchestrationFinOpsGovernor.reserve()` rejects before dispatch |
| Auxiliary | `CRUSORAI_AUX_BUDGET_INR` | `GovernedProviderGateway` reserves before client construction/invoke |
| Turn | `CRUSORAI_TURN_COST_BUDGET_INR` | bridge CostGovernor |
| Session | `CRUSORAI_SESSION_COST_BUDGET_INR` | bridge CostGovernor |
| Reserve | `CRUSORAI_RESERVE_BUDGET_INR` | final-response reserve |

Offline proof (`budget_preflight.json`):

```text
task budget 1.00: reserve 1.01 -> BudgetExhaustedError
aux budget 0.20: max cost 2.22 -> AuxiliaryAccountingError
aux client factory never reached
```

The ceiling is enforced **before** a provider client is constructed or invoked.
A UI warning or post-run total is not used as the control.

---

## 5. Historical Live11 hold

`res_d7990e4d3dc3` remains persisted `in_flight` in the historical evidence,
classified **uncertain** (₹0.167204 hold). It is not released, not settled, and
not counted in the LIVE12 run. It does not consume the new run's budget; it is a
separate historical task/workspace.

---

## 6. Recommended authorization

```text
Ceiling: ₹1.20 total
  task:      ₹1.00
  auxiliary: ₹0.20
  title:     on (₹0.20 lane) or off (₹0.00)
```

The separate authorization must state the ceiling explicitly. This preflight
does not authorize any spend.
