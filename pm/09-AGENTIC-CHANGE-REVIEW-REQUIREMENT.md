# Product Requirement — Agentic Change Review

Status: **APPROVED DIRECTION (founder, 2026-11-12)** · Not scheduled · Owner: TPM/EM
Related: PRD-001 rev 1.2 (FR-13…FR-17, AC-4, AC-6), commit `c2a36e32` (inline preview restored)

---

## 1. Why

Crusor's product claim is that the user can trust an agent with a real repository. Trust is not a message in a
transcript; it is the ability to **see, judge and control** what the agent proposes before it touches the code.
The approval dock today shows the proposed diff inline (restored 2026-11-12) and offers a native full-diff
review. That covers inspection, but not the rest of the interaction a modern agentic editor is expected to
provide.

This document records the target experience so it is specified once, rather than discovered piecemeal.

## 2. Target experience

| # | Requirement | Today |
| --- | --- | --- |
| CR-1 | The agent proposes changes; nothing is applied before the user can inspect them | **Yes** — approval gate + mutation broker |
| CR-2 | The user can inspect the proposed change in the approval surface itself | **Yes** — inline preview restored (`crusorai-approval-diff-preview`) |
| CR-3 | The user can open the full native diff editor for complete review | **Yes** — "Review change" → `host.openDiff` |
| CR-4 | The user can accept or reject the pending change | **Yes** — Allow once / Allow always / Deny |
| CR-5 | The user can review changes **per file** when a task touched several | **No** — single approval per tool call |
| CR-6 | The user can act on an **individual change** where the architecture supports it | **No** |
| CR-7 | **Accept all / Reject all** are available when appropriate | **No** |
| CR-8 | The user can give feedback and request a revision without leaving the flow | **Partial** — chat exists, no revision affordance on the pending change |
| CR-9 | Security-sensitive operations keep mandatory approval regardless of any bulk action | **Yes** — must be preserved by any future work |

## 3. Non-negotiable invariants

1. **Display never approves.** Rendering a diff must never mutate, apply, or grant anything.
2. Approval tokens stay HMAC-bound, single-use, and bound to session/request/command/workspace.
3. Path containment and the mutation broker remain the only write path.
4. Bulk actions (accept all) must not widen scope: secret paths, git-ignored files, outside-workspace writes,
   shell and network actions keep their own gates.
5. A rejected change leaves the workspace byte-identical.

## 4. Scope boundary for the current work

T-18 restored CR-2 and preserved CR-1/CR-3/CR-4. **CR-5…CR-8 are not part of T-18** and must not be
implemented inside a CI ticket. They need their own specification (user stories, acceptance criteria,
edge cases) and their own engineering ticket after T-07.

## 5. Suggested next ticket (not started)

**T-CHANGE-REVIEW** — file-level review list, per-file accept/reject, accept-all/reject-all with the
invariants above, and a "request revision" affordance that returns control to the agent without applying the
pending change.

Dependencies: T-07 receipts (so a task's changes are attributable to one task id), and a decision on how the
bridge represents multi-file pending changes (protocol v2 additive fields).

Open questions for the founder:
- Should accept-all be allowed for writes outside the workspace? (Recommendation: no.)
- Should a revision request keep the same approval token or mint a new one? (Recommendation: new token.)
- Is file-level granularity required before the first public release, or after? (Recommendation: after T-07.)
