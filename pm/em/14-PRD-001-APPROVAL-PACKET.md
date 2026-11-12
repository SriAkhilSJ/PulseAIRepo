# PRD-001 Sign-off Packet (final) — Founder Decisions Recorded

PRD-001 **rev 1.2** (approved direction; sandbox clarified) · 2026-11-12
Companions: `15-TECHNICAL-DECISION-REGISTER.md` · `16-DIRTY-TREE-DISPOSITION.md` · `08-PRD-001-…md`

---

## 1. Decision status — as recorded

| ID | Decision | Status | Date |
| --- | --- | --- | --- |
| TL-DR-1 | **A1** — route at `engineering_task_node`; DAG keeps lifecycle authority | **ACCEPTED** | 2026-11-12 |
| TL-DR-2 | **B1** — rename module into `observability/receipts.py` | **ACCEPTED** | 2026-11-12 |
| TL-DR-3 | **C1′** — containment default-on, fail-closed; **no opt-out** | **ACCEPTED (corrected)** | 2026-11-12 |
| TL-DR-4 | **D1** — JSONL + SQLite rollups | **ACCEPTED** | 2026-11-12 |
| TL-DR-5 | **E1** — test exit code authoritative | **ACCEPTED** | 2026-11-12 |
| P1–P5 | PRD decisions | **ACCEPTED** | 2026-11-12 |

## 2. The sandbox rule (C1′), exactly as approved

Containment is default-on and fail-closed. If sandbox initialisation fails, or the Windows build is
unsupported:

1. **Terminal execution is blocked.**
2. **The reason is explained** — in the UI and in the receipt.
3. **Non-terminal capability stays available** where safe (read, search, edit inside the workspace).
4. **No uncontained shell is ever permitted through an opt-out** — no setting, env var or profile restores one.

Recorded in: PRD **FR-26**, **AC-11**, **SEC-1**, the edge-case table; register **TL-DR-3**; tickets **T-10**,
**T-12**; security gates **SG-1**, **SG-9**.

This **reverses** the earlier recommendation, which allowed an explicit opt-out. The opt-out clause is now
prohibited, and T-12 tests that an attempted opt-out is ignored.

## 3. What changed in PRD rev 1.2

Only the sandbox clarification. Scope, requirements, acceptance criteria and security invariants are otherwise
unchanged from rev 1.1. Revision history records both steps.

## 4. Dirty tree — approved with conditions (D-023)

Conditions accepted and encoded in `16-DIRTY-TREE-DISPOSITION.md` §0:

preserve every entry · back up the full tree first (R0) · separate-worktree-or-equivalent (explained: a
worktree cannot capture uncommitted work, so R0 backup + pinned ref + additive commits) · account for every
entry (§6 reconciliation, 273 = 273) · no delete/quarantine without content review (R5 is review-only) · no
merge without separate approval.

Named areas, explicitly dispositioned: `personal_finance` (27 dirty, no product dependency, keep as demo),
`linkedin-app` (17 tracked, **0 dirty** — no action), `showcase` (75 tracked, **0 dirty** — no action),
`diagnostics` (68 dirty, evidence — commit if cited, else archive), generated files (5 `req_*` ≈290 KB of F-11
contamination + 9 `out/**` — review first, no action now).

## 5. Provider (D-024)

Approved reference configuration: `custom` / `velona.in` / `z-ai/glm-5.3-flash`.
Verified: configuration clean; a 2-token probe answered `READY` in 8.7 s, so credit > 0.
**Exact balance: UNKNOWN.** Constraint recorded: **no expensive evidence runs until a spending limit is
confirmed.**

## 6. Security invariants (unchanged, now with SG-9)

1. Containment on by default; failure blocks terminal execution; **no opt-out**.
2. Child processes never inherit provider keys.
3. No write outside the workspace without an explicit grant.
4. Approval tokens HMAC-bound and single-use.
5. Repository content is data; injected instructions never execute.
6. `verified` requires an executed check.
7. The agent cannot edit its own permission configuration.
8. **New:** no setting, env var or profile may restore an uncontained shell.

## 7. Two-day acceptance criteria (unchanged)

≥2/3 first attempt · 3/3 with ≤2 interventions · test command run 3/3 · 0 unapproved mutations · receipts
100% · 0 false success · 0 collection errors · 0 chat regressions. Raw counts per slice; no rate claims.

## 8. Remaining approvals before implementation

| # | Approval | Status |
| --- | --- | --- |
| A1 | Approve R0 backup destination and run the backup | **OPEN** |
| A2 | Approve executing R1–R4 as five reviewable commits | **OPEN** |
| A3 | Review R5 generated-file summaries before removal | **OPEN** (blocked on R5 review) |
| A4 | Separate approval to merge the reconciliation branch | **OPEN** (not requested yet) |
| A5 | Confirm a spending limit for provider runs | **OPEN** — gates any expensive evidence run |
| A6 | PRD-001 rev 1.2 signature | **OPEN** — sign below |

Implementation does not begin until A1–A2 and A6 are recorded.

---

**Sign-off**

```
PRD-001 rev 1.2      Approved: ______________________  Date: __________
TL-DR-1/2/4/5        Accepted: ______________________  Date: __________
TL-DR-3 (C1′)        Accepted: ______________________  Date: __________
Dirty-tree R0–R4     Approved: ______________________  Date: __________
Spending limit       Confirmed: _____________________  Date: __________
```
