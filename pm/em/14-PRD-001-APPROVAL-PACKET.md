# PRD-001 Approval Packet — Founder Decision Sheet

One page. Read this before the PRD. Everything here traces to `08-PRD-001-TOOL-BACKED-ENGINEERING-LOOP.md` rev 1.1.

---

## 1. What you are approving

Make the **existing tool loop** authoritative for engineering execution, with receipts, default-on containment
and two autonomy profiles. 41 functional requirements, 41 traced to code or the Nov-12 audit. Scope unchanged
from rev 1.0 except the five resolutions below.

**You are not approving:** a release, an installer, a public download, enterprise features, or a benchmark claim.

---

## 2. The five decisions, resolved as proposed

| # | Decision | What it means concretely | Consequence if reversed |
| --- | --- | --- | --- |
| 1 | **Declared `crusor.test_command`** | Test command comes from an explicit field; inference only as a labelled fallback | Silent "green" on a command the agent guessed; AC-2 becomes unfalsifiable |
| 2 | **No implicit auto-approval** | Default profile asks for every mutation, shell and network action. Developer autonomy is an explicit, visible opt-in and never bypasses the sandbox | F-04 persists: low-risk writes auto-approve and the product's safety claim is false |
| 3 | **Retention deferred** | No user data deleted; the 937 MB dev DB is not shipped or committed; retention designed in P1 | Two-day scope grows by ~2 days and risks data loss on a live machine |
| 4 | **Reference provider proposed** | `custom` (OpenAI-compatible, `velona.in`) + `z-ai/glm-5.3-flash`; aux `cheap`/`qwen/qwen3.7-flash`. Only configured key set; matches the repo's own live evidence | Every published number becomes non-reproducible |
| 5 | **Enterprise profile deferred** | Beginner + Developer ship; schema stays extensible so Enterprise needs no migration | Two-day scope grows; enterprise has no buyer yet |

**Decision needed:** confirm #4 (provider) and confirm the wallet has credit. #1, #2, #3, #5 are already
reflected in the PRD; say so if you want any reversed.

---

## 3. Unresolved blockers

| # | Blocker | Owner | Effect |
| --- | --- | --- | --- |
| B-1 | 273-entry dirty working tree including all memory files | Founder | Memory pointer files cannot be committed; implementation must start from `origin/main` (R-03) |
| B-2 | Five Technical Lead decisions (TL-DR-1…5) | Tech Lead / Founder | T-02, T-05, T-06, T-07, T-10 cannot start without them; conservative defaults apply until decided |
| B-3 | Provider credit unverified | Founder | No live evidence run possible |
| B-4 | Fixtures T1–T5 not yet created | QA agent | Acceptance matrix cannot run |

None of these blocks **approval**. All four block **implementation**.

---

## 4. Security invariants — not negotiable, regardless of deadline

1. Containment on by default; failure blocks the task, never silently degrades.
2. Child processes never inherit provider keys.
3. No write outside the workspace without an explicit grant.
4. Approval tokens stay HMAC-bound and single-use.
5. Repository content is data; injected instructions never execute.
6. `verified` requires an executed check; otherwise the product says `unverified`.
7. The agent cannot edit its own permission configuration.

If a fix requires breaking any of these, the milestone is reduced instead. That is not a preference — it is
the product's only defensible claim.

---

## 5. Two-day acceptance criteria (summary)

| Criterion | Bar |
| --- | --- |
| T1–T3 tasks | ≥2/3 first attempt, 3/3 with ≤2 interventions |
| Test execution | Command run in 3/3; failure output changes the next edit |
| Unapproved mutations | 0, including T4 |
| Receipts | 100% of runs, all fields; cost within ±10% of provider dashboard |
| False success | 0; T5 returns `blocked` |
| Collection errors | 0; CI red-blocks a red suite |
| Chat regression | 0 new failures |

Raw counts per slice. No percentage claims from five cases.

---

## 6. Changes made to PRD-001 in rev 1.1

| Section | Change |
| --- | --- |
| FR-19 | Declared test command with documented override |
| FR-23 | Two profiles ship; Enterprise deferred, schema extensible |
| FR-25 | No implicit auto-approval; explicit visible opt-in; sandbox never bypassed |
| US-8, UX-1 | "enterprise" removed from the profile picker |
| NFR-6 | Retention deferred; no user-data deletion; DB not shipped |
| Open Questions | Five resolved (four adopted, one proposed); two new owner-items |
| Revision history | v1.1 entry |

Scope, acceptance criteria and security requirements are otherwise unchanged.

---

## 7. What approval authorises

- Cut implementation branches and start tickets **T-06, T-17, T-19** (the three that have no unresolved
  dependency).
- Start T-02 only after TL-DR-1 is recorded.

## What approval does not authorise

- Any push to `main`, any public binary, any public claim of production readiness.
- Any weakening of §4 to fit the calendar.
- Publishing benchmark or cost numbers before the evidence pack exists.

**Sign-off line:** `Approved: PRD-001 rev 1.1 — ______ (founder) — date ______`
