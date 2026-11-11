# Historical Live11 Findings (unchanged)

Source: `diagnostics/generation_boundary/live_acceptance/live11_20261108/`.
This file summarizes; it does not modify the original evidence.

## Run

- Run ID: `p0_6_5_20261108T000751_06427b06`
- First session: `session-ae337925e1524bbf8e3a10e417a21962`
- First turn: `turn-36a9e2c226c0473e894e079747a2ee51`
- Second (duplicate) session: `session-93a28e6c97e544de9613d2b1a31a2282`
- Second turn: `turn-9005244b5df841d9b7a07c97e5e9617b`
- Workspace: `C:\Users\Administrator\AppData\Local\Temp\crusor_p0_6_5_ws_k6nc97rs`
- Prompt SHA-256: `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8`

## First turn (authorized)

- Source: `res_d6bcfb8c9a51`, 513/1155 tokens, ₹0.023767, settled.
- Tests: `res_9ad5a0510141`, 692/326 tokens, ₹0.009156, settled.
- Title: `res_2a7451171393`, 461/64 tokens, ₹0.004809, settled.
- `TASK_DELIVERED`: `COMPLETED`.
- In-turn pytest: 15 passed; independent smoke: 9/9.
- No truncation, no recovery.

## Second turn (duplicate)

- Created 0.17 s after first `turn.completed`.
- Source reservation `res_d7990e4d3dc3`, ₹0.167204, 11598 tokens.
- Status `in_flight`; no usage receipt, no invocation record, no settlement.
- Killed by app shutdown 1.1 s after the claim.

## Financial totals

```text
settled spend       ₹0.037732
in-flight hold      ₹0.167204
upper-bound exposure ₹0.204936
authorized ceiling  ₹2.00
```

Guard claims: 4. Provider invocation records: 3. Settlements: 3. Active: 1.
No duplicate settlement. No hidden completed invocation.

## What the repair changes

Historical facts above are preserved. Future startup/shutdown behavior:

- a prior `in_flight` hold becomes `uncertain` (hold retained);
- a prior `reserved` hold is released (dispatch never started);
- a prior `running` submission becomes `failed` (no replay);
- an identical prompt in a brand-new session within 60 s is rejected as a
  duplicate; an intentional repeat can wait out the 60 s window or change the
  prompt.

P0.6.9 remains `P0.6.9_ACCEPTANCE_FAILED`; no live acceptance is claimed.
