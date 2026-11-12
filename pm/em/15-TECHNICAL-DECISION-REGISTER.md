# Technical Decision Register — PRD-001

Status: **FOUNDER-ACCEPTED 2026-11-12** (four as recommended, TL-DR-3 corrected before acceptance).
Single source of truth. `12-TECHNICAL-DECISION-REQUESTS.md` is a pointer to this file.
Status vocabulary: `ACCEPTED` · `RECOMMENDED` · `DEFERRED` · `REJECTED`.

---

## TL-DR-1 · Tool-loop entry point → **A1 — ACCEPTED**

| | |
| --- | --- |
| **Decision** | Route at `engineering_task_node`; the node delegates to the tool loop and the DAG keeps lifecycle authority |
| **Accepted** | 2026-11-12 (founder) |
| **Unblocks** | T-02 |

**Consequences accepted:** reuses the routing path already covered by
`test_canonical_runtime_engineering_delegation.py`; the DAG keeps verification, regression and impact
bookkeeping (FR-2). One node grows in responsibility; its failure mode is "engineering task runs as chat",
which is visible and labelled in the receipt. Residual risk: hidden coupling in `chat_graph.py`
(8,218 lines, 105 of them uncommitted work — see `16-DIRTY-TREE-DISPOSITION.md`).

**Rejected alternatives:** A2 (route inside each DAG node — ~4 days, untested path, exceeds the milestone);
A3 (delete the DAG — re-creates guarantees that already exist).

---

## TL-DR-2 · Observability shadow → **B1 — ACCEPTED**

| | |
| --- | --- |
| **Decision** | Rename the module into the package: `src/observability/receipts.py`, update the three import sites |
| **Accepted** | 2026-11-12 (founder) |
| **Unblocks** | **T-06**, then T-07 |

**Consequences accepted:** one owner, one import path, no behavioural change; smallest blast radius.
T-06 is no longer blocked and is a safe parallel start as of this acceptance.

**Rejected alternatives:** B2 (rename the package — wide blast radius); B3 (duplicate the function — two
sources of truth, the F-06 failure returns silently).

---

## TL-DR-3 · Sandbox default → **C1′ — ACCEPTED (corrected by founder)**

| | |
| --- | --- |
| **Decision** | Containment default-on and **fail-closed**. If sandbox initialisation fails, or the Windows build is unsupported: **block terminal execution**, state why, keep non-terminal capability available where safe, and **never permit an uncontained shell through an opt-out** (no opt-out exists). |
| **Accepted** | 2026-11-12 (founder), after correction |
| **Unblocks** | T-10, T-12 |

**Correction history.** The earlier recommendation (C1) allowed an *explicit opt-out* for unsupported builds.
The founder rejected that clause: an opt-out is an uncontained shell by another name. C1′ removes it. The
register, PRD (FR-26, AC-11, SEC-1), tickets T-10/T-12 and security gate SG-1 now all state the same rule.

**Consequences accepted:**
- On an unsupported or misconfigured Windows build, **shell commands cannot run at all**. Tasks that need a
  command end `blocked`, not "partially successful".
- Read / search / edit inside the workspace keep working, so the agent is degraded, not dead.
- There is no setting, flag or profile that restores an uncontained shell. Users who need one must fix the
  environment (supported build, sandbox available) — a support cost, deliberately accepted.
- The product's containment claim becomes true without a footnote.

**Rejected alternatives:** C2 (fall back uncontained with a warning — silent downgrade); C3 (default off);
and now also **C1-with-opt-out** (rejected explicitly by the founder).

---

## TL-DR-4 · Receipt storage → **D1 — ACCEPTED**

| | |
| --- | --- |
| **Decision** | Append-only JSONL per day + SQLite rollups (additive) |
| **Accepted** | 2026-11-12 (founder) |
| **Unblocks** | T-07, T-08 |

**Consequences accepted:** crash-safe (last complete row survives a kill); no new infrastructure for a solo
founder; two stores to reconcile, mitigated by JSONL as source of truth and SQLite as a derived view.

**Rejected alternatives:** D2 (SQLite only — write contention, single corrupt write loses the evidence chain);
D3 (Postgres/OTel collector — operated service before revenue).

---

## TL-DR-5 · DAG verifier authority → **E1 — ACCEPTED**

| | |
| --- | --- |
| **Decision** | Heuristics become advisory; the test exit code is authoritative for `success` |
| **Accepted** | 2026-11-12 (founder) |
| **Unblocks** | T-05 |

**Consequences accepted:** outcomes become falsifiable (`success` = exit 0). Some existing "verification"
reporting loses verdict status; the DAG keeps heuristics for repair targeting. Exposes how much current
verification was cosmetic — a short-term reporting loss for a long-term trust gain.

**Rejected alternatives:** E2 (two verdicts that can disagree — F-09 persists); E3 (delete heuristics — loses
repair targeting).

---

## PRD decisions (P1–P5)

| ID | Decision | Status |
| --- | --- | --- |
| P1 | Declared `crusor.test_command` + documented fixture overrides | **ACCEPTED** (FR-19) |
| P2 | No implicit auto-approval; explicit visible opt-in; sandbox never bypassed | **ACCEPTED** (FR-25) |
| P3 | Checkpoint retention deferred; no user-data deletion; DB not shipped | **ACCEPTED** (NFR-6) |
| P4 | Reference provider `custom` / `velona.in` / `z-ai/glm-5.3-flash` | **ACCEPTED** (D-024) — balance unknown; no expensive runs until a spending limit is set |
| P5 | Enterprise profile deferred; schema extensible | **ACCEPTED** (FR-23) |

## Sign-off

| Decision | Status | Signed by | Date |
| --- | --- | --- | --- |
| TL-DR-1 (A1) | ACCEPTED | Founder | 2026-11-12 |
| TL-DR-2 (B1) | ACCEPTED | Founder | 2026-11-12 |
| TL-DR-3 (C1′) | ACCEPTED (corrected) | Founder | 2026-11-12 |
| TL-DR-4 (D1) | ACCEPTED | Founder | 2026-11-12 |
| TL-DR-5 (E1) | ACCEPTED | Founder | 2026-11-12 |

ADRs to be written under `docs/adr/` (`develop-adr` skill) as part of the implementation phase — one per
decision, recording the same consequences.
