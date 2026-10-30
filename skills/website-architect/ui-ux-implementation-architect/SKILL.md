---
name: ui-ux-implementation-architect
description: Architect-level direction for turning a design into working UI — the handoff contract, component ownership versus screen-level layout, interaction and state conventions, design QA gates, and the review habits that keep an implementation faithful without frozen pixels. Use before any specific UI implementation skill.
license: MIT
compatibility: Framework-agnostic; any design tool (Figma) and frontend stack
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/ui-ux-implementation-architect
  crusor-origin: original
  crusor-sources: "design systems practice; w3.org/WAI/ARIA/apg; nngroup.com/articles (interaction patterns)"
  crusor-triggers: "design handoff, implement design, figma to code, pixel perfect, ui implementation, design qa"
  crusor-verified-on: "2026-10-30"
---

# UI/UX Implementation Architect

Implementation is **translation under constraints**: the design says what it should
feel like, the code says what it can guarantee. The architect owns the contract
between them.

## When to use

- Translating a design into an implementation contract.
- Deciding ownership between design and engineering for fidelity.
- Reviewing drift between the design source and the shipped UI.

## When NOT to use

- Choosing the visual direction itself — that is `frontend-development-architect`.
- Component internals.

## Leaf map

| Need | Skill |
|---|---|
| what the design must supply before code starts | `design-handoff-architect` |
| how components, tokens and variants stay consistent | `design-system-ops-architect` |
| what happens on click, hover, focus, empty, error | `interaction-patterns-architect` |
| words inside the UI | `content-microcopy-architect` |

## Decision 1 — The handoff contract

- A screen is implementable when it specifies: states (default/hover/focus/
  active/disabled/loading/empty/error), responsive behaviour, content limits,
  and data edge cases.
- Values arrive as **tokens**, not raw hex/px. If a design uses a new value, that
  is a token decision, made once.
- Components are named in the design system vocabulary; a one-off shape on a
  screen is either a new component or a mistake.
- "Pixel perfect" is not the goal: **structural fidelity + token conformance**
  is. Pixels shift with fonts, zoom and locale.

## Decision 2 — Ownership

| Layer | Owns |
|---|---|
| design system | primitives, tokens, variants, motion scale |
| feature | composition, layout, data wiring |
| page | arrangement, empty/error/loading orchestration |

- A feature never re-styles a primitive; it passes variants.
- Spacing belongs to the parent container, not the component itself — this is
  what prevents margin spaghetti as screens compose.
- Screens assemble components; they do not define new visual language.

## Decision 3 — State completeness

Every data-driven surface defines all of:

```
loading (skeleton, not spinner-on-blank) · empty (guidance + next action)
error (recoverable, with retry) · partial (some data failed)
success · disabled/read-only
```

- An implementation that only handles success is half-built.
- Empty states are content decisions, made once per surface.
- Optimistic UI needs a visible revert path.

## Decision 4 — Fidelity review

- Review against the design in the browser at real breakpoints, with real
  content lengths (long names, 0 items, 500 items).
- Diff at token level: spacing, type scale, colour roles — not individual pixels.
- Accessibility is part of fidelity (see `accessibility-architect`); a beautiful
  screen you cannot tab through is not done.
- Sign-off is a checklist, not a vibe.

## Decision 5 — Keeping it honest over time

- Design changes flow through the system: token → component → screen. A change
  made only on one screen is drift.
- Every component documents its states in the catalogue (Storybook or
  equivalent) — the catalogue is the contract.
- Visual regressions get caught by screenshot tests on the catalogue, not by
  eyeballing.

## Failure modes at scale

- Screens built with bespoke spacing because tokens were "close enough".
- Three slightly different card components, none of them the design system's.
- Empty and error states designed after launch, by an engineer, in production.
- Design updates shipped to Figma and never to code (or the reverse).
- Fidelity reviews done from a screenshot instead of a browser.

## Verification receipts

1. Screen checklist: all states implemented, including empty/error/loading.
2. Token conformance scan: no raw colours or arbitrary spacing in feature code.
3. Catalogue updated with any new variant; screenshot test passing.
4. Browser review at 3 breakpoints with long/short/empty data.
5. Accessibility pass on the same screens, same release.
