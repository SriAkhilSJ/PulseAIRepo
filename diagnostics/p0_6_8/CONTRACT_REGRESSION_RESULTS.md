# P0.6.8 — Contract Regression Results

These tests pin the exact failure patterns P0.6.7 exposed and the contract rules
that prevent them. All run offline (no provider); the lifecycle case uses a
scripted provider double with authentic usage receipts.

| Regression | Mechanism | Test | Result |
| --- | --- | --- | --- |
| `validate_email` silently renamed to `is_valid_email` | contract symbols are authoritative; cross-file `missing_symbol` when the requested name is absent | `TestCrossFile.test_wrong_symbol_fix_contract_regression` | PASS |
| `int` return replaced by `timedelta` | contract `returns`; annotation + usage checks (`return_type_mismatch`, `return_contract_violation`) | `test_return_type_mismatch_is_detected`; `TestExactHistoricalLifecycle` | PASS |
| h/m/s replaced by days/weeks | contract `units` parsed from the user text; surfaced in source and test prompts; lifecycle fixture returns only h/m/s | `test_api_fields_are_structured`; `TestExactHistoricalLifecycle` | PASS |
| Generated test imports a bare module (`from duration import …`) | static `wrong_import_path` + deterministic import rewrite before tests | `test_wrong_import_path_is_detected`; `test_import_rewrite_removes_invented_symbol_safely`; lifecycle `TEST_REPAIR_APPLIED` | PASS |
| Test imports a symbol the module does not define | static `missing_imported_symbol` | `test_missing_symbol_is_detected` | PASS |
| Implementation signature does not match the requested API | contract signature vs AST parameters (`signature_mismatch`) | `test_signature_mismatch_is_detected` | PASS |
| Extra public API/constants (`exactly`) | `exactly one public function` → `extra_public_api`; invented import symbols removed deterministically | `test_extra_public_api_is_detected`; `test_import_rewrite_removes_invented_symbol_safely` | PASS |
| Floats accepted despite "Do not accept floats" | forbidden-contract check (`forbidden_float`) | `test_forbidden_float_is_detected` | PASS |
| Missing expected exception (`DID NOT RAISE`) | classified as implementation defect against the contract's error clause; lifecycle repairs it | `TestExactHistoricalLifecycle`; `test_historical_failure_is_diagnosed_and_repaired` | PASS |
| Test expects `timedelta` while contract fixes `int` | contract-aware diagnosis: `TEST_EXPECTATION_DEFECT`, coverage-preserving test repair | lifecycle (second repair), `audit_test_repair` tests | PASS |
| Tests pass but files violate the contract | cross-file errors block completion even with green tests | `test_tests_pass_but_contract_violation_blocks_completion` | PASS |
| Repair removes test functions | inventory audit rejects; P0.6.7 behavior preserved | `test_removing_a_test_is_rejected` | PASS |
| Repair reduces assertions | assert-count inventory rejects | `test_reducing_assertions_is_rejected` | PASS |
| Repair converts a test to skip/xfail | decorator inventory rejects | `test_skip_is_rejected` | PASS |
| Repair changes test parameters | parameter inventory rejects | `test_parameter_change_is_rejected` | PASS |
| Import-only maintenance | accepted without dispatch; all tests/assertions preserved | `test_import_only_repair_preserves_all_tests`; lifecycle mechanical rewrite | PASS |
| Exact public API across source and test | contract hash shared by both prompts; cross-file import/symbol checks | `test_clean_files_pass`; lifecycle | PASS |

## Contract precedence enforced

1. Explicit user instructions (prompt-derived contract fields).
2. Explicit user-named files and symbols (role assignment + symbols).
3. Necessary technical constraints (derived import path / test path).
4. Existing project conventions (directory-based roles).
5. Optional model suggestions (`REASONABLE_DEFAULT`/`DISCOVERABLE` →
   `optional_suggestions`, never mandatory).

A lower-priority inference cannot override a higher one: the source prompt is
instructed to keep exactly the contract surface, and the cross-file validator
fails a source that adds/changes it. The live model is not trusted to comply;
the checks are what enforce it.

## Explicitly not claimed

A clean static report is not semantic proof. The tests say so in
`validate_cross_file(method="static_ast", note=...)`; execution remains the
authority, and `TestExactHistoricalLifecycle` proves the execution path.
