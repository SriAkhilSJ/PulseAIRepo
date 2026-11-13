# Task Breakdown — PRD-001 (T-01…T-21)

Every ticket traces to FR/AC in `08-PRD-001-TOOL-BACKED-ENGINEERING-LOOP.md` rev 1.2.
Effort is focused hours for one agent session; estimates are ranges, not commitments.
DoD is defined once in `09-ENGINEERING-EXECUTION-PLAN.md` §7 and applies to all tickets.

---

## W1 — Execution integrity (WS-A · owner of `src/orchestration/**`, `src/graphs/**`)

### T-01 · Spike: choose the tool-loop entry point
- **Objective:** produce the ADR input for TL-DR-1 — exactly where an engineering task enters the tool loop.
- **Components:** `src/graphs/chat_graph.py` (read), `src/orchestration/orchestrator.py` (read), `src/bridge/__main__.py:1713`.
- **Changes:** none to product code. Write findings to `pm/em/adr-input/T-01-spike.md`.
- **Dependencies:** none.
- **Acceptance:** two candidate entry points documented with call paths, risks, and the failure mode of each.
- **Testing:** existing `test_canonical_runtime_engineering_delegation.py` still passes unchanged.
- **Security:** confirm no candidate route bypasses `SafeToolNode` or approval.
- **Effort:** 1–2h. **DoD:** spike note + TL decision requested.

### T-02 · Route engineering execution through the tool loop
- **Objective:** an engineering-classified task executes with read/search/edit/terminal tools bound.
- **Components:** `chat_graph.py` (`engineering_task_node`, routing), `orchestrator.py` (lifecycle hand-off).
- **Changes:** implement the entry point chosen in T-01; keep DAG as lifecycle authority (FR-2); record path (FR-4).
- **Dependencies:** T-01, TL-DR-1 signed off.
- **Acceptance:** AC-1 partial — task reads before editing; receipt field `execution_path = tool_loop`.
- **Testing:** new `test_prd001_engineering_routes_to_tool_loop`; assert path + no generation-only fallback.
- **Security:** no direct model→file write; all writes via mutation broker.
- **Effort:** 4h. **Risk:** hidden coupling in the 8k-line graph — timebox, escalate at 4h.

### T-03 · Plan-before-mutation gate
- **Objective:** no write occurs before a plan is presented and approved (when the profile requires it).
- **Components:** `planner_node:6382`, `plan_preview_node:6547`, `engineering_task_node`.
- **Changes:** gate the first mutation on plan approval; persist plan id into task state and receipt.
- **Dependencies:** T-02.
- **Acceptance:** AC-3 — no file mtime changes before approval.
- **Testing:** test asserts zero writes when approval is withheld; plan card emitted.
- **Security:** unplanned writes require explicit approval (FR-14).
- **Effort:** 3h.

### T-04 · Test-in-the-loop
- **Objective:** run the declared test command after edits; feed failures into the next turn.
- **Components:** `terminal_tools.run_terminal:362`, `engineering_task_node`, context assembly.
- **Changes:** read `crusor.test_command`; execute; attach exit code + failing assertion; cap reruns.
- **Dependencies:** T-03, T-19 (fixtures declare the command).
- **Acceptance:** AC-2 — failing output changes the next edit.
- **Testing:** fixture with a deterministic failing assertion; assert the follow-up turn references it.
- **Security:** command is workspace-scoped, timeout-bounded, classified before execution.
- **Effort:** 3h.

### T-05 · Evidence-based outcome semantics
- **Objective:** `success` only with exit code 0; `blocked` with a reason otherwise; `unverified` never printed as `verified`.
- **Components:** `finish_gate`, receipt writer, `orchestrator` delivery contract.
- **Changes:** outcome derivation function; forbid model self-report as evidence.
- **Dependencies:** T-04, T-07, **TL-DR-5 signed off**.
- **Acceptance:** AC-9; T5 returns `blocked`.
- **Testing:** impossible-invariant fixture; assert `blocked` + no `verified` string.
- **Security:** a false success is a security failure (FR-34/38).
- **Effort:** 2h.

---

## W2 — Receipts and ledger (WS-B · owner of `src/observability*`, `src/finops/**`)

### T-06 · Resolve the observability shadowing
- **Objective:** `from src.observability import record_turn_receipt` works.
- **Components:** `src/observability.py` (module), `src/observability/` (package).
- **Changes:** one rename/merge; update the 3 import sites; no behaviour change beyond availability.
- **Dependencies:** **TL-DR-2 recorded (recommendation B1)** — blocked until then. No other dependency; becomes a safe parallel start the moment the decision is signed.
- **Acceptance:** FR-29; collection error for `test_observability.py` disappears.
- **Testing:** import test + existing observability tests pass.
- **Security:** do not weaken the receipt path to make imports resolve.
- **Effort:** 1h. **DoD:** T-06 is the cheapest high-value ticket — schedule first.

### T-07 · Emit a receipt per turn
- **Objective:** one JSONL row per turn with the schema in `06-FINOPS-METRICS-SPEC.md` §3.
- **Components:** `record_turn_receipt`, `finops/accounting.py:114`, turn lifecycle.
- **Changes:** populate task id, path, provider, model, profile, tokens, cost, duration, tools, approvals, tests, outcome, evidence.
- **Dependencies:** T-06; T-02 for `execution_path`.
- **Acceptance:** AC-5 — all fields present on every run.
- **Testing:** schema validation test; run with a mocked provider.
- **Security:** no prompt bodies; content hashes only (SEC-10).
- **Effort:** 3h.

### T-08 · Task ledger + rollups
- **Objective:** aggregate receipts into cost per successful task and provider comparisons.
- **Components:** receipt files, new additive SQLite ledger, `/ops` view on the existing Flask dashboard.
- **Changes:** additive only; no `sessions.db` migration.
- **Dependencies:** T-07.
- **Acceptance:** AC-10 — failures included in the numerator.
- **Testing:** three synthetic tasks (2 success, 1 fail) produce the expected cost/success.
- **Security:** workspace id hashed; no raw paths.
- **Effort:** 2h.

### T-09 · Cost reconciliation
- **Objective:** prove the ledger matches reality within ±10%.
- **Components:** `finops/accounting.py`, `telemetry/pricing.py`, provider dashboard.
- **Changes:** reconciliation note + alert when outside tolerance.
- **Dependencies:** T-08, live run.
- **Acceptance:** AC-5 second clause; reconciling figure recorded in the evidence pack.
- **Testing:** manual comparison, recorded.
- **Security:** never print key material while collecting usage.
- **Effort:** 1h.

---

## W3 — Safe by default (WS-C · owner of `terminal_tools.py`, `src/security/**`)

### T-10 · Containment default-on, fail-closed
- **Objective:** shell commands run inside AppContainer/Job Object by default; containment is fail-closed.
- **Components:** `terminal_tools.py:1093,1152-1170`, `security/sandbox/windows.py`.
- **Changes:** default on; **remove the uncontained fallback and the opt-out entirely**; when containment cannot start, block terminal execution with a stated reason while read/search/edit remain available.
- **Dependencies:** T-11 (env scrub lands first to avoid leaking during the switch).
- **Acceptance:** AC-11, including the unsupported-build case.
- **Testing:** `test_prd001_sandbox_default_on`; `test_prd001_sandbox_unavailable_blocks_terminal`; assert no code path constructs an uncontained `Popen`.
- **Security:** **this ticket must not be traded for the deadline.** A failure here blocks the milestone.
- **Effort:** 3h. **Risk:** AppContainer may slow `pytest`; measure, do not disable.

### T-11 · Environment scrubbing
- **Objective:** child processes receive an allowlist, never the parent env.
- **Components:** `terminal_tools.py` env construction.
- **Changes:** allowlist (`PATH`, `HOME`, `TEMP`, language vars); drop everything else.
- **Dependencies:** none.
- **Acceptance:** AC-12.
- **Testing:** spawn a command printing env; assert no key-like variable present.
- **Security:** SEC-2. Highest-value 30 minutes in the milestone.
- **Effort:** 0.5h.

### T-12 · Fail-closed proof
- **Objective:** demonstrate that containment failure blocks rather than degrades, and that no configuration restores an uncontained shell.
- **Components:** sandbox manager, terminal tool.
- **Changes:** exception path returns a blocked result with reason; non-terminal tools stay available; no opt-out flag is honoured.
- **Dependencies:** T-10.
- **Acceptance:** forced-failure test asserts terminal blocked, reason surfaced, no uncontained execution, read/search/edit still functional.
- **Testing:** monkeypatch the sandbox to raise; assert `blocked`; assert an attempted opt-out env var is ignored.
- **Security:** SEC-1, SEC-11; the founder-rejected opt-out must not be reintroduced.
- **Effort:** 1h.

### T-13 · Egress denial by default
- **Objective:** agent-run commands cannot reach the network without a per-task grant.
- **Components:** `terminal_tools.py`, permission schema.
- **Changes:** deny rule; grant recorded in receipt.
- **Dependencies:** T-10, T-14 (schema).
- **Acceptance:** network command blocked; attempt recorded.
- **Testing:** blocked `curl` test (no live network).
- **Security:** SEC-3.
- **Effort:** 1.5h.

---

## W4 — Autonomy surface (WS-D · owner of `permission_config.py`, `contrib/crusorai/**`)

### T-14 · Two-profile schema
- **Objective:** Beginner and Developer profiles as permission rules in the existing schema.
- **Components:** `permission_config.py` (allow/ask/deny, last rule wins), settings files.
- **Changes:** ship two named profiles; default Beginner; schema left extensible for Enterprise.
- **Dependencies:** none.
- **Acceptance:** FR-23/25; no implicit auto-approval.
- **Testing:** profile load + evaluation matrix test (allow/ask/deny per action).
- **Security:** SEC-8 — the agent cannot edit these files.
- **Effort:** 2h.

### T-15 · Profile indicator
- **Objective:** the active profile is always visible.
- **Components:** `crusorAIRenderer.ts` (4,976 lines), contribution header.
- **Changes:** small header element; reuse existing design tokens.
- **Dependencies:** T-14.
- **Acceptance:** AC-8 first half.
- **Testing:** CDP/DOM assertion + screenshot in evidence.
- **Security:** display only; no control that widens permissions without confirmation.
- **Effort:** 2h.

### T-16 · Approval prompt enrichment
- **Objective:** every prompt shows risk class, containment state, and the rule that produced it.
- **Components:** renderer prompt path (`~:3243-3278`), protocol fields (additive).
- **Changes:** three extra fields, additive and optional.
- **Dependencies:** T-14, T-10.
- **Acceptance:** AC-6.
- **Testing:** DOM assertion for all three fields.
- **Security:** SEC-5 — token binding unchanged.
- **Effort:** 2.5h.

---

## W5 — Truth gate (WS-E · owner of CI files)

### T-17 · Zero collection errors
- **Objective:** `pytest --collect-only` exits 0.
- **Components:** the 3 failing modules (`test_observability.py`, `test_financial_accounting_closure.py`, `test_provider_usage_normalization.py`).
- **Changes:** fix root causes (T-06 covers one), no `skip`/`xfail` masking.
- **Dependencies:** T-06 for the observability case.
- **Acceptance:** FR-39.
- **Testing:** the command itself, output archived.
- **Security:** none.
- **Effort:** 1.5h.

### T-18 · CI gate with red/green proof
- **Objective:** a red suite blocks the PR.
- **Components:** `.github/workflows/`, `ci/agent-core.yml`.
- **Changes:** move full suite into workflows; remove `|| true`, `set +e`, `exit 0` from the gated job; tier fast/nightly if runtime demands.
- **Dependencies:** T-17.
- **Acceptance:** AC-13, including a deliberately broken commit shown failing.
- **Testing:** red/green run pair, both linked.
- **Security:** none directly; it is the gate that protects every other guarantee.
- **Effort:** 2h.

---

## W6 — Fixtures and evidence (WS-F · owner of `pm/fixtures/**`, `pm/evidence/**`)

### T-19 · Fixtures T1–T5
- **Objective:** five committed, reproducible fixtures with declared `crusor.test_command`.
- **Components:** `pm/fixtures/{t1_greenfield,t2_bugfix,t2b_wrong_assertion,t3_refactor,t4_injection,t5_impossible}`.
- **Changes:** fixture repos, README per fixture, expected outcome.
- **Dependencies:** none.
- **Acceptance:** each fixture runs its test command locally with a known baseline (green or red as designed).
- **Testing:** baseline run recorded per fixture.
- **Security:** T4 fixture contains an injection payload that must never execute; documented as inert.
- **Effort:** 3h. **Note:** fixtures are product-neutral test data, not app code.

### T-20 · Execute AC-1…AC-14
- **Objective:** the acceptance matrix, executed and recorded.
- **Components:** fixtures, running app, evidence manifest.
- **Changes:** none to product code.
- **Dependencies:** T-02…T-07, T-10.
- **Acceptance:** raw counts per slice; no percentage claims.
- **Testing:** this ticket *is* the test.
- **Security:** redact keys and paths before saving logs.
- **Effort:** 2h.

### T-21 · Evidence pack
- **Objective:** a reviewer can reproduce every claim.
- **Components:** `pm/evidence/two-day/` — manifest, transcripts, receipts, diffs, screenshots, provider reconciliation.
- **Changes:** docs only.
- **Dependencies:** T-20.
- **Acceptance:** manifest lists commit, provider, model, rate-card version, and each AC verdict.
- **Testing:** second reviewer (founder) follows it without asking questions.
- **Security:** secrets scan before commit.
- **Effort:** 1.5h.

---

## W7 — Failure triage (T-22 · added 2026-11-12)

### T-22 · Triage seven pre-existing suite failures
- **Objective:** classify and fix the failures that blocked T-18's green gate, without folding product changes into a CI ticket.
- **Components:** `src/graphs/chat_graph.py` (`_turn_scoped_resets`, `task_manager_node`, `SafeToolNode`), `src/tests/test_user_interest.py`, `src/tests/test_unknown_tool_validation.py`.
- **Evidence of origin:** the same 7 tests fail in a clean worktree at `7e4bb7ad` (before R2), so **R2 did not cause them**.
- **Findings:**

| Failure | Root cause | Classification |
| --- | --- | --- |
| 6 × `test_user_interest` | `_turn_scoped_resets()` returned `task_action=""`, `task_status`, `task_completed`, and every branch expanded it **after** setting the real values — the reset overwrote them. `after_task_manager` therefore saw `""` and could not route `plan_cancelled`, `approval_without_plan`, `execute_approved_plan`, `revise_plan`. | **Product regression** (routing) — fixed |
| 1 × `test_unknown_tool_validation` (repair) | `SafeToolNode` classified names for the mutation boundary **before** `_repair_tool_call_names`, so a dialect alias was judged under a name it never had and history kept the alias. | **Product bug** — fixed |
| 1 × `test_unknown_tool_validation` (alias safety) | The alias `run terminal` bypassed `_GRAPH_MUTATION_BLOCKED` (raw name not in the set), was repaired, and reached a **confirmation prompt** instead of being denied. | **Security-relevant regression** — fixed; test strengthened to require outright denial |

- **Fixes:** removed the three keys from `_turn_scoped_resets` (each branch sets them; three branches gained explicit values); moved name canonicalization above the side-effect boundary; the denial path now keeps the repaired assistant message in history. Both alias and canonical names are in the blocked set, so the reorder is fail-closed.
- **Testing:** 73 passed, 7 skipped across the affected modules, including a new regression guard `test_turn_scoped_resets_do_not_clobber_task_action`.
- **Dependencies:** blocks T-18 green gate; informs T-02 (routing depends on `task_action`).
- **Effort:** ~4h actual.
- **DoD:** all 7 pass; related modules green; no security weakening; evidence recorded.

## W8 — Suite baseline classification (T-23 · added 2026-11-12)

### T-23 · Classify the full-suite baseline and qualify Linux CI
- **Objective:** one authoritative failure inventory; separate product defects from environment/test defects; define the minimum work for a defensible T-18 green gate.
- **Method:** four read-only workers (inventory, CI validity, runtime, product regressions). 41 modules re-run individually at HEAD and at clean baseline `7e4bb7ad`; full-suite log parsed to 97%.
- **Measured totals:** **105 failures / 41 modules at HEAD** vs **100 / 40 at `7e4bb7ad`**. R2 accounts for **1** (`test_agent_cards`). The rest pre-date it.
- **Classification (module-level, evidence-backed):**

| Class | Modules | Failures (approx) | Notes |
| --- | --- | --- | --- |
| PRODUCT_BUG | 18 | ~55 | shell boundary (P1), write refusal (P5), prompt shape (P4), pricing/doctor/classifier/cards, `_tools_by_name` (fixed in `20a5cbe0`) |
| ENVIRONMENT_DEPENDENT | 8 | ~30 | uv-trampoline under restricted token (P2), no adb device, POSIX-only APIs |
| TEST_DEFECT | 6 | ~8 | stale patch targets, BOM'd file, deleted module, exact-float equality, changed copy |
| DEPENDENCY_OR_CONFIGURATION | 2 | ~2 | provider unset → `runtime_degraded` |
| UNRESOLVED | 2 | ~4 | bridge timeout under concurrent load; one runtime-evidence assertion |

- **Root-cause patterns:** P1 SafeToolNode terminal boundary (~15); P2 AppContainer × uv trampoline (~17); P3 SSRF loopback block (~8); P4 system-prompt shape drift (~11); P5 write_file over-refusal (~6); P6 POSIX-only assertions (3); P7 stale tests vs deleted/renamed code (~7); P8 no device / no provider (~20); P9 isolated product regressions (~18).
- **Ambiguous — needs founder decision:** P1. `run_terminal` is blocked by `_GRAPH_MUTATION_BLOCKED` **by design** (AGENTS.md F-03); the tests encode the T-10/T-12 target. Recommendation: `xfail(strict=True)` referencing T-10 — not deletion, and not re-enabling shell before T-11 (env scrub) + T-10 (containment).
- **CI findings:** workflow valid and tracked; no `permissions:` block; py3.11 vs `.python-version` 3.14 drift; no `pytest-timeout`; desktop parity modules **skip** on Linux because `desktop/vscode/node_modules` is absent, so they cannot gate PRs as the T-18 comment claims; 30-minute timeout marginal-to-insufficient.
- **Runtime:** only **one** session-scoped fixture in 339 modules; guarded-import probe spawns cold interpreters; `bench-results` (936 MB) is walked; fixed ports 45780/45781 and 8931; guard scratch dirs are created inside the repo root — all block safe sharding.
- **Dependencies:** T-18 green gate; T-02 (shell + write paths).
- **Effort:** inventory ~3h (done). Fix waves estimated 3–5 days.

## Summary

| WS | Tickets | Effort |
| --- | --- | --- |
| A Execution | T-01…T-05 | 13–14h |
| B Receipts | T-06…T-09 | 7h |
| C Safety | T-10…T-13 | 6h |
| D Autonomy UI | T-14…T-16 | 6.5h |
| E Truth gate | T-17…T-18 | 3.5h |
| F Fixtures/QA | T-19…T-21 | 6.5h |
| **Total** | **23 tickets** (T-22, T-23 added) | **≈49.5–50.5h** |

46.5–47.5 hours is more than 16 hours of working time. **That is the honest number, and it is why Day 1 has a
Go/No-Go.** The two-day plan assumes parallel agent sessions (A–F run concurrently); a single sequential
session cannot deliver all 21 tickets in 16 hours. The reduced scope if only one session is available is in
`09-ENGINEERING-EXECUTION-PLAN.md` §6 NO-GO cut table.
