# Open Questions — Crusor AI IDE

Updated 2026-11-12. Original interview questions are retained with the founder's answers so the reasoning
stays auditable.

## Answered by the founder

| # | Question | Answer | Recorded as |
| --- | --- | --- | --- |
| Q1 | Who is the first paying user? | Primary: non-technical / vibe coders / AI users. Also developers and AI power users. Enterprise as an additional commercial market. | D-003 |
| Q2 | Next milestone? | A real deployed, usable product; showcase in dev/AI communities; early users + feedback; move toward paid. | D-004 |
| Q3 | Runway / team / revenue timing? | Solo. Core agent working within 2 days. Revenue in 3–6 months. Track monthly spend, API/infra cost, agent performance, cost per successful task. | D-005 |
| Q4 | Which workflow must be flawless? | All three: greenfield, bug fix in existing repos, refactor/migration. | D-006 |
| Q5 | Fork permanent or transitional? | Permanent — continue maintaining the VS Code OSS fork and native integrations. | D-008 |
| Q6 | "Autonomous" or "supervised"? | Hybrid and configurable: user controls permissions and approval levels; safe ops autonomous; sensitive ops approved; beginner/developer/enterprise profiles. *(Historical answer. This milestone ships Beginner + Developer; Enterprise deferred — D-017.)* | D-009 |
| Q7 | Accept the Nov-12 audit as condition of record? | Yes — baseline for implementation, with critical findings re-verified against current code. | D-010 |
| Q8 | Own the `linkedin-app` / `showcase` / `personal_finance` artifacts? | Not intended product components. Do not delete/archive without dependency check and approval. | D-011 |

## Answered — strategic decisions (2026-11-12)

| # | Question | Answer | Recorded as |
| --- | --- | --- | --- |
| Q-S1 | Segment sequencing: non-technical first, or developer/builder first? | **Builder-first** approved. Long-term positioning stays non-technical; guided onboarding is a subsequent milestone. | D-012 |
| Q-S2 | Tool-gap approach: Option A or Option B? | **Option A** approved, with no unsafe shortcuts and architectural limitations documented. | D-013 |
| Q-S3 | Hard launch gate requiring a signed installer? | **Approved.** No public self-service executable before signing. Demos and private testing allowed; a demo is not a release. | D-014 |

## Resolved — PRD-001 rev 1.1 (proposed defaults, founder confirmation pending)

| # | Item | Resolution |
| --- | --- | --- |
| P1 | Test command discovery | Declared `crusor.test_command` + documented fixture overrides (FR-19) |
| P2 | `workspace_session` auto-approval | Removed as implicit default; explicit visible opt-in only; sandbox never bypassed (FR-25) |
| P3 | Checkpoint retention | Deferred; no user-data deletion; DB not shipped (NFR-6) |
| P4 | Reference provider | Proposed `custom` (`velona.in`) + `z-ai/glm-5.3-flash`; needs confirmation + credit check |
| P5 | Enterprise profile | Deferred; schema stays extensible (FR-23) |

## Open — founder confirmation

| # | Item | Status after review |
| --- | --- | --- |
| C1 | Confirm P4 reference provider and non-zero wallet credit | **CLOSED** — config + 2-token probe pass; balance UNKNOWN by design (D-020) |
| C2 | Disposition the 273-entry dirty working tree before implementation | **OPEN** — proposal R1–R5 in `em/16`; audit baseline is currently untracked |
| C3 | Record the five Technical Lead decisions (TL-DR-1…5) | **RECOMMENDED, awaiting sign-off** (D-019) |
| C4 | Sign PRD-001 rev 1.1 | **OPEN** — sign-off block in `em/14` §9 |

## Open — evidence gathering (owner: TPM)

| # | Item | Status |
| --- | --- | --- |
| Q-R1 | Confirm the remaining 2 collection errors fail for their stated reasons (observability confirmed) | Partially verified |
| Q-R2 | Full dependency confirmation before touching `linkedin-app` / `showcase` / `apps/personal_finance` | **Partial**: first 20 matches of a `git grep` across `.py/.yml/.toml/.json/.ts` show only self-references inside `apps/personal_finance`, a vendored VS Code Copilot test fixture, and `diagnostics/`+`docs/benchmarks/` JSON. No import from `src/` or the Crusor workbench contrib was observed — but this is not yet an exhaustive check. |
| Q-R3 | Whether the `canonical_runtime` flag is on by default in shipped builds | Not verified |
| Q-R4 | Benchmark design for context engine vs naive retrieval (task set, scoring, sample size) | Not started |
| Q-R5 | Whether any external user has ever installed Crusor | No evidence found; assume none |

## Explicitly not asked yet (deliberately deferred)

Pricing exactness, brand/renaming, jurisdiction/tax, open-source strategy for the agent core, hiring plan.
Each depends on Q-S1…Q-S3.
