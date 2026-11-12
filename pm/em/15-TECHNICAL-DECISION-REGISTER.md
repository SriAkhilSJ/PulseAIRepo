# Technical Decision Register — PRD-001

Status of every decision below: **RECOMMENDED (founder review, 2026-11-12) — awaiting explicit sign-off.**
Nothing is marked Accepted. Implementation remains blocked until each row's status becomes `ACCEPTED`.
Status vocabulary: `RECOMMENDED` · `ACCEPTED` · `DEFERRED` · `REJECTED`.

Founder recommendations received: TL-DR-1 = A1, TL-DR-2 = B1, TL-DR-3 = C1, TL-DR-4 = D1, TL-DR-5 = E1.
Consequences are stated before the status, per the review instruction.

---

## TL-DR-1 · Tool-loop entry point → **A1 recommended**

| | |
| --- | --- |
| **Decision** | Route at `engineering_task_node`; the node delegates to the tool loop and the DAG keeps lifecycle authority |
| **Blocks** | T-02 |
| **Status** | RECOMMENDED |

**Consequences of adopting A1**
- Reuses the routing path already covered by `test_canonical_runtime_engineering_delegation.py`.
- The DAG keeps verification, regression and impact bookkeeping (FR-2), so nothing already earned is lost.
- Cost: one node grows in responsibility; its failure mode becomes "engineering task runs as chat", which is
  visible and labelled in the receipt rather than silent.
- Residual risk: hidden coupling in `chat_graph.py` (8,218 lines, and 105 lines of it are uncommitted work).

**Consequences of the alternatives**
- A2 (route inside each DAG node): ~4 days, no existing tests for tools on that path, exceeds the milestone.
- A3 (delete the DAG): re-creates verification/regression/impact guarantees that already exist; weeks.

---

## TL-DR-2 · Observability shadow → **B1 recommended**

| | |
| --- | --- |
| **Decision** | Rename the module into the package: `src/observability/receipts.py`, update the three import sites |
| **Blocks** | **T-06**, T-07 |
| **Status** | RECOMMENDED |

**Consequences of adopting B1**
- One owner, one obvious import path; receipts become available with no behavioural change.
- Touches only the observability surface plus 3 import lines — the smallest blast radius available.
- Unblocks T-06 and therefore the Day-1 Go/No-Go condition.

**Consequences of the alternatives**
- B2 (rename the package): many import sites, higher risk of a partial rename that silently reintroduces the bug.
- B3 (duplicate the function): two sources of truth; receipts drift; the F-06 class of failure returns silently.

**Dependency note:** T-06 is **blocked** until this is signed off, then becomes a safe parallel start. An earlier
draft listed it as both, which was contradictory; corrected in `09` §4 and `10` T-06.

---

## TL-DR-3 · Sandbox default → **C1 recommended**

| | |
| --- | --- |
| **Decision** | Containment default-on; if AppContainer cannot start, the task is **blocked** with a reason (fail closed) |
| **Blocks** | T-10, T-12 |
| **Status** | RECOMMENDED — **product trade, founder-owned** |

**Consequences of adopting C1**
- The security claim becomes true; a malicious repository cannot obtain an uncontained shell.
- Users on unsupported or misconfigured Windows builds **cannot run the agent until they explicitly opt out**.
  That is a real availability cost on older machines, and it will generate support questions.
- The opt-out must be visible and recorded in the receipt, otherwise C1 degrades into C2 with extra steps.

**Consequences of the alternatives**
- C2 (fall back uncontained with a warning): silent downgrade of the product's central claim; an incident waiting
  for a malicious repo.
- C3 (default off): repeats F-03 and contradicts the positioning in `02-PRODUCT-STRATEGY.md`.

---

## TL-DR-4 · Receipt storage → **D1 recommended**

| | |
| --- | --- |
| **Decision** | Append-only JSONL per day + SQLite rollups (additive) |
| **Blocks** | T-07, T-08 |
| **Status** | RECOMMENDED |

**Consequences of adopting D1**
- Crash-safe: a killed turn leaves the last complete JSONL row, which the receipt requirement depends on.
- No new infrastructure to operate as a solo founder; SQLite is already used by the product.
- Cost: two stores to reconcile. Mitigated by making JSONL the source of truth and SQLite a derived view.

**Consequences of the alternatives**
- D2 (SQLite only): write contention during long turns; one corrupt write loses the evidence chain.
- D3 (Postgres/OTel collector): analytics-grade, but adds an operated service before revenue.

---

## TL-DR-5 · DAG verifier authority → **E1 recommended**

| | |
| --- | --- |
| **Decision** | Heuristics become advisory; the test exit code is authoritative for `success` |
| **Blocks** | T-05 |
| **Status** | RECOMMENDED |

**Consequences of adopting E1**
- Outcomes become falsifiable: `success` means a command exited 0 (FR-34).
- Some existing "verification" reporting loses its verdict status; the DAG still uses heuristics for repair targeting.
- Exposes how much of the current verification was cosmetic — a short-term reporting loss, a long-term trust gain.

**Consequences of the alternatives**
- E2 (keep both verdicts): two answers can disagree; F-09 persists; `latency_ms: 1.2` stays in the evidence chain.
- E3 (delete heuristics): loses repair targeting, which the DAG needs.

---

## PRD decisions (P1–P5) — status

| ID | Decision | Status | Note |
| --- | --- | --- | --- |
| P1 | Declared `crusor.test_command` + documented fixture overrides | **ACCEPTED (adopted in rev 1.1, FR-19)** | Inference only as a labelled fallback |
| P2 | No implicit auto-approval; explicit visible opt-in; sandbox never bypassed | **ACCEPTED (FR-25)** | Supersedes the `workspace_session` default |
| P3 | Checkpoint retention deferred; no user-data deletion; DB not shipped | **ACCEPTED (NFR-6)** | Revisit at P1 |
| P4 | Reference provider `custom` / `velona.in` / `z-ai/glm-5.3-flash` | **ACCEPTED-CONDITIONAL** | Config verified; **balance not verified** (see §Provider) |
| P5 | Enterprise profile deferred; schema extensible | **ACCEPTED (FR-23)** | Two profiles ship |

## Sign-off block

| Decision | Recorded status | Signed by | Date |
| --- | --- | --- | --- |
| TL-DR-1 (A1) | RECOMMENDED | — | — |
| TL-DR-2 (B1) | RECOMMENDED | — | — |
| TL-DR-3 (C1) | RECOMMENDED | — | — |
| TL-DR-4 (D1) | RECOMMENDED | — | — |
| TL-DR-5 (E1) | RECOMMENDED | — | — |

Each becomes `ACCEPTED` only when this block is filled and an ADR is written under `docs/adr/`
(one file per decision, `develop-adr` skill).
