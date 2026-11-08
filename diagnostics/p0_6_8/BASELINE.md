# P0.6.8 — Phase A Forensic Baseline

Inspected at `1beced7d` (local == origin, branch
`feat/prompt-cache-stabilization`). All claims below come from the current code
and the P0.6.7 live evidence, not from milestone prose.

## 1. Current planning and execution path

`EngineeringExecutionOrchestrator._run_task_impl`:

1. `RequirementIntelligenceSystem.analyze` → `ProjectSpecification`
   (`src/intelligence/requirement_extractor.py`,
   `requirement_integration.py`).
2. `EngineeringTaskPlanner.build_plan(...)` with `max_nodes`,
   `requested_files`, `task_prompt` (`src/orchestration/planner.py`).
3. `_validate_plan_budget` counts implementation **files**.
4. `ModelExecutionAdapter.execute_node` per target file; one paid dispatch per
   file (`_dispatch_code_prompt`).
5. `VALIDATING_ARTIFACTS` → `DISCOVERING_TESTS` → `EXECUTING_TESTS` →
   `FAILURE_DIAGNOSIS` → `CORRECTING` (bounded) → `VERIFYING` →
   `COMPLETION_EVALUATED` (`src/orchestration/orchestrator.py`).
6. Requirement verification uses plan-scoped files + executed test ids
   (`src/verification/requirement_verifier.py`).
7. Completion gate requires artifacts, executed passing tests, no unresolved
   mandatory requirement, no out-of-scope mutation and no unsettled hold.

## 2. The exact P0.6.7 failure, reconstructed

Prompt (876 bytes, SHA-256
`a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8`,
`diagnostics/p0_6_7/live7/evidence.json` and the signed turn manifest):

> Create src/duration.py with exactly one public function parse_duration(value).
> It parses a duration string into whole seconds. Supported units: h, m, s.
> … Return an int. Raise ValueError … Raise TypeError … Do not accept floats.
> Then create tests/test_duration.py … The test file must import the function
> exactly as `from src.duration import parse_duration`. Run pytest …

Analyzer output at the time (journal `REQUEST_UNDERSTOOD`): five requirements —
REQ-001 module, REQ-002 “Supported units: h, m, s.”, REQ-003 tests sentence,
REQ-004/005 `REASONABLE_DEFAULT` suggestions.

### 2.1 Why FIFO produced the wrong mapping

Before `e60abead`, `build_plan` did:

```python
if requested_pool:
    target_files = [requested_pool.pop(0)]
```

The pool was `[src/duration.py, tests/test_duration.py]`. Requirements were
processed in analyzer order, so REQ-001 (module) got the source file and
**REQ-002 (“Supported units”) got the test file**. There was no notion of a
file role and no check that the requirement and the file describe the same kind
of work.

### 2.2 Why three dispatches were produced for two files

REQ-003 (tests sentence) had no pool entry left. Its analyzer `affected_files`
resolved to `tests/test_duration.py` (the path it mentions), so it became a
third implementation node targeting the same test file. The plan was:

| Node | Target | Requirements |
| --- | --- | --- |
| `task_req_001` | `src/duration.py` | REQ-001 |
| `task_req_002` | `tests/test_duration.py` | REQ-002 |
| `task_req_003` | `tests/test_duration.py` | REQ-003 |

`mutated_files` was 2 but **4 provider dispatches** were claimed
(`node_task_req_001/002/003` + one repair). The P0.6.7 planner had no
duplicate-target rejection.

### 2.3 Why the implementation contradicted the contract

The prompt sent to the provider was the node objective (the full user prompt)
plus a regex-derived “Required public symbol(s)” line. It carried **no
structured return-type, unit, error or extra-API constraints**. The model
produced a `timedelta`-based API with units `d/w` and an `exactly` constant. The
engine had no contract object to compare against; the harness smoke later
showed `parse_duration('1h30m')` raised `ValueError`.

### 2.4 Why the generated test import failed

The test node received the same prose prompt, no authoritative module/import
contract, and no expected-API block. It emitted
`from duration import parse_duration, exactly`; pytest stopped at collection
with `ModuleNotFoundError: No module named 'duration'`. No static cross-file
check existed to catch the unresolved import before spending a test run.

### 2.5 Why the repair auditor rejected the replacement

The failure was classified `TEST_EXPECTATION_DEFECT` (correct: the user pinned
the import path). One repair dispatch returned a rewritten test file that
**removed three test functions** (`test_invalid_inputs_are_rejected`,
`test_exactly_multi_unit_equality`, `test_exactly_inequality`).
`TestIntegrityAuditor.audit_test_modification` rejects any removed test, so the
mutation was refused (`REPAIR_FAILED`) and the loop stopped. The auditor was
right; there was no safe narrow-repair path (import-only rewrite) and no
fallback.

## 3. What `e60abead` fixed

- Files are separated into requested tests/sources using `is_test_file`.
- A test-intent requirement takes a test file, others take source files.
- Every requested file gets a node; same-target nodes are merged.
- The exact prompt now plans **2** implementation work units:
  `task_req_001` (`src/duration.py`, REQ-001+REQ-002) and
  `task_req_003` (`tests/test_duration.py`, REQ-003).

It does **not** address contract extraction, prompt contracts, cross-file
validation, safe test repair, or the role-detection defects below.

## 4. Remaining role-confusion situations (verified by probe)

`is_test_file` is name-only: `(^|/)test_[^/]+\.py`, `*_test.py`, `*.test.*`,
`*.spec.*`. Probes against the current planner:

| Scenario | Current result | Why |
| --- | --- | --- |
| Source file named `src/test_harness.py` | classified TEST | filename pattern wins over directory/intent |
| Test file `tests/checks_duration.py` | test requirement absorbed into the **source** node; synthetic test node has no requirement ids | `is_test_file` is false; the file lands in the source pool |
| One sentence names both `src/a.py` and `tests/test_a.py` | the source requirement is assigned the **test** file; source gets a synthetic node with no ids | requirement intent is “contains the word test” |
| Two sources + two tests | works only because order matches | no source↔test pairing by name/contract |
| Test in `spec/` or `__tests__/` | classified SOURCE | name-only detection ignores directory conventions |
| Test requirement phrased “add coverage” without “test” | depends on path words | no requirement-role classifier |
| Duplicate/alternate path spellings (`.\src\x.py` vs `src/x.py`) | not normalized consistently | `_requested_files` normalizes some separators only |
| Same path named with both source and test intent | silently merged | no conflicting-role rejection |

Additional gaps found:

- **Absorption is round-robin.** Leftover requirements are distributed across
  whichever requested nodes survive (`index % len(requested_nodes)`), so a
  source requirement can be attached to the test node and vice versa.
- **No assignment validation.** Nothing rejects a source requirement on a test
  file, a missing mandatory assignment, a duplicate work unit, or a lost
  requirement id before dispatch.
- **No contract object.** Return type, units, formats, error behavior, exact
  signature, forbidden extras and import contract are not represented anywhere
  downstream; only the symbol-name regex exists.
- **No cross-file validation.** Imports/symbols/signatures are checked only by
  running pytest; a collection error costs a test run and a repair dispatch.
- **Test repair is all-or-nothing.** `TestIntegrityAuditor` rejects any removed
  function but has no inventory/assertion-count model and no import-only path.

## 5. Answers to the Phase A questions

1. **Why FIFO?** `requested_pool.pop(0)` in requirement order; no role model.
2. **Three dispatches?** REQ-002 consumed the test path from the pool; REQ-003’s
   analyzer `affected_files` was the same test path, creating a duplicate-target
   node. No duplicate rejection.
3. **Contract contradiction?** No structured contract reached the provider;
   only prose + symbol names. Return/units/errors/extra-API were unenforced.
4. **Import failure?** No authoritative import/API block in the test prompt and
   no static import validation before execution.
5. **Repair rejection?** The rewrite removed three tests; the auditor correctly
   refuses coverage loss, and no import-only repair existed.
6. **Does `e60abead` fix all causes?** No: it fixes FIFO and duplicate-target
   coalescing for conventional names, but not contract extraction/prompts,
   cross-file validation, safe test repair, directory-based role detection, or
   role-aware absorption.
7. **Remaining confusion:** see §4 table and the additional gaps.

## 6. Plan for P0.6.8 (implemented next)

1. **Contract extraction** (`src/orchestration/contract.py`): structured
   components with role, required symbols/signature, return type, units,
   formats, errors, edge cases, forbidden extras, imports, test cases,
   requirement ids, classification, ambiguity, version/hash; persisted under
   `.crusorai/contracts/`.
2. **Role detection by directory + filename + extension + requirement intent**,
   with ambiguity/conflict rejection instead of guessing.
3. **Assignment + plan validation before dispatch**: every mandatory
   requirement assigned to a role-correct file; every user-named file planned;
   no duplicate work units; no lost ids; demand = unique target files.
4. **Contract-aware prompts** for source and test nodes, sharing the contract
   hash; exact import path and expected API in the test prompt.
5. **Cross-file validation** after generation (AST imports/symbols/signatures/
   return annotations/extra public API), persisted and fed into diagnosis.
6. **Safe test repair**: deterministic import-only rewrite (no dispatch) plus a
   test inventory (functions + assertion count) that accepts maintenance and
   rejects coverage loss.
7. **Lifecycle states**: `CONTRACT_EXTRACTED`, `FILES_ASSIGNED`,
   `PLAN_VALIDATED`, `CROSS_FILE_VALIDATED` adapted into the existing machine.
8. **Adversarial qualification** of the 16 required scenarios, the exact
   historical prompt, contract regressions and repair-integrity cases.
9. **One live acceptance** with the exact historical prompt, then evidence and
   reports.
