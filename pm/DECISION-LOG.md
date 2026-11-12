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

## Rejected proposals

| Date | Proposal | Why rejected | Revisit when |
| --- | --- | --- | --- |
| 2026-11-12 | Vendor PM-Skills into `PulseAIRepo/skills/` | Duplicates Apache-2.0 third-party content in product git history; breaks upstream updates; product repo already has its own 26-skill library with different IDs | If the team wants a pinned, reviewed subset under version control |
| 2026-11-12 | Install `pm-skills-mcp` instead of file-based skills | Upstream maintenance mode; catalog frozen at 40 skills, missing sprint families | Never, per upstream recommendation |

## Change log

| Date | Change | Reason |
| --- | --- | --- |
| 2026-11-12 | Log created | Product track started |
