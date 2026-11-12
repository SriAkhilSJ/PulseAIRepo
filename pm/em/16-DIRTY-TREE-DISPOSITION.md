# Dirty-Tree Disposition Proposal (rev 2 — founder conditions incorporated)

Status: **approach approved with conditions (D-023); execution not started.**
Full per-entry ledger: `16-DIRTY-TREE-INVENTORY.csv` (273 rows).
Nothing has been run: no clean, reset, checkout-overwrite, stash, move or deletion.

Snapshot: `feat/prompt-cache-stabilization` @ `fb5bd528` — **273 entries = 84 modified tracked + 189 untracked,
0 staged, 0 deletions; +10,453 / −969 lines** across modified files.

---

## 0. Founder conditions and how each is satisfied

| Condition | How this plan satisfies it |
| --- | --- |
| Preserve every original entry | No delete, no move, no overwrite. R1–R4 only **add** paths to git; files stay where they are |
| Back up the complete dirty working tree first | **R0** below: filesystem copy + binary patch + pinned ref, verified by count and hash |
| Use a separate worktree or equivalent safe process | A worktree **cannot** capture uncommitted work (it starts from a commit). Equivalent safe process: R0 backup → pinned ref → additive commits → no file moves until review. Explained in §5 |
| Explicitly account for every inventory entry | §6 reconciliation: every one of the 273 has a row, a category and a disposition; sums are proven |
| Do not delete or quarantine without reviewing contents | R5 downgraded from "quarantine" to **review, summarise, then propose**. No removal in this pass |
| Do not merge the reconciliation branch without separate approval | Merge is not part of this plan; it requires a new founder decision after review |

---

## 1. What is in the tree (corrected categories)

An earlier draft mislabelled 8 first-party `contrib/crusorai` files as "vendored Code OSS, off limits". That
would have hidden real product code. Corrected: those 8 are **first-party contrib**, and they are in the
PRD-001 overlap set.

| Category | Count | Disposition |
| --- | --- | --- |
| Root reports (`*.md`) | 82 | R4 — commit as audit evidence |
| Diagnostics evidence | 68 | R4 — commit if it backs a cited claim, else archive |
| Product code (`src/**`) | 31 | R2 — commit with its tests |
| **Product code (first-party contrib)** | **8** | R3 — commit with the desktop change |
| Demo app (`apps/personal_finance`) | 27 | Leave in place (D-011); exclude from product build |
| Tests | 21 | R2 — commit with the code they cover |
| Docs & memory | 13 | R4 — commit; **includes the audit baseline** |
| Desktop tooling/config | 10 | R3 |
| Generated build output (`out/**`) | 9 | Regenerate; do not hand-commit |
| Scripts | 4 | R4 |
| **Total** | **273** | |

---

## 2. Two findings that drive the order

**F-A — the audit baseline is untracked.** `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md`, `docs/reviews/` and two
`HISTORY/` archives exist only on this disk. D-010 makes that audit the condition of record for every PRD
requirement. One disk failure erases the baseline.

**F-B — modified code needs its untracked siblings.** `orchestrator.py` (+457/−14) depends on untracked
`generation_progress.py` and `progress_events.py`; `context_manager.py` (+110/−2) depends on untracked
`workspace/discovery.py`, `access_grants.py`, `evidence.py`. Committing the modified set alone yields a commit
that cannot run. The two sets are one change.

Consequence: today's code is not `HEAD`. Line numbers drift — `AGENTS.md` cites the approval default at
`:1671-1675`; the file currently shows `:1697-1713`.

---

## 3. Explicit disposition of the named areas

| Area | Tracked | Dirty | Product dependency | Disposition |
| --- | --- | --- | --- | --- |
| `apps/personal_finance` | 29 | **27** (21 modified, 6 untracked) | **None** — no import from `src/` or `contrib/crusorai` | **Keep.** It is an agent-built demo referenced by `docs/ARCHITECTURE.md`. Commit its dirty files in R4 as demo evidence, or leave uncommitted if the founder prefers. It is **not** part of the product build and must never be cited as a product capability (D-011) |
| `linkedin-app` | 17 | **0** | None | **No action.** 16 JPGs + a research summary; already tracked and clean. Not in the 273. Removal needs a separate decision |
| `showcase` | 75 | **0** | None | **No action.** Benchmark outputs, already tracked and clean. Not in the 273 |
| `diagnostics` | 475 | **68** (6 modified, 62 untracked) | None (evidence only) | **R4.** Commit the captures that back a claim cited in `pm/` or the audit; archive the rest. Never delete: they are the only record of past runs |
| Generated files | — | 5 `req_*_module.py` + `p0_6_2_acceptance.py` + 9 `out/**` | — | `req_*` are **F-11 contamination** (~290 KB of synthetic modules written into `src/`). `out/**` is derived build output. **R5: review contents, summarise each, then propose removal — no action now** |

---

## 4. PRD-001 overlap — 21 files

The blocking set: 13 under `src/` (whole `src/orchestration/`, `chat_graph.py`, `mutation_broker.py`, plus two
untracked orchestration modules) and 8 under `contrib/crusorai/` (renderer, service, cards, protocol, CSS,
activity, session projection, plus untracked `crusorAITurnOutcome.ts`).

These are exactly the files T-02…T-05, T-15 and T-16 will edit. Until R2/R3 land, an agent's diff cannot be
distinguished from the founder's uncommitted work.

---

## 5. R0 — backup, then R1–R5

### R0 · Backup (must run before anything else)

```powershell
$stamp = "2026-11-12"
$dest  = "<founder-chosen path>\crusor-wip-$stamp"     # e.g. D:\crusor-backups\...
robocopy . $dest /E /XD .git node_modules .venv out __pycache__ .pytest_cache /XF *.pyc
git diff HEAD --binary            > "$dest\tracked-changes.patch"
git ls-files --others --exclude-standard > "$dest\untracked-list.txt"
git status --porcelain=v1         > "$dest\status-before.txt"
git rev-parse HEAD                > "$dest\BASE_COMMIT.txt"
git update-ref refs/backup/wip-2026-11-12 HEAD     # pins the base commit; no worktree change
```

**Verification:** `untracked-list.txt` must have 189 lines; `status-before.txt` must have 273; the patch must
apply cleanly to a scratch clone (`git apply --check`). Record file count and SHA-256 of the patch.

**Why not a worktree:** `git worktree add` creates a checkout of a *commit*. Uncommitted work lives in this
worktree's filesystem and would not be included. The safe equivalent is: filesystem copy + binary patch +
pinned ref, then additive commits that never move a file.

### Then, in order

| # | Commit | Contents | Gate |
| --- | --- | --- | --- |
| **R1** | `docs(audit): commit 2026-11-12 audit baseline` | `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md`, `docs/reviews/`, 2 `HISTORY/` archives | R0 verified |
| **R2** | `feat(agent): commit engineering discovery + streaming work` | `src/orchestration/*`, `src/workspace/{discovery,access_grants,evidence}.py`, `src/graphs/chat_graph.py`, 21 matching tests | R1 merged or at least pushed |
| **R3** | `feat(desktop): commit streaming cards + turn outcome` | 8 `contrib/crusorai` files; regenerate `out/**` instead of committing it | R2 pushed |
| **R4** | `docs(memory): reconcile current state, decisions, roadmap` | `AGENTS.md`, `CURRENT_STATE`, `DECISIONS`, `ROADMAP`, `BUGS_AND_LIMITATIONS`, `ARCHITECTURE`, `PHASE_TRACKER`, `LATEST_HANDOFF`, 82 root reports, 68 diagnostics, personal_finance demo | R2/R3 pushed |
| **R5** | *(review only)* | Summarise each of the 6 generated files; propose removal separately | Founder reviews summaries first |

Branch: `wip/working-tree-2026-11-12` from `origin/main`. **No merge to main without a separate decision.**

---

## 6. Reconciliation — every entry accounted for

| Bucket (from the CSV's `recommended_action`) | Count |
| --- | --- |
| Archive into an audit-evidence PR (R4) | 163 |
| Review, then commit or archive (R2/R3/R4) | 53 |
| Leave in place — demo, D-011 | 27 |
| **Priority: owner disposition before any PRD-001 branch** (R2/R3) | 21 |
| Regenerate / do not hand-commit | 9 |
| **Total** | **273** |

Cross-check by category: 82 + 68 + 31 + 8 + 27 + 21 + 13 + 10 + 9 + 4 = **273**.
Status split: 84 modified + 189 untracked = **273**.
The CSV is the per-entry ledger; no entry is unclassified.

---

## 7. What not to do

`git clean -fd` · `git reset --hard` · `git checkout -- .` · `git stash` · `git add -A` · a single "wip" commit ·
deleting `req_*` modules without reading them · committing `out/**` by hand · merging the reconciliation branch
without approval.

## 8. Decisions still needed

| # | Decision | Owner |
| --- | --- | --- |
| 1 | Approve the backup destination (R0 path) and run R0 | Founder |
| 2 | Approve executing R1–R4 as five reviewable commits | Founder |
| 3 | Review R5 summaries before any generated file is removed | Founder |
| 4 | Separate approval to merge the reconciliation branch | Founder |
