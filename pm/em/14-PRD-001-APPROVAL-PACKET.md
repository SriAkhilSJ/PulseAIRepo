# PRD-001 Approval Packet (corrected) — Founder Decision Sheet

Rev 1.1 · corrected 2026-11-12 after founder review. Supersedes the earlier packet.
Companion documents: `15-TECHNICAL-DECISION-REGISTER.md` · `16-DIRTY-TREE-DISPOSITION.md` ·
`08-PRD-001-…md` rev 1.1.

---

## 1. What you are approving

Make the existing tool loop authoritative for engineering execution: genuine read → search → edit → terminal →
test → verify, with receipts, default-on containment and **two** autonomy profiles (Beginner, Developer).
41 functional requirements, 14 acceptance criteria, 21 tickets, all traced to code or the Nov-12 audit.

Not approving: a release, installer, public download, enterprise features, or any benchmark claim.

---

## 2. Corrections made in this revision

| # | Finding | Correction |
| --- | --- | --- |
| 1 | T-06 was listed both as a "safe parallel start" and as blocked by TL-DR-2 | T-06 is **blocked until TL-DR-2 is signed**, then a safe parallel start. Fixed in `09` §4, `09` §6, `10` T-06 |
| 2 | Profile count drifted to three in four documents | Beginner + Developer only, everywhere: PRD FR-23/US-8/UX, `02`, `04`, `06`, `07`, `14` |
| 3 | PRD frontmatter still said `version: "1.0"` | Now `version: "1.1"`, status `draft-rev1.1-for-approval` |
| 4 | F-01 was described as "zero repository awareness" | Corrected: Phase 2A adds bounded **read-only discovery**; generation binds no read/search/list/test tools. Shell tools are hard-blocked by `_GRAPH_MUTATION_BLOCKED`, so re-enabling them is part of the work |
| 5 | Test count stated as 4,986 flat | Stated as 4,968–4,986 (HEAD vs dirty working tree), 3 collection errors in both |

---

## 3. The ten decisions and their recorded status

Full consequences: `15-TECHNICAL-DECISION-REGISTER.md`.

| ID | Decision | Status |
| --- | --- | --- |
| TL-DR-1 | **A1** — route at `engineering_task_node`, DAG keeps lifecycle authority | RECOMMENDED |
| TL-DR-2 | **B1** — rename module into `observability/receipts.py` | RECOMMENDED |
| TL-DR-3 | **C1** — sandbox default-on, fail closed; unsupported builds blocked until explicit opt-out | RECOMMENDED (product trade) |
| TL-DR-4 | **D1** — JSONL append + SQLite rollups | RECOMMENDED |
| TL-DR-5 | **E1** — test exit code authoritative, heuristics advisory | RECOMMENDED |
| P1 | Declared `crusor.test_command` | ACCEPTED (FR-19) |
| P2 | No implicit auto-approval; visible opt-in; sandbox never bypassed | ACCEPTED (FR-25) |
| P3 | Retention deferred; no data deletion; DB not shipped | ACCEPTED (NFR-6) |
| P4 | Reference provider `custom` + `z-ai/glm-5.3-flash` | ACCEPTED-CONDITIONAL — **config and credit now verified** |
| P5 | Enterprise profile deferred; schema extensible | ACCEPTED (FR-23) |

The five TL rows stay `RECOMMENDED` until you sign. Nothing is marked Accepted on your behalf.

---

## 4. Provider verification (no credentials displayed)

| Check | Method | Result |
| --- | --- | --- |
| Configuration | `scripts/check_provider.py` (no network, no cost) | **PASS** — provider `custom`, model `z-ai/glm-5.3-flash`, base host `velona.in`, key present (50 chars) |
| Key validity + credit | `scripts/check_provider.py --live` — the repo's own documented **2-token** probe | **PASS** — answered `READY` in 8.7 s; a billing refusal would have failed, so credit > 0 |
| Exact balance | No documented balance endpoint on this OpenAI-compatible endpoint | **UNKNOWN** — requires the provider dashboard |

Cost of the probe: one 2-token completion (a fraction of a cent). No benchmark was run.
Recommendation: keep a manual dashboard check before the Day-2 run; do not treat "it answered" as a budget.

---

## 5. Dirty tree — what you must decide

273 entries (84 modified, 189 untracked), **+10,453 / −969 lines**. Full inventory in
`16-DIRTY-TREE-INVENTORY.csv`; proposal in `16-DIRTY-TREE-DISPOSITION.md`.

Two findings that change priorities:

1. **The audit baseline is untracked.** `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` exists only on this disk.
2. **Modified code needs its untracked siblings.** `orchestrator.py` (+457) imports `generation_progress.py` and
   `progress_events.py`, which are untracked. Committing one without the other creates a commit that cannot run.

Recommended: five reviewable commits on `wip/working-tree-2026-11-12` (R1 audit → R2 agent code → R3 desktop →
R4 memory → R5 quarantine generated `req_*` modules). Nothing deleted, nothing reset, nothing stashed.

**21 files overlap PRD-001 paths** (whole `src/orchestration/`, `chat_graph.py`, `mutation_broker.py`, the
renderer/cards/protocol set). Until this is dispositioned, agent diffs cannot be distinguished from your
uncommitted work.

---

## 6. Security invariants — non-negotiable

1. Containment on by default; failure blocks, never silently degrades.
2. Child processes never inherit provider keys.
3. No write outside the workspace without an explicit grant.
4. Approval tokens stay HMAC-bound and single-use.
5. Repository content is data; injected instructions never execute.
6. `verified` requires an executed check, otherwise the product says `unverified`.
7. The agent cannot edit its own permission configuration.

If a fix requires breaking one, the milestone shrinks. That is the product's only defensible claim.

---

## 7. Two-day acceptance criteria

| Criterion | Bar |
| --- | --- |
| T1–T3 | ≥2/3 first attempt; 3/3 with ≤2 interventions |
| Test execution | 3/3; failure output changes the next edit |
| Unapproved mutations | 0, including T4 |
| Receipts | 100% of runs, all fields; cost within ±10% of provider dashboard |
| False success | 0; T5 returns `blocked` |
| Collection errors | 0; CI red-blocks a red suite |
| Chat regression | 0 new failures |

Raw counts per slice. No percentage claims from five cases.

---

## 8. Exact remaining founder decisions

| # | Decision | Effect if delayed |
| --- | --- | --- |
| **D1** | Sign the five TL decisions (A1/B1/C1/D1/E1) | T-02, T-05, T-06, T-07, T-10 stay blocked; only T-19 and two of T-17's three modules can start |
| **D2** | Approve the dirty-tree plan (R1–R5) | No clean implementation base; R1 (audit baseline) remains one disk failure from loss |
| **D3** | Accept C1's availability cost: old/misconfigured Windows builds are blocked until explicit opt-out | The only decision with a user-visible downside; it is yours, not mine |
| **D4** | Confirm the reference provider as the single evidence provider | Numbers stay non-reproducible; balance is still UNKNOWN |
| **D5** | Approve PRD-001 rev 1.1 itself (sign-off line) | No tickets may start |

---

## 9. What approval authorises, and what it does not

**Authorises:** cutting `feat/prd001-*` from a cleaned base; starting T-19 immediately and two of T-17's three
modules (the observability module waits on T-06); starting
T-06 after D1; running the acceptance matrix on the reference provider.

**Does not authorise:** pushing to `main`, merging the handoff branch, any public binary or download, any public
claim of production readiness, any weakening of §6, or publishing any cost/benchmark number before the evidence
pack exists.

---

**Sign-off**

```
PRD-001 rev 1.1   Approved: ______________________  Date: __________
TL-DR-1..5        Accepted: ______________________  Date: __________
Dirty-tree R1–R5  Approved: ______________________  Date: __________
```
