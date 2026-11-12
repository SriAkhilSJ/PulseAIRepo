# Engineering Roadmap

Status: **DRAFT FOR APPROVAL** · 2026-11-12 · Solo founder baseline · Estimates in focused engineering days.

---

## 1. Adjustments to the founder's P0…P4, and why

I kept the five bands but changed three things, based on repository evidence.

| Change | Reason (evidence) |
| --- | --- |
| **Added "Truth gate" as first P0 item** | CI never runs the 4,986-test suite; the full-suite workflow sits in `ci/` outside `.github/workflows`. Five capabilities are described contradictorily across docs. Without this, no later claim is verifiable and every estimate is guesswork. |
| **Split P0 into P0-A (agent works) and P0-B (agent is safe)** | They are independent: P0-A is one code path, P0-B is one default + one UI surface. Sequencing them separately avoids a 2-week blob. |
| **Pulled a trivial monetisation slice into month 3 (P3-lite), left real billing in P3** | Stripe Payment Link + licence file needs ~2 days and no auth system. Waiting for full auth/billing before taking money risks the 3–6 month revenue target for no reason. |
| **Kept enterprise last** | Enterprise needs signing, SSO, policy, egress, audit export — five absent systems. Nothing in the repo shortens that. |

---

## 2. P0-A — Agent core actually works (target: 10 working days)

**Goal:** a real task on a real repository completes end-to-end with tools, approvals, tests and a receipt.

| ID | Task | Effort | Depends on | Done when |
| --- | --- | --- | --- | --- |
| A1 | Route engineering execution through the tool-backed loop (read/search/edit/terminal) instead of generation-only | 4d | — | `src/orchestration` can call file+search tools; a task reads a file before editing it |
| A2 | Keep the existing plan contract (planner → preview → approval) on that path | 2d | A1 | Plan visible before first mutation in `engineering_task` mode |
| A3 | Test-in-the-loop: agent runs the repo's tests and reads failures | 2d | A1 | Failing test output re-enters the context and changes the next edit |
| A4 | Fix `src/observability/` package shadowing so turn receipts are written | 0.5d | — | `record_turn_receipt` importable; JSONL/SQLite row per turn |
| A5 | Task ledger v0 (task_id, tokens, cost, outcome, duration) | 1.5d | A4 | One row per task, survives restart |

**Exit criteria:** 3 scripted tasks (greenfield, bug fix, small refactor) reach a green test run with ≤2 human
interventions each, on one provider, with a receipt.

---

## 3. P0-B — Agent is safe by default (target: 5 working days)

| ID | Task | Effort | Depends on | Done when |
| --- | --- | --- | --- | --- |
| B1 | Make containment default-on (AppContainer where available), fail **closed** not open | 2d | — | Uncontained run requires explicit opt-in; failure logs and blocks |
| B2 | Scrub inherited environment for child processes (no API keys in shell) | 0.5d | — | Child env allowlist test passes |
| B3 | Two visible autonomy profiles - Beginner / Developer - mapped to real allow/ask/deny; Enterprise deferred with extensible schema | 2d | B1 | Profile selectable in UI; profile file is the only source of truth |
| B4 | Surface the active profile + risk level on every approval prompt | 0.5d | B3 | Screenshot-level acceptance |

**Exit criteria:** a repository containing a prompt-injection README cannot cause an unapproved write or an
uncontained shell command, demonstrably, on Windows.

---

## 4. P0-C — Truth gate (target: 3 working days, runs in parallel)

| ID | Task | Effort | Done when |
| --- | --- | --- | --- |
| C1 | Fix 3 collection errors; get suite collecting clean | 1d | `pytest --collect-only` exits 0 |
| C2 | Move full-suite workflow into `.github/workflows`, remove `\|\| true` / `set +e` swallow points | 1d | PR cannot merge on red |
| C3 | Write `TRUTH.md`: single condition-of-record (HEAD + audit), mark 5 contradictory docs as superseded | 1d | One file answers "what is true today?" |

**Why this is first:** your own repository currently says both "395/395 qualified" and "do not claim a clean
suite". Any roadmap built on top of that is unverifiable, and a design partner will find it in week one.

---

## 5. P1 — Production-ready desktop (weeks 3–6)

| ID | Task | Effort | Depends on |
| --- | --- | --- | --- |
| D1 | Reproducible build + code signing/notarisation pipeline | 5d | — |
| D2 | One-click installer bundling the Python runtime (no user venv) | 5d | D1 |
| D3 | First-run onboarding: provider key, workspace pick, profile choice | 3d | B3 |
| D4 | Beginner profile UX: goal → plan → one approval → result + cost | 4d | D3, A5 |
| D5 | Crash/error reporting, opt-in, local buffer | 2d | A4 |
| D6 | Update channel + version compatibility check for the bridge protocol | 2d | D1 |
| D7 | Long-session stability + memory ceiling (repo admits 937 MB checkpoint DB, no retention) | 3d | — |
| D8 | Fix open desktop bugs: pane paint on light theme, Ctrl/Cmd+L unproven | 2d | — |

**Exit criteria:** a non-technical tester installs from a downloaded file, builds one small app, and reads
their cost, without opening a terminal.

---

## 6. P2 — Public deployment and community launch (weeks 6–10)

| ID | Task | Effort | Depends on |
| --- | --- | --- | --- |
| E1 | Landing page + docs site (positioning from `02-PRODUCT-STRATEGY.md`) | 4d | D2 |
| E2 | Reproducible benchmark harness + published results (context engine vs naive baseline) | 5d | A1 |
| E3 | Demo assets: 3 real tasks recorded, unedited, with cost on screen | 3d | A1–A5 |
| E4 | Feedback loop: in-app "report task" with receipt attached | 2d | A5 |
| E5 | Community launch sequence (Show HN, r/LocalLLaMA, AI/dev Discords, X) | 3d | E1–E3 |
| E6 | Public roadmap + issue templates | 1d | C3 |

**Exit criteria:** 300 installs, 30 completed real tasks reported by users, 10 interviews booked.

---

## 7. P3 — Monetisation (weeks 9–16)

| ID | Task | Effort | Depends on |
| --- | --- | --- | --- |
| F1 | **P3-lite:** Stripe Payment Link + signed licence file, Pro BYOK tier | 2d | D2 |
| F2 | Minimal auth (persistent key, sessions survive restart) | 5d | — |
| F3 | Entitlement enforcement (feature gates, seat count) | 3d | F2 |
| F4 | Billing portal + invoices; replace `BillingState` stub | 5d | F2 |
| F5 | Usage & cost dashboard for users (Deliverable 5) | 4d | A5, E4 |
| F6 | Team policy file + shared usage roll-up | 4d | B3 |

**Exit criteria:** 20 paying Pro users; churn measured; cost per successful task published per release.

---

## 8. P4 — Enterprise readiness (Q3 2027+)

Signed + reproducible builds (from D1) → admin policy file → audit export (SIEM) → SSO/SCIM → egress
control/DLP → support SLA. Each gated on a named paying design partner. **Do not start before P3 revenue exists.**

---

## 9. Cross-cutting costs that must be budgeted, not discovered

| Item | Ongoing cost |
| --- | --- |
| Upstream Code OSS rebase | ~2 days per upstream release; 18,154 vendored files, 5 patched sources, hash-receipted manifest |
| Windows sandbox maintenance | AppContainer behaviour differs by Windows build; quarterly retest |
| Provider drift | 8 provider branches; every API change is a support ticket |
| Test suite runtime | 4,986 tests; needs tiers (fast / nightly) or CI time becomes the bottleneck |

---

## 10. Sequence summary

```
Week 1  ─ P0-C truth gate (C1–C3)        ─ parallel ─ P0-A (A1–A3)
Week 2  ─ P0-A finish (A4–A5) + P0-B (B1–B2)
Week 3  ─ P0-B finish (B3–B4) → tag v0.9 "real task works"
Week 4–6 ─ P1 (D1–D8) → tag v1.0 "installable"
Week 6–10 ─ P2 (E1–E6) → public launch
Week 9  ─ P3-lite (F1) starts taking money
Week 10–16 ─ P3 (F2–F6) → tag v1.1 "paid"
2027 Q3+ ─ P4
```

**Hard rule:** no public launch before D1/D2. Shipping an unsigned, terminal-requiring build to a
developer community burns the one first impression you get.
