---
name: design-handoff-architect
description: Architect-level design handoff — what must be specified before implementation starts, tokens over raw values, responsive and content-limit contracts, state matrices, and the review loop that catches drift between design and code. Use when a design is about to become code.
license: MIT
compatibility: Figma (or equivalent) + any frontend stack
metadata:
  crusor-domain: website-architect
  crusor-path: ui-ux-implementation-architect/design-handoff-architect
  crusor-origin: original
  crusor-sources: "design systems practice; Figma dev mode docs; w3.org/WAI/ARIA/apg"
  crusor-triggers: "design handoff, figma, specs, design tokens, states matrix, responsive spec, design review"
  crusor-verified-on: "2026-10-30"
---

# Design Handoff Architect

A handoff is **a specification, not a screenshot**. If the implementer has to
invent behaviour, the design is unfinished.

## When to use

- A design is ready for implementation.
- Implementations repeatedly differ from the design in the same ways.
- Onboarding a designer or engineer to the system.

## When NOT to use

- Exploratory prototyping where the point is to discover the shape.

## Decision 1 — The specification checklist

Before implementation, each screen states:

1. **States** — default, hover, focus, active, disabled, loading, empty, error,
   partial.
2. **Breakpoints** — layout at each, including what collapses, hides, or
   reorders.
3. **Content limits** — min/max characters, truncation rules, wrapping, number
   formats.
4. **Data edge cases** — zero items, 500 items, missing image, long name.
5. **Tokens** — spacing, type, colour roles, radius, motion; no raw values.
6. **Interaction** — what each control does, including keyboard and focus order.

Missing any of these is a design gap, not an engineering judgement call.

## Decision 2 — Tokens are the interface

- Designs express values as tokens (`space-4`, `text-muted`, `radius-md`).
- A new value in a screen is a **token proposal**, reviewed once, added to the
  system, then used everywhere.
- Colour roles over hex: `surface`, `surface-raised`, `border-subtle`,
  `text-muted`, `danger`.
- Typography: named scale steps, not per-screen font sizes.

## Decision 3 — Responsive as a contract

- The design shows each breakpoint; the implementation may collapse to the
  nearest documented state, but not invent one.
- Stacking order, sticky elements and truncation are specified, not guessed.
- Touch targets ≥ 44×44 CSS px on touch layouts; hover-only affordances have a
  touch equivalent.

## Decision 4 — The review loop

- Review in the browser, with real data, at the documented breakpoints.
- Compare structurally: hierarchy, spacing rhythm, states — not a pixel diff of
  a screenshot.
- Discrepancies are triaged: design bug, token gap, implementation bug, or
  acceptable platform difference.
- Sign-off recorded per screen; "looks good" in chat is not a record.

## Decision 5 — Change after handoff

- Changes flow through the token/component layer first, then the screen.
- A late design change on one screen is either adopted system-wide or rejected —
  not silently local.
- Version the design file and link it in the PR description.

## Failure modes at scale

- Screens with only a default state; error and empty invented at runtime.
- Designers specifying 13px and 14px in the same product.
- Mobile layouts created by shrinking desktop rather than by design.
- Handoff via screenshots in a Slack thread.
- Implementation drift discovered at the next redesign.

## Verification receipts

1. Handoff checklist complete per screen (states, breakpoints, content limits).
2. Zero raw colour/spacing values in the feature diff.
3. Browser review at each breakpoint with long/empty data attached to the PR.
4. Discrepancy log with resolution per item.
5. Design file version linked from the change.
