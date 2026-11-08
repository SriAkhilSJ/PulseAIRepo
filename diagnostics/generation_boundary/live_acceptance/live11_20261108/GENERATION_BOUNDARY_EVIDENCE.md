# Generation Boundary Evidence — First (Authorized) Turn

This file covers the first turn only. It is the only turn that received the
authorized submission. The duplicate second turn is documented in
`RUN_SUMMARY.md` and `FINANCIAL_RECONCILIATION.md`.

---

## 1. Physical provider calls (first turn)

| # | Purpose | Reservation | Invocation | In | Out | Cost | Status |
|---|---|---|---|---|---|---|---|
| 1 | `node_task_duration` | `res_d6bcfb8c9a51` | `inv_b5f9df87b6744fc29c635297397fc5cf` | 513 | **1155** | ₹0.023767 | settled |
| 2 | `node_task_tests_test_duration` | `res_9ad5a0510141` | `inv_632e6d84c5fa4bee9ca6d7d93891171e` | 692 | 326 | ₹0.009156 | settled |
| 3 | `session_title` (aux) | `res_2a7451171393` | `inv_03ac979301b14c05bb56ec15139cf651` | 461 | 64 | ₹0.004809 | settled |

All three have authentic usage receipts (`usage_record_id` present) and one
settlement each. No duplicate settlement.

The title model returned no usable text; the bridge used its local fallback.
The aux call is still a real, governed, settled provider invocation and is
included in the total.

---

## 2. Was there truncation?

**No.**

- The source invocation produced **1155 output tokens**, far below the requested
  8192 ceiling.
- No `IncompleteModelOutputError` appears in the journal or logs.
- No `GENERATION_RECOVERIES` journal event exists.
- No ledger row has `operation_type="recovery"`.
- The source was accepted and written only after extraction, `ast.parse`,
  contract and cross-file validation.

The invocation ledger does not persist `finish_reason`. The evidence therefore
proves **normal completion by outcome**, not a recorded literal `stop` string.
No evidence of truncation exists.

---

## 3. Was there recovery?

**No.** The bounded recovery path was never entered because the first response
was complete. This run cannot prove live recovery.

---

## 4. Artifact integrity

| Check | Result |
| --- | --- |
| `src/duration.py` exists | yes |
| Public `parse_duration` definitions | exactly 1 |
| AST parse | ok |
| `tests/test_duration.py` exists | yes |
| Contract import | `from src.duration import parse_duration` |
| In-turn pytest | **15 passed, 0 failed, 0 errors** |
| Independent smoke | **9/9 true** |
| Cross-file validation | `ok=true`, 0 errors |
| Mutations | 2, both `APPLIED` / `VERIFIED` |
| Unrelated files mutated | no (workspace inventory: README, diagnostics, src/duration.py, tests/test_duration.py, `.crusorai/`) |

Source SHA-256: `d55edeae7703db6505bd37de573049984d39c5ed3e81723f21f6b3782f0d0e43`
Tests SHA-256: `b4b39e38653890e3e837fb7f4868f5bb4799edec8402e15a2597df68a1eac8c2`

The preserved copies are under `evidence_workspace/artifacts/`. Re-running
pytest on those copies offline gives **15 passed**.

The historical acceptance shape was 10 tests; this model wrote 15 parameterized
test IDs covering the same required behaviors. The literal 10/10 count was not
reproduced, but every required behavior is present and passing.

---

## 5. Orchestration journal (first turn)

Terminal sequence:

```text
PLAN_GENERATED
IMPLEMENTATION_DONE            mutated_files = [tests/test_duration.py, src/duration.py]
ARTIFACTS_VALIDATED
CROSS_FILE_VALIDATED            ok = true
TESTS_DISCOVERED
TESTS_EXECUTED                  total=15 passed=15 failed=0 errors=0
PRODUCTION_READINESS_EVALUATED
COMPLETION_EVALUATED            ok=true blocked=false verdict=VERIFIED
TASK_DELIVERED                  verdict=COMPLETED
```

Contract hash for the first turn: `0043b1263e870c7fe07d73f1e517deed0cac0eb508ece2d291e5d19e132fa654`.

The preserved journal is `evidence_workspace/journals/first_turn.jsonl`.

---

## 6. Conclusion

The authorized first turn is a **normal live generation**, with complete
artifacts and passing verification. It does **not** exercise or prove the
generation recovery path. The run's overall verdict is failed for reasons
outside generation (duplicate submission and unresolved accounting).
