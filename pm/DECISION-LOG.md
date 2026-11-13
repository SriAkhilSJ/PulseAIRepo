# Decision Log — Crusor AI IDE

Format: newest last. Every entry needs a date, the decision, who decided, and the evidence it rests on.
Nothing is recorded here until the founder approves it. Proposed items live in `OPEN-QUESTIONS.md`.

| Date | ID | Decision | Decider | Status | Basis |
| --- | --- | --- | --- | --- | --- |
| 2026-11-12 | D-000 | PM-Skills v2.35.0 installed via OpenCode git-clone + skill-source registration; not vendored into the product repo | Founder (instruction) | Adopted | `00-INSTALL-VERIFICATION.md` |
| 2026-11-12 | D-001 | Product assessment of record pins to `PulseAIRepo@fb5bd528`; repo docs are treated as claims, not facts, until re-verified | TPM | Adopted (supersedable) | `01-PRODUCT-ASSESSMENT.md` |
| 2026-11-12 | D-002 | No application code or repo memory is modified during discovery | Founder (instruction) | Adopted | — |
| 2026-11-12 | D-003 | Target segments: primary = non-technical/vibe coders and AI users; also developers/power users; enterprise as an additional commercial market | Founder | Adopted (sequencing challenge open — see Q-S1) | Interview 1 |
| 2026-11-12 | D-004 | Milestone: a real deployed, usable product; showcase in dev/AI communities; collect feedback; move toward paid | Founder | Adopted | Interview 2 |
| 2026-11-12 | D-005 | Solo build; core agent target = 2 days; revenue target = 3–6 months; track monthly spend, API/infra cost, agent performance, cost per successful task | Founder | Adopted | Interview 3 |
| 2026-11-12 | D-006 | All three workflows in scope: greenfield, bug fix in existing repos, refactor/migration | Founder | Adopted; sequencing recommendation in `04-ENGINEERING-ROADMAP.md` | Interview 4 |
| 2026-11-12 | D-007 | Competitive ambition: agent core that can outperform on measurable dimensions; study OpenCode, Codex, Cursor, Windsurf, Claude Code, Lovable, Bolt, v0 | Founder | Adopted; benchmark in `03-COMPETITIVE-BENCHMARK.md` | Interview 5 |
| 2026-11-12 | D-008 | Continue maintaining the VS Code OSS fork; preserve editor control and native integrations (fork is permanent, not transitional) | Founder | Adopted; cost budgeted in roadmap §9 | Interview 6 |
| 2026-11-12 | D-009 | Hybrid configurable autonomy; user-controlled permissions/approvals; safe ops autonomous, sensitive ops approved; beginner/developer/enterprise configurations | Founder | Adopted; spec in roadmap B3/B4 | Interview 7 |
| 2026-11-12 | D-010 | November 12 2026 audit (F-01…F-15) is the initial baseline; critical findings re-verified against current code before implementation | Founder | Adopted; re-verification already performed (F-01, F-02, F-03, F-06 confirmed) | Interview 8 |
| 2026-11-12 | D-011 | `linkedin-app`, `showcase`, `apps/personal_finance` are not intended product components; no deletion/archive without dependency check and approval | Founder | Adopted; dependency scan run, no product imports found — see `OPEN-QUESTIONS.md` Q-R2 | Interview 9 |
| 2026-11-12 | D-012 | Customer sequencing: **builder-first** for the initial release (AI-native builders, vibe coders, indie hackers, developers, AI power users). Non-technical remains the long-term primary vision and must not be repositioned; guided onboarding is a subsequent milestone | Founder | Adopted | Approval 1 |
| 2026-11-12 | D-013 | Engineering approach: **Option A** — reuse the existing tool loop for the engineering agent, with genuine repo exploration, file reads, editing, terminal, testing, permission enforcement and verification. No unsafe shortcuts to meet the deadline; document architectural limitations | Founder | Adopted | Approval 2 |
| 2026-11-12 | D-014 | Launch gate: **no public self-service executable distribution before a signed installer exists.** Community demos, recorded demos and controlled private testing may occur earlier; a demonstration is not a release | Founder | Adopted | Approval 3 |
| 2026-11-12 | D-015 | PRD-001 (Tool-Backed Engineering Loop with Receipts) submitted for approval | TPM | **Superseded by D-016 (rev 1.1)** | `08-PRD-001-TOOL-BACKED-ENGINEERING-LOOP.md` |
| 2026-11-12 | D-016 | PRD-001 rev 1.1: five open questions resolved as proposed defaults — declared `crusor.test_command`; no implicit auto-approval; checkpoint retention deferred; two profiles ship with Enterprise deferred; reference provider proposed as `custom`/`velona.in` + `z-ai/glm-5.3-flash` (confirmation pending) | Founder (proposed) + TPM/EM | **Adopted in PRD; provider confirmation pending** | PRD rev 1.1, `14-PRD-001-APPROVAL-PACKET.md` |
| 2026-11-12 | D-017 | Engineering Manager handoff prepared: 21 tickets across 6 workstreams, exclusive file ownership, Day-1 Go/No-Go, QA/security gates, 5 Technical Lead decision requests | EM | **Submitted; implementation not authorised** | `pm/em/09`…`14` |
| 2026-11-12 | D-018 | Founder review corrections applied: T-06/TL-DR-2 contradiction resolved (T-06 blocked until TL-DR-2 signed); autonomy profiles fixed to Beginner + Developer everywhere; PRD frontmatter set to version 1.1; F-01 wording corrected to "no tool bindings during generation (Phase 2A read-only discovery exists)"; test count stated as 4,968–4,986 | Founder (review) + EM | Adopted | PRD rev 1.1; `em/14` §2 |
| 2026-11-12 | D-019 | Five Technical Lead recommendations recorded: TL-DR-1=A1, TL-DR-2=B1, TL-DR-3=C1, TL-DR-4=D1, TL-DR-5=E1 | Founder (recommended) | **Superseded by D-021/D-022 (accepted; C1 corrected to C1′)** | `15-TECHNICAL-DECISION-REGISTER.md` |
| 2026-11-12 | D-020 | Reference provider verified: `custom` / `velona.in` / `z-ai/glm-5.3-flash`; config check clean; 2-token live probe answered `READY` in 8.7s (credit > 0). Exact balance remains UNKNOWN (no documented balance endpoint) | EM | Verified (balance unknown) | `14` §4 |
| 2026-11-12 | D-021 | Technical decisions accepted: TL-DR-1 = A1, TL-DR-2 = B1, TL-DR-4 = D1, TL-DR-5 = E1 | Founder | **ACCEPTED** | `15-TECHNICAL-DECISION-REGISTER.md` |
| 2026-11-12 | D-022 | TL-DR-3 corrected before acceptance: containment default-on and fail-closed; if sandbox init fails or the build is unsupported, **terminal execution is blocked** with a stated reason, non-terminal capability remains, and **no opt-out may permit an uncontained shell** (C1′). The earlier opt-out clause is prohibited | Founder | **ACCEPTED (corrected)** | PRD rev 1.2 FR-26/AC-11/SEC-1; T-10/T-12; SG-1/SG-9 |
| 2026-11-12 | D-023 | Dirty-tree approach (R1–R5) approved **with conditions**: preserve every entry; back up the full tree first (R0); separate worktree or safe equivalent; account for every entry; no delete/quarantine without content review; no merge to main without separate approval | Founder | **APPROVED WITH CONDITIONS** | `16-DIRTY-TREE-DISPOSITION.md` §0 |
| 2026-11-12 | D-024 | Reference provider approved as the single evidence configuration. Exact wallet balance remains unknown; **no expensive evidence runs until a spending limit is confirmed** | Founder | **APPROVED** | `14` §5 |
| 2026-11-12 | D-025 | PRD-001 product direction and technical scope approved; sandbox clarification incorporated as **rev 1.2**. Signature and the R0/R1–R4 go-aheads remain outstanding | Founder | **APPROVED (pending signature)** | `08-PRD-001-…md` rev 1.2 |

| 2026-11-12 | D-026 | Working-tree reconciliation executed on `wip/working-tree-2026-11-12`: R1 audit `40b02500`, R2 agent `fc511e67`, R3 desktop `2ec62a2c`, R4 memory/evidence `952dbd45`. 492 files committed; 39 entries deliberately left untracked (11 generated `req_*`, 28 private-runtime dirs); 1,220 Electron user-profile files excluded from git by policy and preserved in R0 | Founder (authorised) + EM | **DONE** | `docs/CURRENT_STATE.md`; R0 manifest |
| 2026-11-12 | D-027 | T-06 complete: observability module moved into the package as `receipts.py`, re-exported; F-06 fixed at the import layer | EM | **DONE-VERIFIED** (import OK; 4/4 tests) | commit `823aa7cf` + follow-up |
| 2026-11-12 | D-028 | T-17 part 1 complete: `deduplicate_streaming_usage` implemented; collection 5,012 tests / 0 errors (was 4,986 / 3). T-18 (CI gate) is the next unblocked ticket | EM | **DONE-VERIFIED** (22/22 modules, collection 0 errors) | commit `19682792` |

| 2026-11-12 | D-029 | **T-22 created** (next free ID) and resolved: the 7 pre-existing failures are two product regressions plus one security-relevant ordering bug, none caused by R2 (same 7 fail at `7e4bb7ad`). Fixed: turn resets no longer clobber `task_action`/`task_status`/`task_completed`; tool names are canonicalized before the mutation boundary; the alias `run terminal` is now denied instead of reaching a confirmation prompt | Founder (authorised) + EM | **DONE-VERIFIED** (73 passed, 7 skipped; regression guard added) | commit `242decbb` |
| 2026-11-12 | D-030 | Linux CI runtime qualification **not performed**: no WSL distribution and no Docker on this host. The 30-minute workflow timeout therefore remains unvalidated for Linux; Windows runtime (>40 min) must not be presented as Linux evidence | EM | **BLOCKED (environment)** | `AGENTS.md` §14 |

## Rejected proposals

| Date | Proposal | Why rejected | Revisit when |
| --- | --- | --- | --- |
| 2026-11-12 | Vendor PM-Skills into `PulseAIRepo/skills/` | Duplicates Apache-2.0 third-party content in product git history; breaks upstream updates; product repo already has its own 26-skill library with different IDs | If the team wants a pinned, reviewed subset under version control |
| 2026-11-12 | Install `pm-skills-mcp` instead of file-based skills | Upstream maintenance mode; catalog frozen at 40 skills, missing sprint families | Never, per upstream recommendation |

## Change log

| Date | Change | Reason |
| --- | --- | --- |
| 2026-11-12 | Log created | Product track started |
