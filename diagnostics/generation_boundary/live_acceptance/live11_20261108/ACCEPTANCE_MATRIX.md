# Live Acceptance Matrix

Run: `p0_6_5_20261108T000751_06427b06`
Authorized submission: one. Actual submissions observed: **two** (the second was
app-generated).

---

| Criterion | Result | Evidence |
| --- | --- | --- |
| Starting HEAD / repair unchanged | PASS | `563f5cc2…`; no source changes during run |
| Exact prompt recovered byte-for-byte | PASS | 876 bytes, SHA `a887a669…05f8` |
| One Electron session | PASS | one launch, PID 12804 |
| Exactly one original task submission | **FAIL** | second session `session-93a28e6c…` started at 08:18:13.438 with the same prompt |
| No automatic rerun | **FAIL** | duplicate turn `turn-9005244…` |
| Genuine initial provider invocation | PASS | `inv_b5f9df87…`, 513 in / 1155 out |
| Genuine initial truncation | **NO** | 1155 output tokens; no `IncompleteModelOutputError` |
| Truncated response rejected before mutation | N/A | no truncation occurred |
| Exactly one bounded recovery dispatched | N/A | recovery never entered |
| Recovery has new reservation/invocation, governed, settled | N/A | no recovery |
| Source artifact complete and valid | PASS | 1379 bytes, one `parse_duration`, AST ok |
| No truncated fragment on disk | PASS | complete source written once |
| Test artifact complete | PASS | 1372 bytes, exact import |
| Cross-file validation | PASS | journal `CROSS_FILE_VALIDATED ok=true`, 0 errors |
| In-turn pytest 10/10 | **PASS with deviation** | 15/15 passed, 0 failed; not the literal 10 count |
| Independent smoke 9/9 | PASS | all nine checks true |
| Journal reaches correct terminal state (authorized turn) | PASS | `COMPLETION_EVALUATED ok=true`, `TASK_DELIVERED COMPLETED` |
| No false completion for authorized turn | PASS | artifacts and tests exist and pass |
| Second turn reaches terminal state | **FAIL** | journal stops at `BASELINE_CAPTURED`; killed |
| Claims == physical invocations | **FAIL** | 4 claims vs 3 invocation records |
| Every invocation one terminal disposition | **FAIL** | `res_d7990e4d3dc3` is `in_flight` |
| Successful calls authentic usage + settlement | PASS | 3/3 settled with receipts |
| Missing usage uncertain, never free | **FAIL/UNRESOLVED** | killed call left `in_flight`, not `uncertain` |
| No duplicate settlement | PASS | 3 distinct settlements |
| No hidden completed invocation | PASS | 3 records; fourth claim visible but unresolved |
| No active reservation after terminal reconciliation | **FAIL** | 1 active hold |
| No uncertain reservation for passing verdict | **FAIL** | unresolved hold |
| Auxiliary call included in reconciliation | PASS | title call ₹0.004809 settled |
| Spend ≤ ₹2.00 | PASS | ₹0.037732 settled; ≤₹0.204936 exposure |
| Budget enforced before dispatch | PASS | preflight + per-lane caps |
| Evidence preserved | PASS | this directory + `SHA256SUMS.txt` |
| Historical Live9/Live10 evidence unmodified | PASS | not touched |

---

## Result

```text
GENERATION_BOUNDARY_LIVE_ACCEPTANCE_FAILED
```

The authorized task itself completed normally and did not truncate, so **live
recovery is not proven**. The run fails acceptance because a duplicate
submission started automatically at the end of the first turn and left an
unresolved in-flight reservation, breaking the one-submission rule and the
claim/invocation/settlement reconciliation.

A normal completion is **not** presented as recovery evidence. P0.6.9 remains
`P0.6.9_ACCEPTANCE_FAILED`.
