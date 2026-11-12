# Handoff — Engineering Manager, PRD-001 (2026-11-12)

**Status:** handoff prepared, **implementation not authorised**
**Branch:** `docs/engineering-handoff-prd-001`
**Base:** `origin/main` @ `8fa4e240` (contains audit baseline `fb5bd528`; the two extra commits are merge
commits, tree unchanged)
**Condition of record:** `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` (F-01…F-15)
**Product artifacts:** `pm/` (TPM deliverables) and `pm/em/` (this handoff)

> This file is additive. It does **not** replace `CURRENT_STATE.md`, `DECISIONS.md`, `ROADMAP.md` or
> `AGENTS.md`, and it does not supersede the audit. Those four files carry pre-existing uncommitted
> modifications on the founder's machine and could not be updated without bundling 84 unrelated changes
> (see "Blockers"). When that working tree is dispositioned, append the promotion block at the end of this
> file into `CURRENT_STATE.md` and add the ADR entries to `DECISIONS.md`.

---

## 1. What was approved (founder decisions D-003…D-014)

| ID | Decision |
| --- | --- |
| D-003 | Segments: non-technical / vibe coders / AI users primary long-term; developers and AI power users now; enterprise an additional market |
| D-004 | Milestone: a real deployed, usable product; community showcase; feedback; then paid |
| D-005 | Solo build; 2-day core-agent target; revenue 3–6 months; track monthly spend, API/infra cost, agent performance, cost per successful task |
| D-006 | All three workflows in scope: greenfield, bug fix, refactor/migration |
| D-007 | Competitive ambition on measurable dimensions (OpenCode, Codex, Cursor, Windsurf, Claude Code, Lovable, Bolt, v0) |
| D-008 | The VS Code OSS fork is permanent; preserve editor control and native integrations |
| D-009 | Hybrid configurable autonomy; safe ops autonomous, sensitive ops approved |
| D-010 | The 2026-11-12 audit is the baseline; critical findings re-verified against current code before implementation |
| D-011 | `linkedin-app`, `showcase`, `apps/personal_finance` are not product components; no removal without dependency check and approval |
| D-012 | **Builder-first** for the initial release; non-technical remains the long-term vision; guided onboarding is a later milestone |
| D-013 | **Option A**: reuse the existing tool loop for the engineering agent. Genuine repo exploration, reads, edits, terminal, tests, permission enforcement, verification. No unsafe shortcuts; document limitations |
| D-014 | **Launch gate**: no public self-service executable before a signed installer exists. Demos and private testing allowed; a demo is not a release |

Full text and rejected proposals: `pm/DECISION-LOG.md`.

## 2. PRD-001 status

`pm/08-PRD-001-TOOL-BACKED-ENGINEERING-LOOP.md` — **rev 1.1, awaiting founder sign-off.**
41 functional requirements, 12 non-functional, 14 Given/When/Then acceptance criteria, 12 security
requirements, 6 AI-behaviour rows with pass rules, 21 tickets, 5 Technical Lead decision requests.

Rev 1.1 resolutions (D-016): declared `crusor.test_command`; no implicit auto-approval; checkpoint retention
deferred; two profiles ship (Beginner/Developer) with Enterprise deferred; reference provider proposed as
`custom` (`velona.in`) + `z-ai/glm-5.3-flash`, **confirmation pending**.

## 3. Approved engineering scope

In: tool-loop routing for engineering tasks · plan-before-mutation · test-in-the-loop · evidence-based outcome
semantics · per-turn receipts + ledger · containment default-on with fail-closed · env scrubbing · egress denial ·
two autonomy profiles + visible indicator · enriched approval prompts · collection-error fix + CI gate.

Out: installer, signing, auto-update, guided onboarding, hosted inference, billing, multi-file refactors,
benchmark publication, enterprise profile, checkpoint retention, UI redesign.

## 4. Milestones and dependencies

```
M0 Day1 10:00  fixtures + baseline + TL-DR-1 recorded
M1 Day1 17:00  engineering task runs through tool loop with plan approval   ← GO/NO-GO
M2 Day2 11:00  containment default-on; T4 injection inert
M3 Day2 15:30  AC-1…AC-14 executed; evidence pack written
M4 Day2 17:00  acceptance review with founder
```

Critical path: T-01 → T-02 → T-03 → T-04 → T-19 → T-20 → T-21.
Safe parallel starts: T-06 (receipts), T-17 (collection errors), T-19 (fixtures).

## 5. Outstanding architectural decisions (do not guess)

| ID | Question | Blocks |
| --- | --- | --- |
| TL-DR-1 | Where the engineering task enters the tool loop | T-02 |
| TL-DR-2 | How the observability shadow is resolved | T-06, T-07 |
| TL-DR-3 | Sandbox default switch + behaviour on unsupported Windows builds | T-10, T-12 |
| TL-DR-4 | Receipt storage engine | T-07, T-08 |
| TL-DR-5 | Whether DAG heuristic verifiers survive | T-05 |

Details and recommendations: `pm/em/12-TECHNICAL-DECISION-REQUESTS.md`. Conservative defaults apply until
each is recorded. One ADR per decision under `docs/adr/` once decided.

## 6. Security constraints (non-negotiable)

Containment on by default, fail closed · child processes never inherit provider keys · no write outside the
workspace without a grant · HMAC-bound single-use approval tokens · repository content is data, injected
instructions never execute · `verified` requires an executed check · the agent cannot edit its own permission
config. If a fix requires breaking one of these, the milestone is reduced instead.

## 7. Current audit baseline and re-verified findings

Baseline `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md`. Re-verified against code at `fb5bd528` on 2026-11-12:

| Finding | Re-verification result |
| --- | --- |
| F-01 engineering path has no tools | **CONFIRMED** — `git grep 'bind_tools\|read_file\|search_code' -- src/orchestration` returns nothing |
| F-02 collection errors / CI never runs suite | **CONFIRMED** — 4,986 collected, 3 errors; full-suite workflow sits in `ci/`, outside `.github/workflows` |
| F-03 unsandboxed exec, env inherited | **CONFIRMED** — `terminal_tools.py:1093` defaults `0`; tests only set `1` |
| F-06 turn receipts dead | **CONFIRMED** — `ImportError: cannot import name 'record_turn_receipt' from 'src.observability'` |
| F-04 `workspace_session` default | Confirmed at `bridge/__main__.py:1697-1709`; addressed by FR-25 |

## 8. Blockers (all block implementation, none block approval)

1. **B-1 dirty working tree** — 273 entries (84 modified tracked, 189 untracked), including `AGENTS.md`,
   `docs/CURRENT_STATE.md`, `docs/DECISIONS.md`, `docs/ROADMAP.md`, `docs/handoffs/LATEST_HANDOFF.md`, and
   product code under `src/graphs/`, `src/orchestration/`, `src/llm/`, `src/workspace/`. Implementation must be
   cut from `origin/main`; the tree must be dispositioned first (ROADMAP N-2).
2. **B-2 five TL decisions** — see §5.
3. **B-3 provider credit unverified** — repo evidence records a ₹0.00 wallet at one point.
4. **B-4 fixtures T1–T5 not created.**

## 9. How to consume this handoff (read order)

1. `pm/em/14-PRD-001-APPROVAL-PACKET.md` — one page, what is being approved.
2. `pm/08-PRD-001-…md` rev 1.1 — the contract.
3. `pm/em/09-ENGINEERING-EXECUTION-PLAN.md` — workstreams, ownership, Day-1 gate.
4. `pm/em/10-TASK-BREAKDOWN.md` — 21 tickets.
5. `pm/em/11-QA-AND-SECURITY-GATES.md` — gates and release checklist.
6. `pm/em/13-RISK-REGISTER.md` — open risks, R-02 capacity first.

## 10. Do not confuse with implemented functionality

Nothing in `pm/` is implemented. The engineering path still has no tool bindings at `fb5bd528`. Receipts are
still broken. Containment is still off by default. This handoff authorises nothing until the founder signs
PRD-001 rev 1.1 and the five TL decisions are recorded.

---

## Revision — founder review (2026-11-12, same day)

- PRD-001 corrected to **rev 1.1**: T-06/TL-DR-2 contradiction removed (T-06 blocked until TL-DR-2 signed);
  autonomy profiles fixed to **Beginner + Developer only**; F-01 wording corrected (Phase 2A read-only
  discovery exists; generation binds no read/search/list/test tools; shell tools hard-blocked by
  `_GRAPH_MUTATION_BLOCKED`); test count 4,968–4,986 with 3 collection errors.
- Five Technical Lead recommendations recorded **as RECOMMENDED, not Accepted**: A1, B1, C1, D1, E1
  (`pm/em/15-TECHNICAL-DECISION-REGISTER.md`).
- Reference provider verified without exposing credentials: `custom` / `velona.in` / `z-ai/glm-5.3-flash`;
  2-token probe answered `READY` in 8.7 s. Exact balance UNKNOWN (no documented endpoint).
- Dirty-tree inventory completed: 273 entries, +10,453/−969 lines. **The audit baseline
  `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` is untracked**, and modified orchestrator code depends on untracked
  sibling modules. Disposition proposal R1–R5 in `pm/em/16-DIRTY-TREE-DISPOSITION.md`; nothing was run.
- Implementation still **not authorised**.

## Promotion block (append to `docs/CURRENT_STATE.md` once the working tree is dispositioned)

```markdown
### 2026-11-12 — Engineering handoff for PRD-001

- Product track: `pm/` (strategy, competitive benchmark, roadmap, milestone, metrics, PRD-001 rev 1.1).
- Engineering handoff: `pm/em/` (21 tickets, 6 workstreams, Day-1 Go/No-Go, QA/security gates, 5 TL decisions).
- Branch: `docs/engineering-handoff-prd-001` from `origin/main` @ `8fa4e240`.
- Founder decisions D-003…D-014 recorded in `pm/DECISION-LOG.md`; PRD-001 rev 1.1 awaiting sign-off.
- Implementation NOT started. F-01/F-02/F-03/F-06 re-verified and still open.
- Blockers: 273-entry dirty tree, 5 TL decisions, provider credit, fixtures.
```
