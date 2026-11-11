# P0.6.8 — Findings

## 1. Final verdict

**`P0.6.8_ACCEPTANCE_FAILED`.**

The exact P0.6.7 historical task now succeeds end-to-end through the real
desktop path: contract extracted, two role-correct work units, real provider
dispatches, 10/10 in-turn tests, clean cross-file report, `VERIFIED`, turn
`completed`. The acceptance is still **failed** because the dispatch ledger
recorded **one unaccounted auxiliary provider call**: the session auto-titler
used the auxiliary model (`qwen/qwen3.7-flash`) inside the acceptance turn and
no FinOps reservation settled it (3 claims, 2 settlements). That violates the
"no unaccounted dispatches / financial accounting covers every actual provider
invocation" criterion.

| Summary | Value |
| --- | --- |
| Run | `p0_6_5_20261107T211727_fa1f0117` |
| Turn | `turn-5bd30b1c85e84807a830727a118d54bf` |
| Prompt SHA-256 | `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8` (exact P0.6.7 prompt) |
| Contract | 2 components: SOURCE `src/duration.py` (REQ-001/002), TEST `tests/test_duration.py` (REQ-003) |
| Plan | 2 work units, demand 2, no ambiguities |
| Cross-file | clean (static AST) |
| In-turn tests | 10 passed / 0 failed (pytest exit 0) |
| Repairs | 0 (not needed) |
| Turn status | `completed` |
| Task dispatch claims / settlements | 2 / 2 (₹0.125588) |
| Guard claims | 3 (third = auxiliary auto-title, model `qwen/qwen3.7-flash`) |
| Offline suite | **293 passed, 0 failed** |

## 2. Root cause of P0.6.7 (confirmed from code and evidence)

- FIFO file assignment gave the test file to a non-test requirement and
  dispatched the same path twice.
- No structured contract reached the provider: return type, units, errors and
  extra-API prohibitions were unenforced, so `timedelta` replaced `int`.
- No authoritative import contract in the test prompt and no static cross-file
  check, so the bare `from duration import …` reached pytest.
- The all-or-nothing test audit rejected a rewrite that dropped three tests;
  there was no import-only or inventory-preserving repair.

## 3. Contract extraction (new)

`src/orchestration/contract.py` derives a structured `EngineeringContract` from
the user's own words before planning:

- required symbols and signatures (`parse_duration(value)`),
- return type (`int`),
- supported units (`h, m, s`),
- error clauses (`ValueError`, `TypeError` and their conditions),
- forbidden extras (`floats`, extra public APIs/CLI),
- import contract (`from src.duration import parse_duration`),
- required test cases (`'1h30m' -> 5400`, `'1h1h' raises ValueError`, …),
- edge cases, requirement ids, classification, ambiguities.

Persisted under `.crusorai/contracts/<task>_contract.json` with a version and
contract hash. The test component inherits the public API from the source
component, so both prompts share the same contract hash. Optional analyzer
suggestions (REQ-004/005) are recorded and never block completion. Conflicting
symbols or a missing public symbol are ambiguities that reject the plan before
dispatch.

## 4. Planner and file assignment

- `build_plan(contract=...)` emits exactly one work unit per contract component;
  the verification node is free.
- File roles are detected by directory + filename + extension + requirement
  intent (`src/test_harness.py` is SOURCE; `tests/checks_a.py` and `spec/` are
  TEST; config/doc/build are separated).
- One sentence naming both source and test maps the requirement to both files.
- `validate_contract_plan` rejects, before any provider call: missing
  assignments, role conflicts, duplicate work units, lost ids, missing
  user-named files, demand over capacity, and mandatory ambiguities. A rejected
  plan journals `PLAN_REJECTED` and spends nothing.

## 5. Cross-file consistency

After generation and after every repair, static AST checks cover imports,
imported symbols, signatures, return annotations, `timedelta`-vs-`int`,
extra public APIs and forbidden floats. The report is persisted and journaled
(`CROSS_FILE_VALIDATED`). It explicitly states that a clean static report is not
semantic proof; execution is authoritative. A contract violation blocks
completion even when tests pass, and requirement records are marked `FAILED`
when a violation references them.

## 6. Test integrity and repair

- A stable inventory records test functions, assertion counts, exception
  assertions, parameters and decorators.
- Import-only repair is deterministic and dispatch-free; it rewrites bare
  project imports and removes invented import symbols only when unused.
- Provider test repairs are accepted only if every test, assertion, exception
  assertion and parameter is preserved (skip/xfail conversions rejected).
- Test expectations that contradict the contract (e.g. `timedelta.total_seconds`
  on a contract `int`) are classified as test defects and repaired under that
  audit; a `DID NOT RAISE` failure is an implementation defect.

## 7. Offline qualification

**293 passed, 0 failed, 0 skipped** in the full battery (see
`OFFLINE_QUALIFICATION.md`). The exact historical prompt is read from the P0.6.7
evidence at test time and its SHA is asserted; the scripted-provider reproduction
runs the same failure class and completes after a mechanical import repair + two
evidence-backed repairs (6/6 tests, 4/4 settled).

## 8. Live acceptance result

All UI, bridge, contract, plan, cross-file, test, verification and financial
task criteria passed. The task's two provider calls were reserved and settled
(2/2, 0 active, 0 uncertain, ₹0.125588, SQLite reconciled).

The single failure is dispatch reconciliation: the guard claimed a third
dispatch using the **auxiliary** model, because the session auto-titler fired
during the acceptance turn. The auxiliary client is built through
`RetryLLMProxy`, so the guard correctly counted it; it is not task work and no
task FinOps reservation settled it.

### Fix committed after the run (not live-proven)

- `build_acceptance_env` now sets `CRUSORAI_AUTOTITLE=off`.
- `BridgeServer._auxiliary_llm_allowed()` refuses any auxiliary model call
  whenever `CRUSORAI_ACCEPTANCE_RUN_ID` is set, independent of the env flag.
- Two tests pin the env value and the bridge refusal.

No second live run was performed. The milestone authorizes exactly one, and a
failed criterion is not converted into a pass.

## 9. Actual cost and dispatch accounting

- Task: 2 dispatches, 1 attempt each, 2 settled, ₹0.125588, 1192 input /
  6489 output tokens.
- Auxiliary: 1 claim (auto-title), not settled by task FinOps.
- Guard: 3/5 used, never exceeded; no retry, no failover.

## 10. Invariant 7 and secrets

Invariant 7 maintained (0 changed files, 0 drift, 0 undeclared). Secret scan of
all changed files: 0 real hits; the only scanner hit is the in-memory approval
token variable and is a reviewed false positive.

## 11. Remaining defects

1. **Auxiliary provider calls are outside FinOps.** The fix suppresses them in
   acceptance mode; for normal product use, session titling still spends tokens
   not recorded by the task governor. This needs its own accounting lane.
2. **Static consistency is shape, not semantics.** Behavior is proven only by
   executed tests.
3. **Test repair is prompt-driven** when an expectation must change; the
   inventory prevents weakening but the provider must still produce a valid
   rewrite. Import repair is deterministic.
4. **Per-file contract divergence** (different return types for different source
   files in one prompt) is flagged, not modeled per component.
5. **No second live run**: the acceptance-isolation fix is offline-proven only.

## 12. Commit map

| Commit | Content |
| --- | --- |
| `72301431` | contract engine, planner, orchestrator, prompts, cross-file, diagnosis |
| `83bfd7cf` | 42 contract/planner/cross-file/repair tests + P0.6.8 gates |
| `4b24f8c7` | acceptance harness contract/plan/cross-file evidence |
| `76cbcaeb` | baseline, adversarial/regression results, offline qualification |
| `92396a5c` | acceptance isolation (autotitle off) + 2 tests + live8 evidence/docs |

Branch `feat/prompt-cache-stabilization`; local HEAD == origin verified after
push.
