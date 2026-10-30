---
name: content-microcopy-architect
description: Architect-level UI content — where strings live, voice and terminology consistency, error and empty-state copy as part of the interface, translation-ready authoring, and the content model a product needs before it multiplies screens. Use when the words in the interface matter as much as the pixels.
license: MIT
compatibility: Framework-agnostic; i18n catalogues (see i18n-architect)
metadata:
  crusor-domain: website-architect
  crusor-path: ui-ux-implementation-architect/content-microcopy-architect
  crusor-origin: original
  crusor-sources: "nngroup.com/articles (microcopy, error messages); gov.uk content design guidance"
  crusor-triggers: "microcopy, ux writing, interface copy, error messages, empty state copy, terminology, tone of voice"
  crusor-verified-on: "2026-10-30"
---

# Content & Microcopy Architect

Copy is **interface**. A button label is not decoration; it is the specification of
what pressing it does.

## When to use

- Writing labels, buttons, errors, empty states, confirmations.
- Terminology is inconsistent across screens (Save/Update/Submit).
- Copy is hard-coded and needs to become translatable.

## When NOT to use

- Marketing copy and long-form content, which have their own editing process.

## Decision 1 — Strings are data

- All UI strings live in a catalogue keyed by meaning (see `i18n-architect`).
- No concatenation: "{n} items" is one message with a plural rule, not
  `n + " items"`.
- Placeholder names are descriptive (`{fileName}`, not `{0}`).
- Content limits are part of the design spec: buttons truncate, headlines
  wrap — decide which.

## Decision 2 — Voice and terminology

- One verb per action, product-wide: pick "Delete" and never also use "Remove",
  "Discard", "Erase" for the same operation.
- A terminology list exists and is enforced in review (glossary in the repo).
- Second person, active, present tense: "We couldn't save your changes."
- No jargon the user did not introduce; no idioms that will not translate.

## Decision 3 — Errors as guidance

Every error answers three questions:

1. What happened, in the user's terms.
2. Why, if it is knowable and actionable.
3. What to do next.

- Never expose codes, stack traces, or internal identifiers as the message.
- Field errors sit next to the field and name the fix ("Enter a date after
  1 March"), not the failure ("Invalid input").
- Distinguish user error, system error, and permission error — the actions
  differ.

## Decision 4 — Empty and first-run states

- Empty is a design state with a purpose: explain the value, offer the first
  action, and — where useful — show an example.
- Distinguish "nothing yet" from "nothing matched your filter" from "no
  permission".
- Loading copy sets expectations for anything over a second.
- Confirmations name what changed ("Invite sent to ana@…"), not "Success!".

## Decision 5 — Translation-ready authoring

- Short sentences, no nested clauses; translation expands text 30–40%.
- No text inside images; no string splits across elements.
- Dates, numbers, currency via `Intl`, never pre-formatted in strings.
- Provide context to translators (screenshot + what the string is for).

## Failure modes at scale

- Three words for the same action, so users cannot predict outcomes.
- Errors like "Error 422" that tell the user nothing.
- Empty states that say "No data" and offer no next step.
- Button labels that change meaning after translation and no longer fit.
- Copy invented per screen by whoever implemented it last.

## Verification receipts

1. Terminology glossary in the repo, enforced on strings changed in the PR.
2. Error-copy checklist applied to every error path in the flow.
3. Empty state present and purposeful for every list/data surface.
4. String catalogue: no concatenation, no embedded HTML, placeholders named.
5. Pseudo-locale pass on the primary screens (overflow, truncation).
