---
name: design-system-ops-architect
description: Architect-level operation of a design system in code — token pipelines and versioning, component API and variant policy, the catalogue as the contract, adoption metrics, and the governance that stops a system from forking into three. Use when a component library must survive several teams.
license: MIT
compatibility: Any component library; Storybook or equivalent; token pipeline (Style Dictionary)
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/ui-ux-implementation-architect/design-system-ops-architect
  crusor-origin: original
  crusor-sources: "design-tokens.github.io/community-group; storybook.js.org/docs; component governance practice"
  crusor-triggers: "design system, component library, storybook, tokens pipeline, component api, component variants, style drift, design drift, inconsistent styles, adoption, governance"
  crusor-verified-on: "2026-10-30"
---

# Design System Ops Architect

A design system is **a product with users inside the company**. It survives on
adoption, versioning and a change process — not on how good the Button looks.

## When to use

- A component library serves more than one team or product.
- Screens are drifting: three card components, four button styles.
- Token changes need to ship without breaking consumers.

## When NOT to use

- A single-app project with one consumer — build components, skip the ops
  ceremony until there is a second consumer.

## Decision 1 — Token pipeline

```
design source → tokens (JSON) → build → CSS vars / TS types / platform outputs
```

- One source of truth; generated outputs are never hand-edited.
- Three tiers enforced: primitive → semantic → component. Features consume
  semantic tokens only.
- Token names are API: renaming is a breaking change with a migration note.
- Theming (light/dark/brand) is a token swap, not a second stylesheet.

## Decision 2 — Component API policy

| Rule | Why |
|---|---|
| variants over ad-hoc props | bounded surface |
| no `style`/`className` passthrough for layout | prevents per-screen restyling |
| slots/children for composition | feature code composes, never forks |
| explicit states in the API | loading/disabled/error designed once |
| one component per concept | avoids Card/CardAlt/CardV2 |

- A new prop is a contract addition: it needs a use case from at least two
  consumers, or it is a one-off.

## Decision 3 — The catalogue is the contract

- Every component appears in the catalogue with all states, at all breakpoints.
- Docs show usage and misuse side by side.
- Screenshot tests run on the catalogue, so visual regressions are caught once
  rather than per page.
- Accessibility notes accompany each component (roles, keyboard, announcements).

## Decision 4 — Versioning and release

- Semantic versioning for the package; breaking changes announced with a
  codemod or a migration guide.
- Deprecation before removal, with a usage count and a deadline.
- Consumers pin major versions; the system supports N-1 during migration.
- Release notes name the visual or behavioural change in one line.

## Decision 5 — Adoption and governance

- Measure adoption: percentage of screens using system components; count of
  local overrides (the drift metric).
- A contribution path exists: propose → review → build in the system (not in a
  screen).
- One owner (or a small group) with the authority to say no to bespoke variants.
- Quarterly audit: unused components, props with one usage, tokens with no
  consumers.

## Failure modes at scale

- Two design systems in one product ("old" and "new" components side by side
  forever).
- Token changes shipped as a patch, breaking every consumer silently.
- Catalogue with only the happy state; everyone learns the error state from
  production.
- Local overrides everywhere, so the system is a suggestion.
- Governance with no authority: every request becomes a new variant.

## Verification receipts

1. Token pipeline: generated artefacts only, no hand edits.
2. Component API review for the last three additions (two-consumer rule).
3. Catalogue coverage: states per component, screenshot tests green.
4. Adoption metric: system components vs local variants per product area.
5. Deprecation inventory with usage counts and dates.
