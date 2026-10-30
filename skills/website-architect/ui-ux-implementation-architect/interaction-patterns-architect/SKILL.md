---
name: interaction-patterns-architect
description: Architect-level interaction design in code — choosing established patterns over invented ones, feedback and latency behaviour, destructive-action safeguards, navigation and overlay conventions, and the state model behind every interactive surface. Use when a screen has to behave, not just look.
license: MIT
compatibility: Framework-agnostic
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/ui-ux-implementation-architect/interaction-patterns-architect
  crusor-origin: original
  crusor-sources: "nngroup.com/articles (interaction patterns); w3.org/WAI/ARIA/apg; apple.com/design/human-interface-guidelines"
  crusor-triggers: "interaction design, ux patterns, modal, toast, confirmation dialog, destructive action, loading state, empty state"
  crusor-verified-on: "2026-10-30"
---

# Interaction Patterns Architect

Users do not learn your interface; they **recognise patterns**. Invent a pattern
and you spend the user's attention on your invention instead of their task.

## When to use

- Designing a flow with overlays, destructive actions, async feedback, or forms.
- Users hesitate, double-submit, or miss confirmations.
- Choosing between a modal, a page, an inline edit, or a drawer.

## When NOT to use

- Visual style questions (see the branch's design skills).

## Decision 1 — Pick the established pattern

| Need | Pattern |
|---|---|
| short focused task, context preserved | modal dialog |
| long/complex task | its own page/route |
| secondary info, no commitment | drawer/side panel |
| quick edit of one field | inline edit with save/cancel |
| irreversible action | explicit confirm with the object named |
| background success | inline confirmation, not a toast alone |
| failure needing action | inline error with the fix, not a toast |

- Toasts are for non-blocking, ignorable information; they disappear, so they
  cannot carry decisions.
- Nested modals are a design bug — escalate to a page or a wizard.

## Decision 2 — Feedback and latency

| Latency | Response |
|---|---|
| < 100 ms | no indicator needed |
| 100–1000 ms | immediate pressed/loading state on the control |
| > 1 s | skeleton or progress with context |
| > 10 s | background it; tell the user they can leave |

- Show the optimistic result only when a revert path exists and is visible.
- Disable-on-submit plus a clear in-flight label; never silent double-submit.
- Skeletons match the final layout; spinners on blank areas teach nothing.

## Decision 3 — Destructive actions

- Name the object: "Delete 'Q3 report'?" — never "Are you sure?".
- Prefer undo over confirmation for reversible actions (soft delete + snackbar).
- Confirmation dialogs for irreversible actions only; repeated confirmations
  train users to click through.
- Bulk destructive actions state the count and offer a dry-run or summary.

## Decision 4 — Navigation and overlays

- Back/close always does the expected thing; `Esc` closes overlays; focus
  returns to the trigger.
- Deep links exist for anything a user might share or bookmark; state in the URL
  survives refresh.
- Unsaved-changes guard on navigation away from a dirty form.
- Scroll restoration and preserved filter state on back navigation.

## Decision 5 — The state model behind the screen

Every interactive surface names its states explicitly:

```
idle → submitting → success | error(retryable | terminal)
idle → loading → empty | list | error
```

- If a state is not in the model, it will appear as a bug in production.
- Errors say what happened and what to do next; they never expose internals.
- The same action keeps the same vocabulary everywhere (Save vs Update vs
  Submit — pick one).

## Failure modes at scale

- Toasts carrying errors that vanish before they are read.
- Confirmation dialogs on every action, so nobody reads them.
- Modal inside a modal inside a drawer.
- Optimistic updates with no visible failure path — data silently lost.
- Every screen inventing its own loading style.

## Verification receipts

1. State model written per interactive surface, all states designed.
2. Latency budget: skeleton/spinner thresholds implemented, not improvised.
3. Destructive-action audit: named object, undo or confirm, count for bulk.
4. Keyboard pass: `Esc`, focus return, deep link, refresh preservation.
5. Vocabulary audit across the product (one verb per action).
