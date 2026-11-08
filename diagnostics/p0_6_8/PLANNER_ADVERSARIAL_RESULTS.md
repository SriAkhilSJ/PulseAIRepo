# P0.6.8 — Planner Adversarial Results

All cases run against the real `EngineeringContract` extractor,
`EngineeringTaskPlanner` and `validate_contract_plan` (no provider). Command:
`pytest src/tests/test_p0_6_8_contract_first.py -q`. Result on the final tree:
**42 passed, 0 failed** (see OFFLINE_QUALIFICATION.md for the full battery).

| # | Required adversarial scenario | Test | Result |
| --- | --- | --- | --- |
| 1 | One source + one test explicitly named | `test_exact_historical_prompt_plans_two_work_units` | PASS — 2 work units, roles SOURCE/TEST |
| 2 | Source/test requirements interleaved | `test_interleaved_requirements_get_matching_roles` | PASS — each role gets its file |
| 3 | Source filename containing `test` | `test_source_file_named_test_is_source` | PASS — `src/test_harness.py` → SOURCE |
| 4 | Test file without `test_` naming | `test_test_file_without_conventional_name_is_test` | PASS — `tests/checks_a.py` → TEST |
| 5 | Multiple sources + multiple tests | `test_multiple_sources_and_tests_pair_by_stem` | PASS — 4 work units, no duplicates |
| 6 | Requirements sharing one public API | `test_exact_historical_prompt_plans_two_work_units` (REQ-001+REQ-002 on one source) | PASS — coalesced, both ids preserved |
| 7 | Conflicting user-specified function names | `test_conflicting_symbols_are_ambiguous` | PASS — ambiguity recorded, pre-dispatch rejection |
| 8 | Explicit return type | `test_api_fields_are_structured` (`returns == "int"`) | PASS |
| 9 | Explicit units / supported values | `test_api_fields_are_structured` (`units == h,m,s`) | PASS |
| 10 | Ambiguous API contract | `test_no_symbol_for_a_public_api_is_ambiguous` | PASS — ambiguity recorded |
| 11 | Project conventions differ (spec dir, `__tests__`) | `test_test_directory_is_authoritative` | PASS |
| 12 | Coalescing requirements for the same target | `test_exact_historical_prompt_plans_two_work_units`; `test_duplicate_requirement_ids_are_not_lost` | PASS |
| 13 | Duplicate requirement IDs | `test_duplicate_requirement_ids_are_not_lost` | PASS — no duplicate mapping, none lost |
| 14 | Missing / ambiguous user-named file | `test_unknown_user_file_is_rejected` | PASS — ambiguity recorded |
| 15 | Plan exceeds dispatch budget | `test_budget_exceeded_is_refused_before_dispatch` | PASS — `PlanBudgetExceeded` before provider |
| 16 | Test requirement must not be absorbed into source | `test_test_requirement_is_not_absorbed_into_source` | PASS |

## Assignment guarantees checked

- Every mandatory requirement has a role-correct assignment
  (`test_clean_plan_passes`, `test_missing_requirement_assignment_is_rejected`).
- Source requirements never land on test files and vice versa
  (`test_role_conflict_is_rejected`).
- Every user-named file has exactly one work unit
  (`test_duplicate_work_unit_is_rejected`, `test_missing_user_file_is_rejected`).
- Coalescing unions ids and never loses one
  (`test_lost_requirement_is_rejected`).
- Dispatch demand is the number of unique target files
  (`test_clean_plan_passes`: demand 2 for 2 files).
- Demand over capacity is rejected before the first provider call
  (`test_demand_over_capacity_is_rejected`).

## Exact historical reproduction

The prompt is read from `diagnostics/p0_6_7/live7/evidence.json` at test time;
its SHA-256 is asserted to be
`a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8`
(`test_prompt_is_the_exact_historical_request`).

The contract yields exactly two components and two work units:

| Role | File | Requirements |
| --- | --- | --- |
| SOURCE | `src/duration.py` | REQ-001, REQ-002 |
| TEST | `tests/test_duration.py` | REQ-003 |

`TestExactHistoricalLifecycle` then runs the full engine with a scripted
provider reproducing the P0.6.7 artifacts: the wrong bare import, the
`timedelta` return, the extra `exactly` symbol, and tests that call
`total_seconds()`. The engine performs the mechanical import repair (no
dispatch), diagnoses the source defect, repairs it, diagnoses the test
expectation that contradicts the contract, repairs it, re-executes 6/6 tests,
and completes.
