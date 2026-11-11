# P0.6.6 — Execution Reliability Closure

## Verdict

**`P0.6.6_LIVE_FAILED`** — infrastructure objectives met, live completion not proven.

The three defects from P0.6.5 are **closed and proven offline plus on live evidence**:

1. **FinOps on the orchestrator path** — reservations, authentic usage, verified
   pricing, settlement and reconciliation now demonstrated on a real desktop
   turn (2/2 dispatches settled, 0 uncertain, ₹0.060 spent, SQLite + JSON agree).
2. **Planner dispatch budget** — plan generation is budget-aware, counts
   dispatch demand in **files** (not nodes), refuses over-budget plans before
   any provider call, and never drops a requirement id.
3. **Output ceiling** — measured at three ceilings, raised 2048 → 4096 → 8192
   with a scope guard and an exact-symbol contract; the P0.5.1 fail-closed gate
   is intact.

The **live turn still ends `failed`** because the model writes its test file in a
separate dispatch and three edge-case assertions disagree with the module it
wrote (`no-tld`, `single-char-tld`, overlong length). The artifact itself passes
the harness's independent contract check, but the engine's own delivery verdict
at the time — and 3 of its 53 generated tests — say otherwise, so this is not an
acceptance. The later verification-traceability fix could change the engine's
verdict on such a turn without making its tests pass; that gap is recorded in
§7.2 rather than papered over by re-running.

> Correction to P0.6.5: the financial ledger **did** settle there (5/5
> reconciled, 1 uncertain, ₹0.192). The P0.6.5 harness read `CRUSORAI_HOME/
> sessions.db`; the orchestrator writes `<workspace>/.crusorai/`. Fixed here.

## 1. Starting state

- Branch `feat/prompt-cache-stabilization`, start commit `3c804eb3`
  (local == origin, verified after fetch).

## 2. Task 1 — FinOps in `EngineeringExecutionOrchestrator.run_task`

The governor was already constructed and handed to `ModelExecutionAdapter`,
which owns the per-dispatch lifecycle (`reserve → mark_in_flight → commit`
`/ mark_uncertain / release`). What was missing at the orchestrator level:

| Change | File |
| --- | --- |
| `run_task` is now a thin wrapper over `_run_task_impl`; **on every exit** (success, failure, cancellation, exception) `_finalize_finops_after()` runs | `src/orchestration/orchestrator.py` |
| Finalizer **releases** lingering ACTIVE holds (the scheduler is synchronous, so nothing can still be in flight) and **never releases UNCERTAIN holds** — it reports them for reconciliation | same |
| `_last_finops` is initialised per instance so the wrapper always sees this turn's governor | same |
| A pre-dispatch refusal (`AcceptanceBudgetExceeded`, `TurnCancelledError`) is now classified **pre-dispatch** → the hold is released, not retained as uncertain | `src/orchestration/model_adapter.py` |

Financial invariants proven by tests (`test_p0_6_6_execution_reliability.py`):

- reserve → settle exactly once; `calls_count == 1`, spend equals actual cost;
- duplicate `commit_reservation` is a no-op (no double charge);
- a released hold cannot later be charged (terminal state);
- `mark_uncertain` retains the hold and appears in the final report;
- the finalizer releases active holds and leaves uncertain ones intact.

## 3. Task 2 — Planner dispatch budget

Dispatch demand is **one provider call per target file** (the verification node
dispatches nothing). The budget therefore counts files:

- `EngineeringTaskPlanner.build_plan(..., max_nodes=)` coalesces requirement
  nodes, unioning ids/files/tests (nothing dropped), then consolidates to one
  file per merged node when the file count still exceeds the implementation
  budget — absorbed paths are written into `expected_outputs`
  ("consolidated into …"), never hidden.
- `Orchestrator._validate_plan_budget()` raises `PlanBudgetExceeded` **before any
  dispatch** when `sum(files) > budget`, and records `PLAN_REJECTED`.
- `_remaining_dispatch_budget()` = min(task limit, live acceptance guard
  remaining), so a plan can never be generated that the guard would refuse.
- The bridge passes `CRUSORAI_ACCEPTANCE_MAX_DISPATCHES` into
  `ExecutionLimits(max_dispatch_budget=…)`.
- Files the **user named** are the work units: analyzer placeholder nodes are
  absorbed into them (ids preserved, no extra `src/req_00N_module.py`), and the
  node objective becomes the user's own request text.
- Verification traceability: `verify_task` now accepts the plan's explicit
  requirement → files map. Previously requirement verification passed only
  because invented `src/req_00N_module.py` paths contained `req_002`; a path
  containing `req_` satisfied every acceptance criterion by substring. That was
  fake evidence. User-named files carry no requirement id, so the orchestrator
  maps each `related_requirement_ids` entry to the node's target files, and the
  verifier scopes the requirement to files the plan actually mutated. Non-stub
  AST bodies are still required, and a scope naming an absent file verifies
  nothing (three tests pin both the fallback and the scope).

Adversarial tests: budget 1/0/−3 refused; 6 requirements in 5/2 dispatches keep
all six ids; a 3-file node vs budget 2 refused; plan at/under budget allowed;
guard-remaining intersection.

## 4. Task 3 — Output ceiling and truncation

Measured on the live provider with the same task shape:

| Ceiling | Result |
| --- | --- |
| 2048 (P0.6.5) | all 5 implementation nodes `finish_reason='length'` |
| 4096 (P0.6.6 `live2`) | all 4 nodes `finish_reason='length'` — still truncated |
| 8192 (`live3`) | user module + tests complete, but an analyzer-invented placeholder node (`src/req_004_module.py`, inflated RFC/DNS requirement) still hit the ceiling |
| 8192 + user-named file plan (`live4`–`live6`) | 2 dispatches; module + tests complete, no truncation |

`ExecutionLimits.max_output_tokens_per_node = 8192` (default), stamped onto each
node by the orchestrator, carried into `max_tokens` provider kwargs. Worst-case
bound at five dispatches: 5 × 8192 output tokens × the measured ~₹1.9e-5/token
≈ **₹0.78**, inside the ₹5 cap. Observed live spend: ₹0.060 for 2 dispatches
(₹18.7 per 1M output tokens, consistent across runs live2–live6).

Two fidelity guards added because size alone was not enough:

- scope: user-named nodes carry the user's prompt (minimal scope, no CLI/DNS);
- exact symbols: `def`/`function <name>` mentions in the objective become a
  "Required public symbol(s): … Use EXACTLY these names" line — the model had
  renamed `validate_email` to `is_valid_email`.

P0.5.1 fail-closed validation is untouched (`assert_provider_output_complete` →
`extract_generated_source` → `validate_generated_source` before mutation).

## 5. Task 4 — Offline qualification

| Suite | Result |
| --- | --- |
| `test_p0_6_6_execution_reliability.py` (new) | 27 passed |
| `test_p0_6_5_live_acceptance.py` | 27 passed |
| `test_p0_6_4_desktop_observability.py` | 31 passed |
| `test_p0_6_4_1_acceptance_retry_clamp.py` | 11 passed |
| `test_p0_5_1_output_integrity.py` | 11 passed |
| `test_p0_3_orchestrator_integration.py` | 7 passed |
| `test_planner_phatic_gate.py` | 18 passed |
| `test_phase_9_7_enterprise_finops.py` | 20 passed |
| `test_phase_12_1_1_identity_finops_production.py` | 5 passed |
| bridge suites (8 files) | 63 passed |

**220 passed, 0 failed, 0 skipped** (607 s).

The first draft of this report said "≈371"; that was an arithmetic error
(bridge's 63 was added twice). The measured collected total is 217 before the
three verification tests and 220 after. Correcting it here rather than shipping
a number nobody can reproduce.

Three bridge tests were failing on a **20 s frame budget** while `python -m
src.bridge` needs ~22 s to answer `hello` cold on this machine (measured). Their
timeouts were raised to 60/90 s (`_read_frames`, `_run_script`, and one
`subprocess.run`) — an environmental budget, not a logic change.

Also fixed while qualifying: the first full run after user-named planning failed
`test_p0_3_orchestrator_integration.py::test_desktop_bridge_reaches_model_backed_executor`.
That exposed the verification-traceability defect described in §3: the test had
been passing because invented filenames contained requirement ids. The engine
now consumes the plan's requirement → files map, and the three new verification
tests are part of the 27.

`src/workspace/baseline.py` also used the same Windows
`subprocess.run(timeout=)` pattern that can wedge forever on a grandchild-held
pipe; it now uses the shared `src/utils/git_safe.run_git` (no stdin, no prompts,
`core.fsmonitor=false`, tree kill on timeout). This was the live run-1 stall at
`_inspect_git_info`.

Code OSS Invariant 7: **maintained** (0 changed files in `desktop/vscode`, 0
drift, 0 undeclared). Secret scan of `diagnostics/p0_6_6` **and** the live6
electron logs: **0 hits** (`scripts/secret_scan_p0_6_6.py`: key prefixes,
secret assignment, bearer tokens, private-key blocks).

## 6. Task 5 — Live desktop acceptance (`diagnostics/p0_6_6/live6`)

Every paid attempt is listed, including the ones that failed. No run used more
than 4 of its 5 dispatches, every dispatch got exactly one attempt, and no
reservation was left active or uncertain.

| Attempt | Dispatches | Spend (₹) | Outcome |
| --- | --- | --- | --- |
| `live` | 0 | 0.000000 | stalled before dispatch (Windows git pipe wedge at baseline capture); fixed with `run_git` |
| `live2` | 4 | 0.266898 | all 4 nodes truncated at 4096 (`finish_reason='length'`) |
| `live3` | 4 | 0.297509 | module + tests complete at 8192; analyzer-invented `src/req_004_module.py` still truncated; turn failed |
| `live4` | 2 | 0.172198 | module over-built (963 lines, RFC/DNS/CLI) and ignored the user contract; harness smoke had a `sys.modules` bug |
| `live5` | 2 | 0.068435 | module renaming (`is_valid_email` vs `validate_email`) broke the next node's tests |
| `live6` | 2 | 0.060020 | accepted-chain evidence: module correct, 3 of 53 agent tests disagree; turn `failed` |
| **Total** | **14** | **0.865060** | no constraint breached |

Historical evidence in `live2` still carries the old `P0.6.5_*` verdict token
because it was produced before the rename; it is reported here as a failed
attempt, not as acceptance.

| Stage | Evidence |
| --- | --- |
| Run / session / turn / workspace | `p0_6_5_20261107T162828_df4aedc7` / `session-69eab052…` / `turn-33809952…` / `ws-23b018c6…` |
| Electron | real app, workbench, engine **"Crusor ready"**, dynamic loopback CDP |
| Worker→bridge | utility processes → venv shim → interpreter PID 25788; ledger pid matches |
| Guard | banner in the app's bridge; budget 5, attempts 1 |
| UI submission | real composer, `Input.insertText` + `rawKeyDown` Enter; manifest `request.sha256 == sha256(prompt)` |
| Dispatches | **2** (module + tests); **2 settled**, 0 uncertain, ₹0.06002 |
| Plan journal | `PLAN_GENERATED nodes_count=3, dispatch_budget=5, per_node_output_tokens=8192` (`live6/orchestration_journal.jsonl`) |
| Financial | all checks green (settlements, calls matched, no active/uncertain, within budget, SQLite reconciled, usage recorded) |
| Output | `src/email_validator.py` (AST ok, `validate_email`, correct bool/TypeError semantics) and `tests/test_email_validator.py` |
| Independent verification | harness smoke **PASS** (valid→True, invalid→False, non-string→TypeError); SHA-256 recorded |
| Agent's own tests | **50 passed, 3 failed** (`no-tld`, `single-char-tld`, overlong total length) |
| Turn status | **`failed`** (delivery verdict FAILED, `error: null`) |
| Renderer | 0 unhandled errors/rejections |
| Shutdown | app stopped after the turn; exit code reported in evidence |

Verdict formula requires: guard ok, finance ok, AST ok, agent tests rc 0,
independent smoke ok, terminal `completed`, 0 renderer errors, correlation.
Everything except **agent tests rc 0** and **terminal completed** holds.

## 7. Remaining defects (precise)

1. **Cross-node test consistency.** The test file is authored by a different
   dispatch than the module, with no repair pass available under a 2-dispatch
   plan. Three edge-case assertions disagree with the module's (correct) core
   behaviour. Fix options: plan a verification/repair node inside the budget,
   or have the tests node read the module the previous node wrote (the adapter
   already passes `existing_content` for existing files).
2. **Delivery verdict vs. generated tests.** The engine fails a turn when the
   regression gate fails, but it does not run the test files the agent itself
   wrote; the desktop harness does. After the plan-scoped verification fix, the
   engine would likely mark `live6` COMPLETED while 3 of its 53 generated tests
   fail. The acceptance gate rejects that (and did), so the remaining gap is
   "engine verdict is not the harness verdict", not "no verification exists".
   Closing it means executing agent-authored tests inside the turn, which is a
   real feature, not a verdict tweak.
3. Requirement analysis still inflates a one-sentence request into RFC/DNS/CLI
   requirements; the scope guard reduced the module from 963 → ~180 lines but
   the analyzer remains the source of pressure.
4. Verification now trusts the plan's requirement → file mapping. It proves the
   plan's files contain non-stub implementations, not that every analyzer-written
   acceptance criterion is semantically satisfied (the criterion matcher remains
   keyword-based). Explicitly scoped and documented is better than the previous
   filename-substring accident, but it is not a semantic proof.

## 8. Commits

- **`a5c8e27e`** — `feat(p0.6.6): orchestrator FinOps reconciliation, file-aware
  dispatch budget, measured 8192 output ceiling`
  (`src/orchestration/*`, `src/bridge/__main__.py`, `src/utils/git_safe.py`,
  `src/workspace/baseline.py`, `benchmarks/crusor_desktop_acceptance/*`,
  `src/tests/test_p0_6_6_execution_reliability.py`, plus the P0.6.5/bridge test
  updates).
- **`fa6deae8`** — `fix(p0.6.6): accept the current verdict token in the harness
  CLI; align ceiling test docs`. This commit also carries the sanitized
  `diagnostics/p0_6_6/` evidence and `scripts/secret_scan_p0_6_6.py` because
  those files were staged when the fix was committed (no history was rewritten).
- **`a66cd1da`** — `fix(p0.6.6): verify requirements against the plan's files,
  not filename substrings` (`src/verification/*`, the orchestrator's
  requirement → files map, the three verification tests, and the corrected
  5 × 8192 cost comment).
- A final docs commit on top of `a66cd1da` records this corrected commit map,
  the exact 220-test tally, the attempt/spend ledger and the measured cost
  bound.

Evidence committed is intentionally minimal, mirroring P0.6.5: `evidence.json`,
`run.json`, `acceptance_dispatch.json`, turn evidence + SHA-256, `ide.json`,
traces, plan journal and screenshots. Electron user-data, portable profile,
caches, session databases and WAL files are **not** committed.

## 9. Bottom line

Crusor now enforces its own execution limits and pays for exactly what it
dispatches on the real desktop path — the three P0.6.5 defects are fixed and
proven. It still cannot be called a completed engineering turn: its generated
tests disagree with its generated module on three edge cases, and it reports the
turn as failed rather than repairing. That is the next defect to close, not a
green report to write.
