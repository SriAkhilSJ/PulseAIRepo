# CrusorAI - Roadmap

**Snapshot:** 2026-11-12 (`feat/prompt-cache-stabilization`, HEAD `fb5bd528`)
**Updated:** 2026-11-12 — engineering audit + memory reconciliation appended
(§11); HEAD and branch unchanged.
**Rule:** items marked **Committed** exist in the repo or an explicit task;
items marked **Proposed** are candidates and are not authorized work.

---

## 1. Current position

- Phase 1.4 remains **WINDOWS SECURITY QUALIFIED** for the declared Windows 11 +
  Python 3.11/3.14 contract.
- The Agent Runtime migration (Increments 1–3, `docs/ARCHITECTURE.md` §14) is
  implemented and verified at HEAD + working tree for the desktop: LangGraph is
  the sole interactive owner, engineering is delegated, context/tools/approvals/
  mutations are unified, and a canonical receipt + FinOps ledger exist.
- Runtime evidence is provider-free: 155 core tests, 232/3 security tests, 38/1
  bridge sidecar, restart replay for approve/deny/cancel, stale-approval tests.
  The 2026-11-12 suite cannot collect in full and has 3 known failures (F-02).
- Live product qualification passed its first controlled task: the exact
  one-file prompt created only `hello.md`, was independently VERIFIED, and
  recorded one approval/mutation and one Velona invocation (₹0.014704).
  Two scope leaks were fixed. Total bounded live spend: ₹0.092942.
- Agentic execution visibility is wired: engineering stage progress streams into
  the existing activity/plan cards, DAG completion is recorded only from real
  executor settlement, and the plan card distinguishes completed / failed /
  blocked / cancelled. Provider-free Electron acceptance: 21/21 checks, zero
  provider invocations.
- **The 2026-11-12 audit is the condition baseline**:
  `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md`. Engineering still binds no tools
  during generation (F-01). The product default approval policy is
  `workspace_session`, not `ask` (F-04). Terminal/test execution is unsandboxed
  by default (F-03). The checkpoint DB is hardcoded/unbounded (F-05), turn
  receipts are dead (F-06), RBAC cannot deny (F-07), and cancellation under-counts
  spend (F-08).
- Remaining: security defaults, engineering tool binding/targeted edits, test
  baseline + CI gates, persistence/observability, FinOps/authorization truth,
  full TurnReceipt rendering, live acceptance, packaging, deployment and commit
  disposition.

## 2. Priorities

1. **Truthful state.** Keep HEAD, working tree, evidence, and docs aligned.
2. **Security boundaries.** Close remaining runtime gaps without weakening
   existing guards.
3. **Desktop integration.** Make the strongest engine capabilities visible and
   usable in the IDE.
4. **Reliability and cost.** Reduce false completion, long-turn cost, and
   unrecoverable failures.
5. **Reproducibility.** Keep the fork build and test baseline repeatable.

## 3. Now (authorized next steps)

### N-1 - Independent review of Phase 1.4 final closure

**Status:** Required gate
**Scope:** review `0bf14d9c`..`71479fb6`, especially the ACL architecture
removal, native network proof, Python 3.11 fix, TMP contract, and memory
limitation.
**Exit criteria:** review notes recorded; any follow-up filed; no unresolved
security objection. Then begin desktop production qualification.

### N-2 - Working-tree disposition

**Status:** Decision needed; **269 entries** (262 at the audit; docs and P1-A
added the rest), 83 modified, 186 untracked, 0 staged — HEAD `fb5bd528`
**Scope:** decide whether the uncommitted Agent Runtime increments, desktop
artifacts, tests, apps, generated `src/req_*_module.py` files and memory layer
belong to future commits or are retained as reviewed work. The broker wiring is
already at HEAD and is not part of this decision (B-001 closed).
**Constraint:** this task must not commit, reset, or delete them.
**Exit criteria:** each group is explicitly owned and scheduled, or left
untouched by instruction.

### N-3 - Phase 2 definition

**Status:** Partially implemented — 2A (discovery) and 2D (outside-workspace
grants) are verified; 2B (targeted edits) and 2C (diagnose/repair) are open.
**Scope:** the runtime migration is complete for the desktop; remaining work is
engineering capability, security defaults and release hardening.
**Exit criteria:** none for the original Phase 2 brief; use P-0b instead.

### N-4 - Electron Agent-pane acceptance

**Status:** Provider-free E2E passed 2026-11-10; full receipts/live providers open
**Scope:** fixed the missing chat routing singleton and regenerated the shipped
panel hash; drove chat, engineering approve, denial and cancellation through the
real Electron UI.
**Exit criteria:** met for the provider-free path. Remaining: render the full
`TurnReceipt`, exercise live providers, packaging and headed qualification.

## 4. Next (proposed, highest value; audit order)

### P-0 - Close the default security posture

**Why:** terminal execution inherits the full environment and is sandbox-optional
(F-03); the product bridge defaults to `workspace_session`, which auto-approves
LOW-risk writes (F-04). The Electron dock evidence was produced with `ask`.
**Work:** default to `ask`; route every process through `ExecutionBroker`; pass a
scrubbed env allowlist; require approval to execute model-generated tests; add
negative tests (wrong policy => approval request; key absent from child env).
**Exit criteria:** default launch emits an approval request for a LOW-risk write;
a child process cannot see provider credentials; a sandbox failure fails closed.

### P-0b - Make engineering a tool-using agent (Phase 2B)

**Why:** generation binds no tools, regenerates whole files, and can still
synthesise requirement-id filenames (F-01). All three 2026-11-12 live tasks
failed or blocked.
**Work:** bind bounded read/list/search during generation; add targeted hunk
edits; reject requirement-id targets unconditionally; prove with a graph-level
test on a disposable project and one authorized bounded run.
**Exit criteria:** an existing file is edited surgically; the plan never contains
`src/req_*_module.py`; a failing test drives a bounded repair.

### P-1 - Enforce identity/RBAC in the live tool path

**Why:** the authorizer is called with a hard-coded superadmin and cannot deny
(F-07, B-002).
**Work:** resolve the principal from session identity/tenancy; remove the
superadmin default; add adversarial tests and an ADR update.
**Exit criteria:** a guest cannot execute a privileged tool; a permitted role
can; tests prove both.

### P-2 - Verify the mutation broker at HEAD and retire B-001

**Why:** B-001 was marked fixed only in the working tree, but `HEAD` already
routes writes through the broker (F-12).
**Work:** record the `file_tools.py:508-538` evidence, remove the stale
"uncommitted" claim, and keep a regression that fails a write without a token.
**Exit criteria:** no documentation or test asserts a bypass at HEAD; the broker
regression passes.

### P-3 - Surface intelligence artifacts in protocol v2 and the desktop

**Why:** orchestrator outputs cannot be rendered (B-003).
**Work:** add typed frames for architecture/impact/regression/verification/
delivery artifacts; generate TypeScript; add renderers and contract tests.
**Exit criteria:** a real orchestrator run renders each artifact without
free-form JSON.

### P-3b - Surface the canonical TurnReceipt in the desktop

**Why:** the bridge emits `receipt` with terminal status, changed files, tests,
approvals, mutations, evidence and FinOps ids; full UI rendering is not proven
(B-021).
**Work:** render the receipt as the authoritative turn card and remove remaining
event-reconstruction paths.
**Exit criteria:** UI counts/verdict match the persisted receipt on success,
denial, cancellation, partial and failure.

### P-4 - Restore a trustworthy full-suite baseline

**Why:** `pytest --collect-only` reports 4,953 tests with 3 collection errors;
three modules are red; security CI is path-filtered (F-02).
**Work:** fix or delete the stale imports
(`deduplicate_streaming_usage`, `record_turn_receipt`), update the two
`test_bridge` pins and the card-type pin, run the full suite, classify every
failure, and gate it in CI.
**Exit criteria:** a cleanly collected suite with an explicitly justified
baseline and no unknown red; exit code recorded.

### P-5 - Re-run live product acceptance

**Why:** P0.6.9 failed and LIVE12 is unvalidated (B-005); the 2026-11-12 live run
proved provider dispatch but failed all engineering tasks.
**Work:** authorized, budgeted run after P-0/P-0b; capture artifacts, spend and
verdict. Do not reuse or mutate the historical reservation without owner
approval.
**Exit criteria:** a new run with a complete artifact set and an honest verdict.

### P-6 - Harden persistence and observability

**Why:** the checkpoint path/import/bridge/OTel/URI test isolation is fixed
(P1-A + R2 + R3), but the DB is still 936.7 MB with no retention (F-05); the
`src/observability` package shadows the module, so turn receipts never run
(F-06).
**Work:** add retention/vacuum and decide workspace placement; fix the package
collision, remove the swallowed import, add a receipt test. Keep the P1-A path
contract and lazy-open regression.
**Exit criteria:** disk growth is bounded; `record_turn_receipt` runs and is
tested; a custom home/checkpoint override is covered.

### P-7 - Make money truthful

**Why:** post-dispatch cancellation releases the hold and records zero usage;
pricing is marked verified without provenance; cost spans three stores (F-08).
**Work:** mark cancelled-after-dispatch `uncertain` with measured/estimated
usage; record pricing source/date/evidence; define one authoritative ledger with
reconciliation.
**Exit criteria:** a cancelled paid turn is visible in the ledger; pricing
provenance is auditable; reconciliation is tested.

## 5. Later (proposed, structural)

| Item | Why | First step |
|---|---|---|
| ~~Python 3.11 import purity~~ | Fixed by Phase 1.4 (B-007). | Keep the regression. |
| WindowStation/Desktop ACL recovery | Machine-level boundary remains unresolved (B-009). | Threat model and a reversible, audited repair design. |
| Unified financial store | Multiple money surfaces and heuristic reconciliation (B-010, F-08). | Define one transaction boundary or a formal reconciliation contract. |
| Prompt-cache-aware compaction | Compaction can invalidate the prefix (B-011). | Make compaction consult the cache plan; measure before/after. |
| Cost guard on by default | Spend can run until provider refusal (B-012). | Choose a safe default budget and surface it in the UI. |
| Desktop build reproducibility | Native modules and fork drift (B-014). | One documented clean build + launch recipe with hashes. |
| Requirement-id hygiene guard | Generated `src/req_*_module.py` contamination (F-11). | Add a repo check and quarantine the existing files with owner approval. |

## 6. Not planned / out of scope

- Rewriting the desktop off Code OSS.
- Replacing LangGraph or the stdio bridge without a migration ADR.
- A hosted multi-tenant service.
- Broad refactors that mix unrelated dirty entries with phase work.
- Any claim of live acceptance without a recorded run.

## 7. Sequencing rules

1. One phase, one scope, one starting HEAD.
2. No phase may absorb pre-existing dirty files.
3. Security changes need adversarial tests and CI evidence.
4. Documentation updates are part of the change, not an afterthought.
5. If a proposed item is not authorized, leave it here rather than starting it.

## 8. Definition of done for any roadmap item

- Committed change with SHA.
- Tests and exit codes recorded.
- CI run/job IDs where CI applies.
- `docs/CURRENT_STATE.md`, `docs/phases/PHASE_TRACKER.md`, and
  `docs/handoffs/LATEST_HANDOFF.md` updated.
- New limitations recorded honestly.

## 9. Completed 2026-11-11 (uncommitted, provider-free)

| Item | Outcome | Evidence |
|---|---|---|
| Live engineering progress → existing Agentic cards | PASS | `CRUSOR_PROGRESS_INTEGRATION_REPORT.md` |
| Engineering DAG completion from real settlement | PASS | `CRUSOR_PLAN_COMPLETION_REPORT.md` |
| Plan outcome semantics: completed / failed / blocked / cancelled | PASS | `CRUSOR_PLAN_OUTCOME_SEMANTICS_REPORT.md` |
| Multi-turn orchestration storage isolation | FIXED | `src/graphs/chat_graph.py` |
| Per-turn Agentic card ownership + reload/restart restoration | PASS | `CRUSOR_TURN_CARD_RESTORATION_REPORT.md` |
| Clean chronological timeline; internal verification/delivery/cost hidden | PASS | `CRUSOR_AGENTIC_TIMELINE_REPORT.md` |

Next candidates created by this work (not authorized as a separate phase):

1. **Real-provider verification of the progress/outcome/card/timeline path** —
   requires an explicit paid-call authorization; mock-mode evidence is complete.
2. **Populate node descriptions in plan steps** — the progress snapshot carries
   DAG node ids, not descriptions; a bounded view field would improve labels.
3. **Event-exact historical interleaving** — live cards pin at arrival, but
   restored turns use anchors because checkpoint messages carry no per-event
   sequence. A durable message/card sequence would close this.

---

## 10. Completed 2026-11-12 (uncommitted, real provider, terminal only)

| Item | Outcome | Evidence |
|---|---|---|
| Real-provider smoke test through the shared gateway | PASS (`CRUSOR_GATEWAY_OK`, 22 in / 58 out, 2.34 s, `inv-b0d44e039c9f44e5`) | `CRUSOR_AGENT_CORE_TERMINAL_QUALIFICATION.md` |
| Terminal three-task engineering run (A/B/C, `mini_math`) | Provider path PASS; **engineering FAIL** (`FAILED`, `FAILED`, `BLOCKED`) | same, plus `%TEMP%\CrusorLiveE2E\evidence\backend-qual.json` |
| Measured ledger `latency_ms` | FIXED (was null) | `src/orchestration/model_adapter.py`; 18 tests pass |
| Spend | ₹0.4207 of the ₹50 cap (5 terminal calls + 1 stopped UI attempt) | FinOps `provider_invocations.jsonl` |

Next, proposed (not authorized):

1. **Phase 2a — read-only tool binding.** Bind list/read/search to the
   engineering model and pass discovered files to the planner, so targets are
   real paths. Deterministic tests first. **DONE 2026-11-12** (uncommitted):
   `src/workspace/discovery.py`, `src/workspace/evidence.py`, contract/planner
   wiring; 9 deterministic tests including a graph-level ordering proof. See
   `CRUSOR_PHASE_2A_WORKSPACE_DISCOVERY.md`.
2. **Phase 2b — targeted edits.** Patch existing discovered files through the
   broker instead of regenerating whole files. Not started.
3. **Phase 2d — outside-workspace access with permission.** **Implemented
   2026-11-12** (uncommitted): `workspace.access` approval, turn-scoped grants,
   exact boundaries, sensitive veto, context-only external evidence; **writes
   (2d-2)** create/modify through the broker with the normal diff token.
   17 deterministic tests. `CRUSOR_PHASE_2D_OUTSIDE_WORKSPACE_ACCESS.md`.
   Delete/rename/copy outside remain unsupported.
4. **Phase 2c — repair loop.** Execute tests, feed failures back, allow bounded
   repair through the broker, re-verify — driven by discovery evidence. The
   existing repair loop is unchanged and is not gated by `mock_mode`
   (B-CORE-006). Not started.
5. **Format recovery.** One metered re-prompt on `SourceExtractionError`
   (B-CORE-002). Not started.
6. **Identifier reconciliation.** `chat_graph.py:5389` sets
   `task_id = f"turn_{turn_id}"`, so task ids render `turn_turn-*`. Needs a
   reconciliation test before renaming (task-scoped storage paths depend on it).

## 11. Completed 2026-11-12 (documentation + P1-A/R2/R3)

| Item | Outcome | Evidence |
|---|---|---|
| Initial source-based engineering audit | COMPLETE | `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` (F-01…F-15) |
| Memory reconciliation to HEAD `fb5bd528` | COMPLETE | `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`, `docs/BUGS_AND_LIMITATIONS.md`, `docs/DECISIONS.md`, `docs/ROADMAP.md`, `docs/phases/PHASE_TRACKER.md`, `docs/handoffs/LATEST_HANDOFF.md` |
| Broker status corrected | FIXED at HEAD (not uncommitted) | `src/tools/file_tools.py:508-538`; `git diff HEAD` empty |
| Old blockers corrected | B-DESK-001 / B-001 / B-015 closed-at-HEAD notes | `docs/BUGS_AND_LIMITATIONS.md` |
| Working-tree count corrected | 262 at audit; 264 after two docs (80 modified, 184 untracked) | `git status --porcelain` |
| P1-A checkpoint/session test isolation | DONE-VERIFIED | `src/runtime/app_paths.py`, `src/graphs/chat_graph.py`, `src/tests/conftest.py`, `src/tests/test_checkpoint_isolation.py` (15 passed); real DB unchanged |
| P1-A-R2 independent-review remediation | DONE-VERIFIED | B-1/B-2 fixed; 22 isolation + 4 bridge tests; real DB + all sidecars unchanged; invalid paths fail closed |
| P1-A-R3 SQLite URI path correction | DONE-VERIFIED; awaiting acceptance | B-4 fixed with `sqlite_readonly_uri`; `#`/space/`%`/Unicode bridge tests; real DB + sidecars unchanged |
| P1-B collection/test baseline | NOT STARTED (review gate) | P1 investigation report |

P1-A changed source/test files (`app_paths`, `session_store`, `chat_graph`,
`conftest`, new `test_checkpoint_isolation.py`); no dependency, git or provider
change was made. Findings F-01…F-11, F-13…F-15 remain open; F-12 is closed for
the audit snapshot and F-05 is PARTIAL (path/import fixed, retention open).
