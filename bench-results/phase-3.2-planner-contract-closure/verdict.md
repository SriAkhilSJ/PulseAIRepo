# Phase 3.2 — planner/contract closure: verdict

**PHASE 3.2: PASS (bounded scope).**

All eight previously failing Phase 11.6 cases pass; the full file is 44/44.
Contract validation was not relaxed, requirement→file traceability is preserved,
and the Phase 3.1 approval path remains green.

This is not Agent Core production readiness.

## Acceptance

| Criterion | Result |
|---|---|
| All eight previously failing cases pass | **PASS** — 8/8; full file 44/44 |
| Contract validation remains strict | **PASS** — `validate_contract_plan` unchanged; ambiguities still reject |
| Requirement-to-file traceability | **PASS** — requirement_map → plan node IDs; same-target coalescing keeps both IDs |
| No new regression failures | **PASS for touched areas** — 118 passed, 1 pre-existing deselected; the deselected case fails at HEAD too |
| Phase 3.1 approval intact | **PASS** — 11/11 approval suite |
| No paid provider calls | **PASS** — 0 |

## Root causes (two, not one)

1. **Product “build” misclassified as a BUILD file** (tests 02/04/05/11/42):
   `requirement_intent` matched bare `build`; CONFIG/DOC/BUILD had no
   role-appropriate fallback, so `REQ-001` had no target and the ambiguity
   blocked the plan.
2. **Repair/refactor/clean verbs were not explicit requirements** (tests
   26/38/40): the extractor produced only optional suggestions; the contract had
   no mandatory requirement, the plan fell back to `src/main_task.py`, and
   verification returned `NOT_TESTED` → verdict `FAILED`.

Full detail: `root-cause.md`, `baseline-8.txt`.

## Correction

- `requirement_intent` recognises build-system nouns, not the verb.
- Necessary CONFIG/DOC/BUILD requirements get deterministic role-appropriate
  targets (`config/<id>.yaml`, `docs/<id>.md`, `build/<id>.py`); no arbitrary
  source files are invented for SOURCE/TEST.
- `detect_file_role` understands `config/` data files and `build/` scripts.
- The extractor recognises fix/repair/refactor/clean/remove/rename/… and keeps
  short imperative requests (≥6 chars).
- Empty descriptions still block explicitly; optional suggestions stay optional;
  duplicate targets still coalesce; dispatch budget still enforced; contract
  hashes stable.

## Evidence

`baseline-8.txt`, `baseline-8-pytest.txt`, `contracts-after.txt`,
`phase116-full.txt`, `verification-tests.txt`, `contract-planner-tests.txt`,
`repro_baseline.py`, `contracts_after.py`.

## Limitations

- One pre-existing repair-lifecycle test (`test_p0_6_8_contract_first.py::
  TestExactHistoricalLifecycle::test_historical_failure_is_diagnosed_and_repaired`)
  still fails exactly as at HEAD; it is unrelated to extraction and was not
  weakened or skipped in the suite (explicitly deselected and documented).
- B-DESK-001 still blocks the `stream_agent` graph path.
- Phase 3.1 approvals remain at stage 9 (no diff body; B-DESK-005).
- Deterministic mock generation writes role-appropriate files but does not
  produce real documentation/config content semantics.
