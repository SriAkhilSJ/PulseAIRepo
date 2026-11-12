# Technical Decision Requests (Tech Lead validation)

I am the EM, not the Technical Lead. These five decisions change architecture or security posture and must be
validated explicitly before the dependent ticket starts. Each request states the options, my engineering
recommendation, and what happens if the wrong option is chosen.

Default rule: **if no decision is recorded, the conservative option applies** (no bypass, fail closed, smallest
change). Silence never authorises the shortcut.

---

## TL-DR-1 · Where does an engineering task enter the tool loop?

| Option | Description | Risk |
| --- | --- | --- |
| **A1** Route at `engineering_task_node` | Node delegates to the tool loop, keeps DAG as lifecycle authority | Lowest; reuses tested routing |
| A2 Route inside `orchestrator` per plan node | Each DAG node invokes tools | 4d+; no tests exist for tools on that path |
| A3 Replace orchestrator with graph | Delete the DAG | Re-creates guarantees (verification, regression, impact) that already exist |

**Recommendation:** A1. **Blocks:** T-02. **If wrong:** A2 costs the milestone; A3 costs weeks.
**Evidence:** `chat_graph.py:7914-8126`, `orchestrator.py:76`, audit F-01.

---

## TL-DR-2 · How is the observability shadow resolved?

| Option | Description | Risk |
| --- | --- | --- |
| **B1** Rename module → `observability/receipts.py` | Merge into the package, update imports | Low; one obvious owner |
| B2 Rename package → `observability_pkg/` | Keeps module name; touches many imports | Medium; wide blast radius |
| B3 Duplicate the function in the package | Two sources of truth | **Rejected** — guarantees drift |

**Recommendation:** B1. **Blocks:** T-06, T-07. **If wrong:** duplicate implementations diverge and receipts
become untrustworthy again — the exact F-06 failure returning.

---

## TL-DR-3 · Sandbox default switch and unsupported-build behaviour

| Option | Description | Risk |
| --- | --- | --- |
| **C1** Default on; if AppContainer cannot start → task **blocked** with reason | Fail closed | Users on old Windows cannot run the agent until they opt out explicitly |
| C2 Default on; fall back to uncontained with a warning | Never blocks | Silent downgrade of the security claim |
| C3 Default off, prompt the user | Keeps today's behaviour | Repeats F-03; contradicts the product positioning |

**Recommendation:** C1. **Blocks:** T-10, T-12. **If wrong:** C2 is an outage-shaped security incident waiting
for a malicious repository.
**Note:** this decision changes user-visible availability on older Windows builds — a product trade, not only a
technical one. Founder must be aware.

---

## TL-DR-4 · Receipt storage engine

| Option | Description | Risk |
| --- | --- | --- |
| **D1** JSONL per day + SQLite rollups (additive) | Append-only, crash-safe, cheap | Two stores to keep consistent |
| D2 SQLite only | Single store | Write contention with long tasks |
| D3 Postgres/OTel collector | Analytics-grade | Infrastructure the solo founder must operate |

**Recommendation:** D1. **Blocks:** T-07, T-08. **If wrong:** D3 adds operational burden before revenue; D2
risks blocking the turn loop on disk I/O.

---

## TL-DR-5 · Does the engineering DAG keep its heuristic verifiers?

Existing verifiers are text-heuristic: `security_verifier.py:218-242` greps for `Depends(`; `runtime_verifier.py:96`
**hardcodes `latency_ms: 1.2`**. Under PRD-001, `success` must come from executed tests (FR-34).

| Option | Description | Risk |
| --- | --- | --- |
| **E1** Heuristics become advisory; test exit code is authoritative | Honest outcomes | Loses some pre-existing "verification" reporting |
| E2 Keep heuristics as-is alongside test exit code | Preserves existing reports | Two verdicts can disagree; F-09 persists |
| E3 Delete heuristics | Simplest | Removes context the DAG uses for repair targeting |

**Recommendation:** E1. **Blocks:** T-05. **If wrong:** E2 keeps a fabricated metric (`latency_ms: 1.2`) in the
product's evidence chain — precisely what the audit flagged.

---

## Decision log for these requests

| ID | Decision | Decided by | Date | Ticket unblocked |
| --- | --- | --- | --- | --- |
| TL-DR-1 | — pending — | Tech Lead / Founder | | T-02 |
| TL-DR-2 | — pending — | Tech Lead | | T-06 |
| TL-DR-3 | — pending — | Founder (product trade) | | T-10 |
| TL-DR-4 | — pending — | Tech Lead | | T-07 |
| TL-DR-5 | — pending — | Tech Lead | | T-05 |

Recorded as ADRs via the `develop-adr` skill once decided; one file per decision under `docs/adr/`.
