# Dirty-Tree Disposition Proposal

Status: **proposal only — nothing was run.** No `git clean`, `reset`, `checkout --overwrite`, stash or deletion.
Full machine-readable inventory: `16-DIRTY-TREE-INVENTORY.csv` (273 rows: status, path, area, category,
PRD-001 overlap, added/removed lines, last commit, likely purpose, recommended action).

Snapshot: branch `feat/prompt-cache-stabilization`, HEAD `fb5bd528`, **273 entries = 84 modified tracked +
189 untracked, 0 staged, 0 deletions.** Uncommitted delta: **+10,453 / −969 lines** across modified files.

---

## 1. What is actually in there

| Category | Count | Meaning |
| --- | --- | --- |
| Root reports (`*.md`) | 82 | Phase verdicts, audits, limitation snapshots — evidence, not code |
| Diagnostics evidence | 68 | Trace/JSON captures from CDP and runtime runs |
| Product code (`src/**`) | 31 modified + untracked | The in-flight engineering/streaming work |
| Demo app (`apps/personal_finance`) | 27 | Agent-generated demo, not product (D-011) |
| Tests | 21 | New test modules for the same in-flight work |
| Docs & memory | 13 | `CURRENT_STATE`, `DECISIONS`, `ROADMAP`, `BUGS`, `ARCHITECTURE`, handoffs, **and the audit itself** |
| Desktop tooling/config | 10 | Build scripts, package-locks, `out/` metadata |
| Generated build output | 9 | `desktop/vscode/out/**` — derived, should be regenerated |
| Vendored Code OSS | 8 | `desktop/vscode/src/vs/**` — **off limits** per invariant 7 |
| Scripts | 4 | Acceptance/streaming helpers |

By area: `apps` 27 · `desktop` 27 · `diagnostics` 68 · `docs` 13 · `src` 52 · root reports 82 · scripts 4.

## 2. Two findings that change the plan

### F-A · The audit baseline is not committed

`docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` is **untracked**. So is `docs/reviews/` and two handoff archives
(`HISTORY/2026-11-12_p1a-pre.md`, `HISTORY/2026-11-12_pre-reconciliation.md`).

D-010 makes that audit the condition of record for every requirement in PRD-001. Today it exists on one disk,
in one working tree. If this machine fails, the baseline disappears and the PRD's traceability evaporates.

**This is the single highest-value commit available in the repository right now.**

### F-B · Modified code depends on untracked modules

The 84 modified files include the entire engineering runtime, and the untracked files are its missing halves:

| Modified (tracked) | Untracked sibling it likely needs |
| --- | --- |
| `src/orchestration/orchestrator.py` (+457/−14) | `generation_progress.py`, `progress_events.py` |
| `src/orchestration/context_manager.py` (+110) | `src/workspace/discovery.py`, `access_grants.py`, `evidence.py` |
| `src/graphs/chat_graph.py` (+105/−19) | `test_engineering_streaming.py`, `test_turn_outcome_semantics.py`… |
| `desktop/.../crusorAIRenderer.ts` (+99/−41) | `common/crusorAITurnOutcome.ts` |

Committing the modified files **without** their untracked siblings would create a commit that does not run.
The two sets are one change. This also means the code an agent reads today is not `HEAD` — line numbers drift
(example: AGENTS.md cites the approval default at `:1671-1675`; the file currently shows `:1697-1709`).

## 3. PRD-001 overlap — 21 files (the blocking set)

| Path | Δ | Last commit touching it | WS |
| --- | --- | --- | --- |
| `src/orchestration/orchestrator.py` | +457/−14 | `5197937a` canonical runtime | A |
| `src/orchestration/contract.py` | +445/−30 | `5197937a` | A |
| `desktop/.../crusorAIRendererService.ts` | +298/−137 | `f3528098` streaming cards | D |
| `src/orchestration/approval_gateway.py` | +133/−1 | `5197937a` | A |
| `desktop/.../common/crusorAICards.ts` | +118/−0 | `f3528098` | D |
| `src/orchestration/context_manager.py` | +110/−2 | `0b0e799d` intelligence | A |
| `src/graphs/chat_graph.py` | +105/−19 | `5197937a` | A |
| `src/orchestration/model_adapter.py` | +79/−9 | `5197937a` | A |
| `src/orchestration/scheduler.py` | +73/−11 | `5197937a` | A |
| `src/workspace/mutation_broker.py` | +56/−4 | `5197937a` | SEC |
| + 10 more (planner, models, visibility, renderer, protocol, CSS, activity, session projection) | | | A/D |

Plus two untracked files under `src/orchestration/` and one under `contrib/crusorai/`.

**Consequence for PRD-001:** T-02, T-03, T-04, T-05, T-15 and T-16 all edit these paths. Until the working tree is
committed or explicitly excluded, every ticket diff is computed against a state that exists nowhere in git,
and no reviewer can tell the agent's change from the founder's.

## 4. Generated and never-commit items

| Item | Action | Why |
| --- | --- | --- |
| `src/req_001…005_module.py`, `src/p0_6_2_acceptance.py` | Quarantine, then delete **with approval** | F-11 contamination: engineering tasks wrote products into `src/` |
| `desktop/vscode/out/**` (9 files) | Do not hand-commit; regenerate from source | Derived build output |
| Any `*.db`, `*.sqlite`, `.env` | Never commit | Local data / secrets (none currently present in status) |
| `diagnostics/**` traces | Commit if they back a cited claim; otherwise archive | Evidence, not product |

## 5. Recommended strategy — five commits on one reconciliation branch

Nothing is deleted. Nothing is rewritten. Each commit is reviewable on its own.

```
git switch -c wip/working-tree-2026-11-12 origin/main
```

| # | Commit | Contents | Why this order |
| --- | --- | --- | --- |
| **R1** | `docs(audit): commit 2026-11-12 audit baseline` | `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md`, `docs/reviews/`, both `HISTORY/*` archives | The condition of record must exist in git before anything cites it |
| **R2** | `feat(agent): commit engineering discovery + streaming work` | `src/orchestration/*`, `src/workspace/{discovery,access_grants,evidence}.py`, `src/graphs/chat_graph.py`, the 21 matching tests | Keeps code + its tests + its untracked siblings in one buildable commit |
| **R3** | `feat(desktop): commit streaming cards + turn outcome` | `contrib/crusorai/**`, `crusorAIProtocol.ts`, `crusorAICards.ts`, `common/crusorAITurnOutcome.ts`; regenerate `out/` instead of committing it | Desktop change depends on R2's protocol fields |
| **R4** | `docs(memory): reconcile current state, decisions, roadmap` | `AGENTS.md`, `CURRENT_STATE`, `DECISIONS`, `ROADMAP`, `BUGS_AND_LIMITATIONS`, `ARCHITECTURE`, `PHASE_TRACKER`, `LATEST_HANDOFF`, 82 root reports | The memory reconciliation that was never committed |
| **R5** | `chore(repo): quarantine generated modules` | Move `req_*_module.py`, `p0_6_2_acceptance.py` to `quarantine/` **with approval** | Removes F-11 contamination from `src/` without deleting history |

Then: PR `wip/working-tree-2026-11-12` → `main`, review, merge. Only afterwards cut
`feat/prd001-*` branches from the new `main`.

**Why a branch, not a stash:** the AGENTS.md invariants forbid stash/reset without an explicit named purpose, and
a stash is invisible to review. A branch commit is inspectable, revertable and attributable.

## 6. What not to do

| Tempting action | Why not |
| --- | --- |
| `git clean -fd` | Destroys 189 untracked files including the audit baseline and 21 tests |
| `git reset --hard` | Discards +10,453 lines of feature work |
| `git checkout -- .` | Same, invisibly |
| `git add -A` | Violates invariant 2 and sweeps `apps/`, `out/`, diagnostics into one unreviewable commit |
| Commit everything as one "wip" | Unreviewable; mixes product code with 82 reports and a demo app |

## 7. Decision required

Approve the five-commit strategy (R1–R5), or name a different grouping. R1 is urgent independent of PRD-001:
the audit baseline is one disk failure away from being lost.
