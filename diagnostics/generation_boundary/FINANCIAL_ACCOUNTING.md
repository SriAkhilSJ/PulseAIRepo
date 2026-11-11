# Financial Accounting — Generation Recovery

Status: **offline-tested with scripted receipts**. No real money was spent in
this repair. Live10's historical accounting is preserved unchanged.

---

## 1. Live10 is not a financial failure

From `diagnostics/p0_6_9/live10/provider_invocations.jsonl` and
`FINAL_REACCEPTANCE.md`:

| Metric | Value |
| --- | --- |
| Physical claims | 2 |
| Settled invocations | 2 |
| Aggregate calls | 2 |
| Source | `res_6988ef02e5e6`, 512 in / 8192 out, ₹0.153887 |
| Tests | `res_d75fe218ac8c`, 691 in / 384 out, ₹0.010265 |
| Total | **₹0.164152** |
| Active reservations | 0 |
| Uncertain reservations | 0 |

The source call was settled correctly for the tokens the provider actually
produced. The turn failed because the output was incomplete, not because the
ledger was inconsistent. No auxiliary/title call occurred because the turn died
before titling.

---

## 2. The invariant is unchanged

```text
physical provider claims
    ==
provider invocation records
    ==
accounted reservations / settlements
```

The repair adds no accounting shortcut:

- `_dispatch_code_prompt()` still reserves **before** invoking the provider.
- The acceptance guard still counts every physical claim.
- Usage must be authentic; a missing receipt after dispatch is
  `MissingUsageReceiptError` and the reservation becomes **uncertain**, not free.
- Actual cost is calculated from the receipt by the existing governor.
- Settlement happens exactly once, in the existing dispatch path.
- Pre-dispatch refusals (client construction, unenforceable ceiling, budget
  rejection) release the reservation.
- Post-dispatch ambiguity retains the hold as uncertain.

No budget manager, cost calculator or settlement path was duplicated.

---

## 3. Recovery accounting

A recovery is an ordinary physical dispatch through the same gateway, with:

| Field | Recovery value |
| --- | --- |
| `purpose` | `node_<node_id>_recovery<N>` |
| `operation_type` | `"recovery"` |
| `reservation_id` | new, unique |
| `invocation_id` | new, unique |
| `usage_record_id` | `<reservation_id>:usage` |
| `settlement_id` | `<reservation_id>` |
| cost | computed from its own receipt |
| status | `settled`, or `released`/`uncertain` by the existing rules |

It is never folded into the original call, never described as free, and never
skipped by the ledger. The only new classification is the
`operation_type="recovery"` label; the accounting machinery is the P0.6.9 one.

---

## 4. Bounds that still apply

| Bound | Recovery behaviour |
| --- | --- |
| Acceptance guard | Requires `active_guard().remaining > 0`; at zero, no second claim. |
| Dispatch budget | Recovery consumes one of the existing dispatches. |
| Cost cap | Recovery must reserve within the existing ₹ cap; a breach blocks it. |
| Token budget | Recovery is reserved through the same governor. |
| Output ceiling | Same effective provider-aware ceiling; no increase. |
| Attempts | 1 by default, env-clamped to 0–2. |
| Timeout | Existing per-call timeout and client construction path. |
| Cancellation | Checked before recovery; cancelled turns do not spend. |

No unbounded loop exists. The loop condition is `recoveries <
max_recoveries`, and `max_recoveries` is clamped at 2 even if the environment
variable is set higher.

---

## 5. Offline accounting evidence

The historical replay asserts, for the success path:

```text
accounting.calls_count          == 3
len(settled_reservations)       == 3
len(active_reservations)        == 0
len(uncertain_reservations)     == 0
len(invocation records)         == 3
all records status              == "settled"
recovery records                == 1
distinct reservation ids        == 3
sum(actual_cost_inr)            == governor.spent_inr (6 dp)
```

The fake provider returns authentic-shaped usage receipts; costs are simulated.

Negative-path assertions:

| Scenario | Accounting result |
| --- | --- |
| First call truncated, recovery valid | 3 settlements; 1 `recovery` row |
| First + recovery both truncated | 3 physical calls (source + recovery + independent tests node); no active/uncertain; source absent |
| Recovery missing usage | ≥1 **uncertain** reservation retained; not free |
| Guard exhausted | exactly 1 claim; no second reservation |
| Cancelled before recovery | exactly 1 claim |
| Recovery disabled | exactly 1 claim |

`calls_count == len(llm.prompts)` is asserted in the failure replays, so a hidden
provider call would fail the test.

---

## 6. Coverage gaps — unchanged and not claimed

This repair does **not** bring these paths into governed accounting:

- chat graph;
- summarizer;
- compaction;
- self-curation;
- planner helpers;
- One-Shot;
- inline completions.

The governed paths remain engineering implementation, engineering repair,
auxiliary session titling, and now engineering generation recovery through the
same gateway. P0.6.9's historical live verdict is not changed.

---

## 7. Spend in this task

```text
Provider spend: ₹0.00
Live calls: 0
Electron acceptance runs: 0
Paid benchmarks: 0
Real title calls: 0
```

All receipts in this report are scripted test fixtures.
