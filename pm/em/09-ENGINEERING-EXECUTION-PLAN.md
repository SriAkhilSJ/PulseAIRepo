# EM Execution Plan — PRD-001

Status: **draft for founder approval** · 2026-11-12 · Owner: Engineering Manager
Traceable to: `pm/08-PRD-001-TOOL-BACKED-ENGINEERING-LOOP.md` rev 1.1 (FR-1…FR-41, AC-1…AC-14)
Base: `origin/main` @ `8fa4e240` (contains audit baseline `fb5bd528`; tree identical, merges only)

---

## 1. Delivery model

Solo founder + AI coding agents + this EM plan. Therefore:

| Role | Reality |
| --- | --- |
| Founder | Product owner, only human approver, runs the live evidence |
| EM (me) | Decomposition, sequencing, ownership boundaries, evidence gate |
| Tech Lead | **Not a separate human.** Four decisions need explicit validation — see `12-TECHNICAL-DECISION-REQUESTS.md`. Until then the default is the conservative option |
| Coding agents | Implement exactly one ticket at a time, within declared file ownership |
| QA | Independent verification agent; may not be the agent that wrote the code |

**One ticket per agent session.** A session that finishes early does not "help" another workstream — it stops
and reports. Overlap causes conflicting edits in an 8,000-line graph file; that risk is larger than the time saved.

---

## 2. Workstreams and file ownership

No two workstreams may edit the same file. Where they must, the second waits for the first to merge.

| WS | Name | Owned paths (exclusive) | Owner |
| --- | --- | --- | --- |
| **A** | Execution path | `src/orchestration/**`, `src/graphs/**` | Backend agent A |
| **B** | Receipts & ledger | `src/observability.py`, `src/observability/**`, `src/finops/**`, `src/telemetry/pricing.py` | Backend agent B |
| **C** | Sandbox & env | `src/tools/terminal_tools.py`, `src/security/**` | Security agent |
| **D** | Profiles & UI | `src/context/permission_config.py`, `desktop/vscode/src/vs/workbench/contrib/crusorai/**` | Frontend agent |
| **E** | CI & truth | `.github/workflows/**`, `ci/**`, `TRUTH.md` | DevOps agent |
| **F** | Fixtures & evidence | `pm/fixtures/**`, `pm/evidence/**`, `src/tests/test_prd001_*.py` | QA agent |

**Conflict points and resolution:**

| Shared surface | Rule |
| --- | --- |
| `src/graphs/chat_graph.py` | WS-A only. No other agent touches it; WS-B reads it but does not edit |
| `src/context/permission_config.py` | WS-D only. WS-C requests changes via a ticket, never inline |
| `src/tools/terminal_tools.py` | WS-C only. WS-A calls the tool, never edits it |
| Tests | Each WS adds tests only under its own file prefix; QA owns cross-cutting tests |
| `pm/` docs | EM only |

---

## 3. Work breakdown structure

```
PRD-001
├── W1 Execution integrity (WS-A)          → T-01…T-05
├── W2 Evidence & receipts (WS-B)          → T-06…T-09
├── W3 Safe by default (WS-C)              → T-10…T-13
├── W4 Autonomy surface (WS-D)             → T-14…T-16
├── W5 Truth gate (WS-E)                   → T-17…T-18
└── W6 Fixtures, QA & evidence (WS-F)      → T-19…T-21
```

---

## 4. Dependency map

```
T-01 (spike: entry point)  ─┬─► T-02 (route engineering→tool loop) ──► T-03 (plan gate)
                            │                                        └─► T-04 (test-in-loop) ──► T-05 (blocked semantics)
                            │
T-06 (rename observability) ─┴─► T-07 (receipt emit) ──► T-08 (ledger) ──► T-09 (cost reconciliation)

T-11 (env scrub) ──► T-10 (containment default) ──► T-12 (fail-closed proof) ──► T-13 (egress deny)

T-14 (profile schema) ──► T-15 (profile UI) ──► T-16 (approval prompt fields)   [needs T-10 for containment state]

T-17 (collection errors) ──► T-18 (CI gate red/green)        [independent of A–D]

T-19 (fixtures) ──► T-20 (AC execution) ──► T-21 (evidence pack)   [needs T-02…T-07, T-10]
```

**Critical path:** T-01 → T-02 → T-03 → T-04 → T-19 → T-20 → T-21.
Anything not on this path is parallelisable; T-17/T-18 and T-06 are safe parallel starts.

---

## 5. Two-day schedule

### Day 1

| Time | WS-A | WS-B | WS-C | WS-D | WS-E | WS-F |
| --- | --- | --- | --- | --- | --- | --- |
| 09:00–10:00 | T-01 spike | T-06 rename | baseline capture | — | T-17 start | fixtures T-19 |
| 10:00–13:00 | T-02 routing | T-07 receipt | T-11 env scrub | T-14 schema | T-17 | fixtures |
| 14:00–16:00 | T-03 plan gate | T-08 ledger | T-10 default-on | T-15 UI | T-18 CI | fixture validation |
| 16:00–17:00 | T-04 start | T-09 reconcile | T-12 fail-closed | T-16 prompt | T-18 | — |
| **17:00** | **Go/No-Go** | | | | | |

### Day 2

| Time | Work |
| --- | --- |
| 09:00–11:00 | T-04 finish, T-05 blocked semantics, T-13 egress |
| 11:00–13:00 | T-20 run AC-1…AC-14; fix only blocking defects |
| 14:00–15:30 | T-21 evidence pack; adversarial rerun (T4) |
| 15:30–17:00 | Acceptance review against FR/AC; receipt reconciliation check; PRD sign-off |

---

## 6. Day-1 Go/No-Go

**GO requires all four:**

1. T-02 complete: an engineering-classified task enters the tool loop and the receipt records the path.
2. T-06 complete: `record_turn_receipt` imports and writes without raising.
3. T-19 complete: fixtures exist, are committed, and each declares `crusor.test_command`.
4. No new security regression: containment/env work has not been weakened to make T-02 pass.

**NO-GO action (not a deadline extension):**

| Condition | Cut |
| --- | --- |
| T-02 blocked by hidden coupling | Fall back to chat-path execution for the demo; label it `chat-path` in the receipt; keep T-03…T-05 for Day 2 |
| T-06 blocked | Stop; receipts are non-negotiable, nothing else matters without them |
| Fixtures incomplete | Run T2 only; declare T1/T3 deferred in the evidence pack |
| Security regression found | Stop the workstream that caused it; the milestone ships smaller or not at all |

Never: extend the deadline, disable a guard, or mark a task done on a model's self-report.

---

## 7. Definition of Done (every ticket)

A ticket is done only when **all six** exist:

1. Code merged into `docs/engineering-handoff-prd-001` (or the implementation branch cut from it).
2. A test that fails before the change and passes after — cited by name.
3. `pytest --collect-only` still exits 0.
4. Evidence line in `pm/evidence/two-day/manifest.md`: command, output, date, agent.
5. No new `TODO`/`FIXME` introduced in the touched files (existing ones must not increase).
6. QA agent (not the author) confirmed the acceptance criterion.

**Not done:** "it works on my run", screenshots without logs, a passing test that was skipped or `xfail`ed.

---

## 8. Branch and integration strategy

| Branch | Purpose |
| --- | --- |
| `main` | Canonical. Never commit here. |
| `docs/engineering-handoff-prd-001` | **This handoff** (docs + memory only). Founder reviews before implementation. |
| `feat/prd001-<ws>-<ticket>` | One branch per ticket, cut from the handoff branch after approval |
| `feat/prd001-integration` | Aggregates approved tickets; CI must be green before acceptance runs |

Rules: no force-push; no rebase of shared branches; one ticket per branch; squash on merge; the 273-entry
working tree is **not** part of any of this (see §9).

---

## 9. Working-tree hazard (must be resolved before implementation)

`git status` on `feat/prompt-cache-stabilization` shows **273 entries: 84 modified tracked, 189 untracked,
0 staged**. That includes the repository's own memory files (`AGENTS.md`, `docs/CURRENT_STATE.md`,
`docs/DECISIONS.md`, `docs/ROADMAP.md`, `docs/handoffs/LATEST_HANDOFF.md`).

Consequences:

1. Memory files cannot be updated and committed without bundling 84 unrelated modifications — so this handoff
   writes a **new dated handoff file** instead (repo convention) and leaves the pointer files untouched.
2. Any implementation branch cut from here would carry that dirt. Implementation must start from
   `origin/main`, and the founder must disposition the 273 entries first (ROADMAP N-2).
3. Recommendation: commit or archive the audit-reconciliation work as its own PR **before** PRD-001
   implementation. It is the difference between a reviewable diff and an unreviewable one.

---

## 10. Communication cadence (solo-adapted)

| Ritual | When | Output |
| --- | --- | --- |
| Ticket start | per session | one-line intent + file ownership claim |
| Ticket end | per session | DoD evidence block |
| Day-1 Go/No-Go | Day 1 17:00 | GO / CUT decision recorded in `DECISION-LOG` |
| Evidence review | Day 2 15:30 | AC matrix with raw counts per slice |
| Post-milestone | Day 3 | `iterate-lessons-log` entry; update risk register |

No standups, no status meetings. The evidence manifest is the status.
