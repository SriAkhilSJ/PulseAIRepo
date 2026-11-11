# Live Acceptance Run — Generation Boundary

**Verdict: `GENERATION_BOUNDARY_LIVE_ACCEPTANCE_FAILED`**

This is the record of the one authorized live Electron session. No rerun was
performed. P0.6.9 remains `P0.6.9_ACCEPTANCE_FAILED`.

---

## 1. Run identity

| Item | Value |
| --- | --- |
| Run ID | `p0_6_5_20261108T000751_06427b06` |
| Starting / ending HEAD | `563f5cc2cb516e9da29c6db9088a516933f24f79` |
| Branch | `feat/prompt-cache-stabilization` |
| First session ID | `session-ae337925e1524bbf8e3a10e417a21962` |
| First turn ID | `turn-36a9e2c226c0473e894e079747a2ee51` |
| Workspace | `C:\Users\Administrator\AppData\Local\Temp\crusor_p0_6_5_ws_k6nc97rs` |
| Electron PID | 12804 |
| Bridge PID | 4356 |
| Prompt length / SHA-256 | 876 bytes / `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8` |
| Start / finish (UTC) | 08:07:51.537 / 08:18:19.116 |

The prompt was recovered byte-for-byte from `diagnostics/p0_6_7/live7/evidence.json`
and matched the required SHA before submission (`prompt.txt` in this directory).
The harness records `prompt_typed.typed_sha256` as the same value.

---

## 2. Timeline

| Time (UTC) | Event |
| --- | --- |
| 08:07:51 | Harness starts; one Electron launch |
| 08:08:20.623 | One real Enter in the composer; composer clears |
| 08:08:26.978 | First turn manifest appears; SHA matches |
| 08:08:28–08:08:34 | Source, tests and title provider calls settle |
| 08:08:52.481 | First turn `TASK_DELIVERED` — `COMPLETED` |
| 08:08:52–08:18:13 | Bridge blocks in `_engine_build` while emitting `session_info` inside the title path; terminal frame delayed |
| 08:18:13.263 | First turn `turn.completed` (`completed=true`, 588.625 s) |
| 08:18:13.438 | **Second session** `session-93a28e6c…` starts with the same prompt |
| 08:18:13.55 | Second turn plans 2 units; source reservation `res_d7990e4d3dc3` becomes `in_flight` |
| 08:18:14.013 | Harness observes first-turn terminal |
| 08:18:14.556 | Harness stops Electron, killing the second turn |

The harness recorded exactly one submission gesture (`method: "enter"`, no
send-button click). The second turn is therefore an **app-side duplicate
submission**, not a second harness action and not an intentional rerun. It
created a new session and a new turn from the same prompt.

---

## 3. What the authorized task did

The first turn genuinely completed:

- `src/duration.py` created (1379 bytes), one public `parse_duration`.
- `tests/test_duration.py` created (1372 bytes).
- In-turn pytest: **15 passed, 0 failed, 0 errors**.
- Harness independent smoke: **9/9 true**.
- `CROSS_FILE_VALIDATED`: `ok=true`.
- `COMPLETION_EVALUATED`: `ok=true`, `blocked=false`, verdict `VERIFIED`.
- `TASK_DELIVERED`: verdict `COMPLETED`.
- Exactly two file mutations, both `APPLIED` / `VERIFIED`.

The generated test file parametrizes the required cases into 15 test IDs; the
historical acceptance shape was 10. All required behaviours are covered and pass,
but this run does not reproduce the literal 10/10 count.

---

## 4. Generation boundary outcome

| Question | Answer |
| --- | --- |
| Genuine initial truncation? | **No.** Source output was 1155 tokens (< 8192); no `IncompleteModelOutputError`; the source passed extraction, AST, contract, tests and smoke. |
| Genuine recovery? | **No.** No `GENERATION_RECOVERIES` event; no `operation_type="recovery"` ledger row. |
| Initial completion normal? | Yes, on the evidence available. The invocation ledger does not persist `finish_reason`; the recorded outcome is a complete accepted artifact. |
| Recovery proven live? | **No.** |

This run can therefore never be `GENERATION_BOUNDARY_LIVE_RECOVERY_PROVEN`.
Absent the duplicate below, it would have been
`GENERATION_BOUNDARY_LIVE_NORMAL_PATH_ONLY`.

---

## 5. Why the verdict is FAILED, not NORMAL_PATH_ONLY

Three mandatory failures:

1. **Second task submission.** A second session/turn with the exact same prompt
   started automatically when the first turn completed. The authorization
   permits exactly one original submission and no automatic reruns.
2. **Unresolved financial disposition.** The second turn created reservation
   `res_d7990e4d3dc3` (₹0.167204) and left it `in_flight`. No usage receipt or
   settlement exists because Electron was stopped.
3. **Claim/invocation mismatch.** The acceptance guard recorded 4 claims; the
   provider invocation ledger has 3 records. The fourth claim has no terminal
   invocation record. The required invariant
   `claims == invocation records == settlements` does not hold.

The harness's own verdict was already `P0.6.9_ACCEPTANCE_FAILED`; its in-turn
snapshot read the new second turn (journal stopped at `BASELINE_CAPTURED`) rather
than the completed first turn. That snapshot race is a reporting defect, but it
does not erase the three failures above, and this record does not use it to
downgrade or upgrade the result.

---

## 6. Spend

| Item | Amount |
| --- | --- |
| Settled provider spend | **₹0.037732** |
| In-flight hold (second turn) | ₹0.167204 |
| Upper-bound exposure | **₹0.204936** |
| Authorized ceiling | ₹2.00 |
| Breach | No |

The ₹2.00 ceiling held. The failure is duplicate-submission and accounting
reconciliation, not budget overrun. Full detail:
`FINANCIAL_RECONCILIATION.md`.

---

## 7. Verdict

```text
GENERATION_BOUNDARY_LIVE_ACCEPTANCE_FAILED
```

Reasons: one real initial generation completed normally (no recovery), a second
automatic submission occurred, and its in-flight reservation left the run with
4 claims vs 3 invocation records. Recovery remains unproven live. P0.6.9 remains
`P0.6.9_ACCEPTANCE_FAILED`.
