---
name: forms-architect
description: Architect-level form architecture — where form state lives, one validation schema shared by client and server, error mapping and focus behaviour, multi-step and draft persistence, submission idempotency, and the accessibility contract every field owes. Use when building or auditing forms.
license: MIT
compatibility: Framework-agnostic; schema validation (zod/valibot/yup)
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/forms-architect
  crusor-origin: original
  crusor-sources: "developer.mozilla.org/Forms; html.spec.whatwg.org/form-control-infrastructure; zod.dev"
  crusor-triggers: "forms, form validation, form state, react hook form, zod schema, multi-step form, input validation, submit"
  crusor-verified-on: "2026-10-30"
---

# Forms Architect

A form is a **contract between a schema, a UI, and a server**. Most form bugs are
that contract being written three times in three places.

## When to use

- Any form with more than two fields, validation, or a server round-trip.
- Forms that lose data, double-submit, or show errors in the wrong place.
- Multi-step flows, drafts, and wizards.

## When NOT to use

- A single search box — plain input plus URL state is enough.

## Decision 1 — One schema, two enforcers

- The validation schema (zod/valibot) is the single definition; the client uses
  it for UX, the server uses it for truth.
- Server is authoritative; client validation is a courtesy that never replaces
  it.
- Schema errors map to field paths the UI already knows — no string matching.
- Cross-field rules (password confirm, date ranges) live in the schema, not in
  handlers.

## Decision 2 — State ownership

| State | Home |
|---|---|
| field values, dirty/touched | form library (react-hook-form / conform / native) |
| server errors | returned from submit, mapped into the same field errors |
| draft persistence | localStorage/session, versioned and expiring |
| URL-carried steps | route params for multi-step flows |

- Avoid a global store for form state; it outlives the form and leaks between
  records.
- Reset semantics are explicit: after success, after route change, after
  "start over".

## Decision 3 — Errors are UI

- Validate on blur and on submit; re-validate on change only after the first
  error (no shouting while typing).
- Errors appear next to the field, are announced (`aria-live`, `aria-invalid`,
  `aria-describedby`), and move focus to the first invalid field on submit.
- One error message per field, in the user's language, actionable.
- Submit-level errors (network, 409 conflict) appear at the top with a link to
  the offending field.

## Decision 4 — Submission

- Disable-and-label the submit button while in flight; never allow double
  submit.
- Idempotency key on create/charge operations; retries must be safe.
- Success, partial success, and failure are three distinct states with distinct
  UI.
- Unsaved-changes guard before navigation for long forms.

## Decision 5 — Multi-step and drafts

- Each step validates its own slice; the whole form validates at the end.
- Progress is recoverable: refresh mid-flow returns to the same step.
- Back navigation never loses entered data.
- Drafts expire and are never silently merged across accounts.

## Failure modes at scale

- Validation duplicated in the client and server, drifting until one accepts
  what the other rejects.
- Errors rendered as a toast only — the user cannot tell which field.
- Form state in a global store: opening the same form for another record shows
  the previous record's data.
- Double submission creating duplicate orders.
- Multi-step forms that lose everything on refresh.

## Verification receipts

1. Schema shared between client and server (one import, not two copies).
2. Submit-invalid test: focus lands on the first error; message announced.
3. Double-submit test: one request, disabled state visible.
4. Refresh mid-flow: same step, same data.
5. Server-error mapping test: 422 field errors land on the right fields.
