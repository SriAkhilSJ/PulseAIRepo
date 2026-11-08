# P0.6.9 — Financial Reconciliation

Live run `p0_6_5_20261107T221000_edc9f5de` · session
`session-406f10d4…` · turn `turn-b140891f…` · workspace `ws-3064aec2…`.

## 1. Engineering task (settled)

| Invocation | Model | Tokens in/out | Reservation | Settlement | Cost |
| --- | --- | --- | --- | --- | --- |
| `node_task_duration` | `z-ai/glm-5.3-flash` | 518 / 4386 | `res_68c66c229dcb` | same | ₹0.083510 |
| `node_task_tests_test_duration` | `z-ai/glm-5.3-flash` | 683 / 307 | `res_738c31ef60ba` | same | ₹0.008786 |
| **Task total** | | 1201 / 4693 | 2 | 2 | **₹0.092296** |

Task FinOps: `calls_count=2`, `settled=2`, `uncertain=0`, `active=0`,
`spent_inr=0.092296`. SQLite and JSON agree.

## 2. Auxiliary title (unresolved at shutdown)

| Item | Value |
| --- | --- |
| Claim | guard sequence 3, model `qwen/qwen3.7-flash` |
| Reservation | `res_2f16815efba3` (aux session governor) |
| Estimated hold | ₹0.014149 / 1788 tokens |
| State | **`in_flight`** at evidence capture |
| Settlement | none |
| Usage | none captured |
| Title | empty |
| Invocation ledger record | none (the gateway did not reach a terminal branch) |

Aux FinOps file: `calls=0`, `settled=0`, `uncertain=0`, `active=1`,
`spent_inr=0`.

## 3. Aggregate

| Metric | Value |
| --- | --- |
| Guard claims | 3 |
| Settled invocations | 2 |
| In-flight / unsettled | 1 |
| Aggregate settled cost | ₹0.092296 |
| Outstanding hold | ₹0.014149 |
| Aggregate budget | ₹5.00 (not breached) |
| Task + auxiliary reconciled | **NO** — one in-flight auxiliary hold |

`sum(settled)` = ₹0.092296; `task 0.092296 + aux 0.0` = same. The mismatch is
not arithmetic: one physical provider call was claimed and reserved but the
process was stopped before usage/settlement, so it is correctly unresolved, not
free.

## 4. Root cause

The bridge finalized the turn evidence manifest **before** running the
governed title call (the call was moved next to the terminal frame but still
after `_finalize_evidence`). The acceptance harness treats the manifest
terminal as the end of the turn, stopped the app, and killed the title call
while it was in flight. The reservation therefore never settled and the
auxiliary invocation record was never written.

This is a lifecycle-ordering defect, not a pricing, reservation or provider
failure: the auxiliary reservation was created before dispatch, which is the
required order.

## 5. Fixes committed after the run (offline-proven, not live-proven)

- The governed title call now runs **before** `_finalize_evidence` in the main
  turn path, so the manifest cannot declare completion before accounting
  finishes.
- The harness `finish()` waits up to 90 s for a terminal auxiliary invocation
  record **before** stopping the app (`wait_for_auxiliary_accounting`), as
  defence in depth for slow providers.
- The P0.6.9 test suite covers the wait helper; the gateway still fails closed
  on unpriced/unauthorised/ceiling-incapable calls.

## 6. Verdict consequence

`P0.6.9_ACCEPTANCE_FAILED`: the mandatory criteria "Settlement for every
invocation", "No unaccounted calls", "Auxiliary cost reconciled", "Aggregate
session cost reconciled" and "Automatic session titling exercised" are not met.

No second live run was performed. The engineering task itself passed with
10/10 tests and a clean contract/cross-file report.
