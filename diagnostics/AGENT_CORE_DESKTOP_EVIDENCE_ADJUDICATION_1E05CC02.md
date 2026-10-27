# Agent Core desktop evidence adjudication — `1e05cc02`

- **Date:** 2026-10-25 (America/Los_Angeles)
- **Evidence commit:** `1e05cc0205c9f065a192fbf41079cce83203696a`
- **Claimed implementation:** `b22d6efce922357ca7c04b3e59106db2da86849d`
- **Protocol:** `diagnostics/DESKTOP_AGENT_RERUN_B22D6EFC.md`
- **Decision:** **REJECTED — not desktop acceptance evidence**

Do not cite this package as an Agent Core desktop PASS. The raw artifacts remain
preserved at
`diagnostics/desktop-evidence/agent-core-b22d6efc/`; this adjudication does not
rewrite or remove any submitted artifact.

## 1. Decision

The submission's A–I PASS matrix is unsupported. Several failures are each
independently disqualifying:

1. every captured A–F session used the explicitly prohibited reused workspace
   `C:\Users\Administrator\Downloads\testCRUSOR`;
2. the package contains **zero screenshots** and no `screenshots/` directory;
3. the required complete engine/build log is absent;
4. G and I are terminal/unit-test substitutes, not desktop sessions;
5. C did not execute `write_file` and instead read a pre-existing target;
6. F's terminal call was canceled, no cleanup receipt exists, and the trace has
   no finalization row;
7. H treats unfinished F as finalized and contradicts numeric cache telemetry;
8. the required G/I session mappings, traces, reports, and SQLite attribution
   are absent.

The package does contain useful raw receipts for limited mechanics in A, B, D,
and E. Those receipts do not cure the workspace, attribution, screenshot,
build-identity, restart, and completeness failures.

## 2. Scope and preservation

`git show --name-only 1e05cc02` confines the evidence commit to the 22 files
under `diagnostics/desktop-evidence/agent-core-b22d6efc/`. The package contains:

- `RESULTS.md`, `provenance.txt`, and `sessions.json`;
- six A–F JSONL traces and six A–F reports;
- one incomplete H audit;
- three SQLite JSON extracts;
- terminal/unit-test logs for G/I and a broad pytest run.

It does **not** contain any PNG/JPEG screenshot, screenshot manifest, complete
engine log, SQLite query/schema README, G before/after restart receipt, or G/I
desktop trace/report.

## 3. Machine validation

A fail-closed validator now exists at:

```text
scripts/validate_agent_core_desktop_evidence.py
```

Command:

```bash
python scripts/validate_agent_core_desktop_evidence.py \
  diagnostics/desktop-evidence/agent-core-b22d6efc \
  --json-out /tmp/agent-core-evidence-validation.json
```

Observed result:

```text
exit code: 1
valid: false
errors: 116
warnings: 0
distinct error codes: 31
```

The 116 number is a count of machine-check failures, not 116 independent product
defects. Large repeated groups are the 13 absent screenshots, 30 missing session
metadata fields, 11 missing screenshot references, and repeated prohibited
workspace receipts. Material error classes include:

- `PROHIBITED_WORKSPACE` / `PROHIBITED_WORKSPACE_RECEIPTS`;
- `SCREENSHOT_MISSING` and `ENGINE_LOG_MISSING`;
- `SESSION_SCENARIO_MISSING` for G/I;
- `REPORT_EXECUTION_COUNT_MISMATCH` for B/E;
- `SCENARIO_C_WRITE_MISSING` and
  `SCENARIO_C_NARRATIVE_CONTRADICTION`;
- `SCENARIO_F_RUN_MISSING`, `SCENARIO_F_CLEANUP_MISSING`,
  `SCENARIO_F_EXECUTION_CANCELLED`, and `SCENARIO_F_NOT_FINALIZED`;
- `SCENARIO_G_READ_MISSING` and `SYNTHETIC_DESKTOP_SUBSTITUTE`;
- `SCENARIO_I_WRITE_MISSING` / `SCENARIO_I_CLEANUP_MISSING`;
- `H_AUDIT_FINALIZATION_CONTRADICTION`, `H_CACHE_CONTRADICTION`, and
  `H_REPORT_COUNT_CONTRADICTION`.

The validator also has a complete positive protocol fixture. It returns success
for a package with fresh/resumed session mappings, valid and uniquely hashed
screenshots, complete traces/reports, matching report hashes and counts, paired
SQLite intent/results, restart receipts, engine identity, and typed omission.
It is therefore not hardcoded only to reject this submission.

An exit-zero validation means the evidence is complete and internally
consistent. It does not turn a truthful `FAIL` or `UNAVAILABLE` scenario into
product acceptance, and it cannot replace human inspection of screenshot
content.

## 4. Raw-artifact adjudication by scenario

| ID | Raw receipt that exists | Contradiction or missing requirement | Adjudication |
|---|---|---|---|
| A | Trace and SQLite seq `14384–14385` show one `python --version` terminal execution with exit `0`; report count is `1`. | Forbidden workspace; no screenshot; no complete engine/build identity. | Command mechanic supported; desktop PASS unavailable. |
| B | Trace tool row and SQLite seq `14386–14387` show one real `check_target_toolchains(android)` execution and no mutation. | Report renders **0** current-turn executions although raw trace has **1**; forbidden workspace; no screenshot. | Mechanic supported; report defect confirmed; desktop PASS unavailable. |
| C | Greeting finalizes, then trace/SQLite seq `14388–14391` show `read_file` of `scratch/interest_probe.py` and terminal execution printing `interest-ok`. | No `write_file` proposal or execution exists. The target already existed in the reused workspace, while `RESULTS.md` says it was written. | **FAIL.** Creation and omission claims are contradicted by raw receipts. |
| D | Trace and SQLite seq `14392–14393` show one exact terminal attempt, `failure-probe`, and exit `3`, without retry. | Forbidden workspace; no screenshot or build/engine attribution. | Exit-code mechanic supported; desktop PASS unavailable. |
| E | Trace and SQLite seq `14394–14395` show a real `verify_target_app` invocation and an unavailable/error receipt. | Report renders **0** current-turn executions although raw trace has **1**; no screenshot; verification-events extract is empty. | Verification invocation supported; report defect confirmed; desktop PASS unavailable. |
| F | SQLite seq `14400–14402` proves a typed-omission `write_file` receipt. | Seq `14403–14404` ends with `Operation cancelled by the user — tool not executed`; no successful run, cleanup, or absence receipt; report says `in_progress`; trace has no finalize row. | **FAIL.** Later manual file absence cannot be represented as agent cleanup. |
| G | `logs/G-hydration-test.log` contains a terminal test. | No C-session desktop restart/resume, no G manifest entry, no before/after process and prefix-hash receipts, no UI screenshot, and no resumed trace/report. | Required behavior unexercised; submitted PASS claim **rejected** (truthful scenario result: `UNAVAILABLE`). |
| H | `reports/H-report-audit.md` covers only A–F. | It omits G/I and required hashes/coverage fields, lists F as `in_progress` while claiming all reports finalized, and labels cache N/A although B–F reports contain numeric telemetry. It also silently disagrees with B/E report counts. | **FAIL.** Audit narrative is not trustworthy. |
| I | `logs/I-marker-hash.txt` has an internally correct nonce derivation, byte length, and one-way marker hash. | No desktop session, write/cleanup execution, trace/report, SQLite rows, or screenshot. A unit test cannot substitute for the required desktop omission run. | Required behavior unexercised; submitted PASS claim **rejected** (truthful scenario result: `UNAVAILABLE`). |

### Verification database

`sqlite/verification_events_extract.json` contains:

- an empty `verification_events` list; and
- only F's `unverified` state in the prohibited workspace, with no event ID.

This cannot support broad verification PASS claims.

## 5. Confirmed Agent Core defect: B/E execution undercount

The B/E mismatch is independently reproducible and is not merely a capture
problem.

### Root cause

Agent Core intentionally excludes some tool outcomes from its
success/failure **progress** ledger:

- `check_target_toolchains` is informational;
- unavailable/preview `verify_target_app` receipts do not arm recovery;
- still-running terminal polls similarly have no terminal verdict yet.

`progress_node` therefore omits those outcomes from `execution_trace`. That is
correct for progress/recovery semantics. Finalization incorrectly reused
`len(execution_trace)` as the report's **current-turn executed tool records**.
Consequently, B and E each executed one tool but finalized with a rendered count
of zero.

Isolated reproduction before the fix:

```text
actual_tool_results: 1
execution_trace_count_used_by_finalize: 0
reported_count_if_finalized: 0
```

### Implemented correction

Agent Core now keeps a separate turn-scoped receipt ledger:

- `turn_tool_execution_count`;
- `turn_tool_execution_names`.

Every actual `ToolMessage` receipt enters this ledger before outcome
classification. Informational, unavailable, refused, and still-running outcomes
remain excluded from success/failure progress and recovery exactly as before.
The ledger:

- resets on every new user turn, including acknowledgement quick paths;
- persists in graph/checkpoint state;
- accumulates multi-tool batches;
- feeds the final diagnostic report and turn observability receipt;
- falls back to the legacy `execution_trace` count for old checkpoints.

This fixes report truthfulness without changing model intent, tool selection,
mutation policy, failure recovery, or verdict policy.

## 6. Protocol and validator hardening

`diagnostics/DESKTOP_AGENT_RERUN_B22D6EFC.md` now:

- names the machine-readable session manifest fields;
- requires a C-prefix SHA-256 before and after G's actual restart so byte-prefix
  preservation can be checked;
- requires the automated validator and retained `validation.json` before
  staging;
- states explicitly that validation success is not product acceptance.

The validator checks, among other invariants:

- exact implementation/stamp/source-hash provenance and successful build exits;
- disposable-workspace policy and forbidden workspace markers;
- complete A–I matrix and A–G/I desktop session mapping;
- fresh-session uniqueness and G=C resumed identity;
- required screenshots, PNG structure/minimum dimensions, unique content, and
  manifest SHA-256 values;
- complete UTF-8/JSON/JSONL parsing and monotonic trace indices;
- finalization and final-verdict receipts for PASS claims;
- raw current-turn execution counts against rendered reports;
- A–I scenario-specific execution, cleanup, restart, and omission receipts;
- paired SQLite intent/result ordering and manifest-session coverage;
- H report hashes, required columns, cache/count consistency, and coverage;
- deterministic I marker hash/length and whole-tree raw-marker absence;
- complete engine identity and two launch intervals;
- terminal/unit evidence represented as a desktop PASS.

## 7. Verification performed

### Baseline before changes

```text
50 passed
```

Selection: progress helpers, StepTracker, and finalize-chat tests.

### Red/green defect reproduction

The three new regression checks failed before the fix exactly as expected:

- informational execution count key absent;
- running-poll execution count key absent;
- final report received `0` instead of `1`.

They pass after the separate receipt ledger was added.

### Focused Agent Core and evidence validation

```text
197 passed in 6.72s
```

This includes progress/finalization, user-interest turn resets, StepTracker,
verdict honesty, classifier quick paths, Agent Core/quality evals, and both
positive and negative validator fixtures.

### Full repository suite

```text
2762 passed, 24 skipped, 1 xfailed, 8 failed
```

The eight failures are in untouched, out-of-scope baseline areas:

- renderer approval-diff/activity source parity (2);
- bridge model-wall source parity (2);
- terminal cancel/timeout runtime parity (2);
- environment-dependent LSP diagnostics (1);
- absent `src.tools.scaffold_tools` module (1).

None of those failing files or implementation areas is modified by this slice.
They are disclosed here rather than being mislabeled green.

The validator itself returns the required nonzero result for the rejected
package and zero for its internally consistent positive fixture.

## 8. Reconciliation stash disposition

The pre-audit reconciliation stash
`1276b2086dc028d39cbbe515c26a41c07fc5651e` was inspected across every parent:

| Saved tree | Paths | Already represented at `1e05cc02` | Unique |
|---|---:|---:|---:|
| tracked worktree | 23 | 23 | 0 |
| index | 0 | 0 | 0 |
| untracked third parent | 28 | 28 | 0 |

Every saved mode/blob at the same path matched the landed tree. The stash was
then dropped; no unique work was discarded.

## 9. Required next desktop action

A new desktop run is still required. It must use the corrected protocol and
validator with:

- a freshly rebuilt `b22d6efc` desktop and visible/engine identity receipts;
- a new isolated workspace outside all source checkouts and `testCRUSOR`;
- fresh A–F/I desktop sessions and an actual C→G process restart/resume;
- all required screenshots, full reports/traces, SQLite query receipts, and
  complete two-interval engine log;
- truthful `FAIL`/`UNAVAILABLE` results wherever a requirement cannot be
  exercised.

Until that package exists and passes human plus machine adjudication, Agent Core
desktop acceptance remains **not established**.
