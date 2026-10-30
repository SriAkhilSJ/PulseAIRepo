---
name: tailwind-architect
description: Architect-level Tailwind guidance — token wiring from design tokens into the theme, component-layer boundaries, when utilities are wrong, dark mode and theming strategy, and the class-explosion failure modes that make utility CSS unmaintainable. Use when setting up or auditing a Tailwind codebase.
license: MIT
compatibility: Tailwind CSS 3.4+/4.x with a token source
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/tailwind-architect
  crusor-origin: original
  crusor-sources: "tailwindcss.com/docs; tailwindcss.com/blog/tailwindcss-v4"
  crusor-triggers: "tailwind, tailwindcss, utility css, tailwind theme, design tokens, utility classes, tailwind config, design tokens css"
  crusor-verified-on: "2026-10-30"
---

# Tailwind Architect

Tailwind is a **token delivery mechanism**, not a styling philosophy. If the
theme is arbitrary and the components are long class strings, you have CSS with
extra steps.

## When to use

- A design system exists or is being defined and must reach the codebase.
- A component library needs consistent spacing/colour/type without a CSS-in-JS
  runtime.
- Replacing ad-hoc CSS with a constrained scale.

## When NOT to use

- Content-heavy documents where semantic CSS is the better abstraction.
- A design system with no tokens — fix the tokens first.

## Decision 1 — Tokens are the source of truth

- `tailwind.config` (or `@theme` in v4) maps **semantic** tokens to utilities:
  `bg-surface`, `text-muted`, `border-subtle` — not `bg-gray-100`.
- Raw palette values are allowed only in components that are themselves the
  system (Button variants), never in feature code.
- Light/dark is a token swap (CSS variables), not `dark:` scattered through
  every component. `dark:` is for exceptions.
- Spacing/radius/shadow scales come from the token set; new arbitrary values
  (`p-[13px]`) are a design decision that must go back into the tokens.

## Decision 2 — Where utilities stop

| Layer | Owns |
|---|---|
| tokens | values |
| primitives (Button, Input, Card) | variant API + class composition |
| features | composition and layout only |

- A feature file with 40 classes is a primitive that hasn't been extracted.
- Variants live in `cva`/maps inside the primitive, not in call sites.
- Conditional class merging goes through one helper (`cn()`), never scattered
  template strings.

## Decision 3 — Responsiveness and layout

- Mobile-first breakpoints aligned to real layout shifts, not device names.
- Container queries for component-level responsiveness (cards, panels).
- Grid/flex utilities define layout; components do not carry their own margins
  (spacing belongs to the parent — the "no external margin" rule).

## Decision 4 — Build integration

- Content paths explicit; no dynamic class construction (`bg-${color}-500`) —
  it defeats extraction. Use a safelist or a variant map instead.
- CSS variables for theme values that must change at runtime (user theme).
- Purge in production, verified by size budget in CI.

## Failure modes at scale

- Every component re-inventing spacing because the tokens are too coarse.
- `dark:` on 300 elements → theme changes are a refactor.
- Arbitrary values everywhere → the design system no longer constrains anything.
- Class strings duplicated across features → one visual change, 40 edits.

## Verification receipts

1. Grep audit: no raw palette utilities in feature files.
2. `bg-${` / dynamic class construction: zero occurrences.
3. Production CSS size within budget after purge.
4. Dark/light switch verified on 3 representative pages.
5. A new feature can be built without adding a single arbitrary value.
