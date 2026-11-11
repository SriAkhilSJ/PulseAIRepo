# CrusorAI - Roadmap

**Snapshot:** 2026-11-10 (`feat/prompt-cache-stabilization`, HEAD `604605b2`)
**Rule:** items marked **Committed** exist in the repo or an explicit task;
items marked **Proposed** are candidates and are not authorized work.

---

## 1. Current position

- Phase 1.4 remains **WINDOWS SECURITY QUALIFIED** for the declared Windows 11 +
  Python 3.11/3.14 contract.
- The Agent Runtime migration (Increments 1–3, `docs/ARCHITECTURE.md` §14) is
  implemented and verified in the working tree: LangGraph is the sole
  interactive owner, engineering is delegated, context/tools/approvals/mutations
  are unified, and a canonical receipt + FinOps ledger exist.
- Runtime evidence is provider-free: 155 core tests, 232/3 security tests, 38/1
  bridge sidecar, restart replay for approve/deny/cancel, stale-approval tests.
- Live product qualification passed its first controlled task: the exact
  one-file prompt created only `hello.md`, was independently VERIFIED, and
  recorded one approval/mutation and one Velona invocation (₹0.014704).
  Two scope leaks were fixed. Total bounded live spend: ₹0.092942.
- Remaining: full TurnReceipt rendering, mojibake quality, live
  invocation-id re-verification, full-suite baseline, packaging, deployment
  and commit disposition.

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

**Status:** Decision needed; now 229 entries
**Scope:** decide whether the uncommitted Agent Runtime increments, broker
wiring, compiled desktop artifacts, tests and memory layer belong to future
commits or are retained as reviewed work.
**Constraint:** this task must not commit, reset, or delete them.
**Exit criteria:** each group is explicitly owned and scheduled, or left
untouched by instruction.

### N-3 - Phase 2 definition

**Status:** Superseded by the Agent Runtime increments
**Scope:** the runtime migration is complete; remaining work is Electron
integration and release hardening.
**Exit criteria:** none for the original Phase 2 brief.

### N-4 - Electron Agent-pane acceptance

**Status:** Provider-free E2E passed 2026-11-10; full receipts/live providers open
**Scope:** fixed the missing chat routing singleton and regenerated the shipped
panel hash; drove chat, engineering approve, denial and cancellation through the
real Electron UI.
**Exit criteria:** met for the provider-free path. Remaining: render the full
`TurnReceipt`, exercise live providers, packaging and headed qualification.

## 4. Next (proposed, highest value)

### P-1 - Enforce identity/RBAC in the live tool path

**Why:** `IdentityAwareToolAuthorizer` exists but is not connected (B-002).
**Work:** wire authorization into the tool dispatch boundary, fail closed for
unauthenticated/unauthorized roles, add adversarial tests, record an ADR update.
**Exit criteria:** a guest cannot execute a privileged tool; a permitted role
can; tests prove both; no ambient-permission bypass remains.

### P-2 - Commit or replace the mutation-broker integration

**Why:** HEAD file tools bypass ownership/snapshot/rollback (B-001).
**Status:** working tree now routes `write_file`/`edit_file` through the broker
with digest+precondition tokens; uncommitted.
**Work:** review and commit as its own scoped change, or retain with a written
owner decision.
**Exit criteria:** every interactive write goes through the broker with proof
and the commit is recorded.

### P-3 - Surface intelligence artifacts in protocol v2 and the desktop

**Why:** orchestrator outputs cannot be rendered (B-003).
**Work:** add typed frames for architecture/impact/regression/verification/
delivery artifacts; generate TypeScript; add renderers and contract tests.
**Exit criteria:** a real orchestrator run renders each artifact without
free-form JSON.

### P-3b - Surface the canonical TurnReceipt in the desktop

**Why:** the bridge now emits `receipt` with terminal status, changed files,
tests, approvals, mutations, evidence and FinOps ids; full UI rendering is not
proven (B-021).
**Work:** render the receipt as the authoritative turn card and remove remaining
event-reconstruction paths.
**Exit criteria:** UI counts/verdict match the persisted receipt on success,
denial, cancellation, partial and failure.

### P-4 - Restore a trustworthy full-suite baseline

**Why:** the last full-suite record has 25 failures (B-006); Increment 3 ran a
bounded 155-test core plus classified sidecar/eval suites, not the full suite.
**Work:** run the full suite on HEAD + working tree, classify each failure,
fix or quarantine with a documented reason, record exit codes.
**Exit criteria:** a clean or explicitly justified baseline with no unknown red.

### P-5 - Re-run live product acceptance

**Why:** P0.6.9 failed and LIVE12 is unvalidated (B-005).
**Work:** authorized, budgeted run on a headed host; capture artifacts, spend,
and verdict. Do not reuse or mutate the historical reservation without owner
approval.
**Exit criteria:** a new run with a complete artifact set and an honest verdict.

## 5. Later (proposed, structural)

| Item | Why | First step |
|---|---|---|
| Python 3.11 import purity | Remove `platform.system()` spawn and restore 3.11 CI (B-007). | Change to `os.name == "nt"`, run the guarded import probe on 3.11. |
| WindowStation/Desktop ACL recovery | Machine-level boundary remains unresolved (B-009). | Threat model and a reversible, audited repair design. |
| Unified financial store | Multiple money surfaces and heuristic reconciliation (B-010). | Define one transaction boundary or a formal reconciliation contract. |
| Prompt-cache-aware compaction | Compaction can invalidate the prefix (B-011). | Make compaction consult the cache plan; measure before/after. |
| Cost guard on by default | Spend can run until provider refusal (B-012). | Choose a safe default budget and surface it in the UI. |
| Desktop build reproducibility | Native modules and fork drift (B-014). | One documented clean build + launch recipe with hashes. |

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
