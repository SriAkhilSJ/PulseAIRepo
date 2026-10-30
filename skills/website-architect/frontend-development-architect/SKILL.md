---
name: frontend-development-architect
description: Architect-level visual direction and design-system design for web frontends — choosing a defensible aesthetic, defining primitive/semantic/component tokens, a type scale, layout primitives, component API contracts, and the accessibility, motion and performance budgets the codebase is built against. Use when starting a UI, reviewing a design system, or when a page feels templated rather than intentional.
license: Apache-2.0
compatibility: Framework-agnostic (React, Vue, Angular, Svelte, static HTML). Requires the ability to read and edit the frontend source.
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect
  crusor-origin: adapted
  crusor-sources: "anthropics/skills@8a1541c4 (frontend-design); vercel-labs/agent-skills@063bee94 (web-design-guidelines)"
  crusor-verified-on: "2026-10-30"
  crusor-triggers: "design system, visual direction, tokens, typography, palette, ui design, look-and-feel, accessibility, design review, frontend design"
---

# Frontend Design Architect

Design is a **system decision**, not a styling pass. Deliver a design brief plus
a token and component contract the whole codebase is held to — not a screenshot
or a pile of `className`s.

## When to use

- Starting a new UI or a new page family.
- The UI "works" but reads as generated, templated, or bootstrapped.
- A design system exists but has no enforceable rules (every component invents
  its own spacing, radius, color and type).
- Reviewing a frontend before it is scaled to more screens or contributors.

## When NOT to use

- The user supplied a visual spec or brand system: follow it exactly.
- A tweak inside an already-governed system: use the existing tokens.

## Step 1 — Ground the design before choosing anything

Identify in one paragraph: the product, its audience, its primary job, and the
subject's vernacular (materials, vocabulary, artifacts, era). If the brief does
not say, state a concrete proposal and continue — never ask for taste you can
infer from the domain.

Distinctiveness comes from the subject, not decoration: a dashboard for
financial analysts and a toy landing page must not share a palette, type and
rhythm.

## Step 2 — Choose a direction, and be able to defend it

Write a **design direction card** — six lines, no more:

```
Direction:      <one line, e.g. "editorial dossier, not SaaS dashboard">
Type:           <families and roles: display / text / mono>
Palette:        <base, surface, ink, one accent, one signal — named hex>
Layout:         <grid, measure, alignment, rhythm>
Motion:         <one orchestrated moment, or none>
Signature:      <the one memorable element>
```

Boldness is spent on the signature; everything around it stays quiet.

### Defaults to refuse (the generated-page tells)

Legitimate *choices* for some briefs, *defaults* for none. If the brief does not
ask for one, do not spend the design's freedom on it:

- warm cream (`#F4F1EA`-ish) + serif display + terracotta accent
- near-black page + single acid-green or vermilion accent
- identical rounded cards for every content type, one radius for all hierarchy
- gradient washes as decoration, not information
- tracked-out ALL-CAPS eyebrows, `·`-joined meta strings, `→` on every link
- fade-and-slide-up on every section; hover transitions on every card

If the card could be produced unchanged for an unrelated product, it is a
default rather than a decision — rewrite it.

## Step 3 — Token architecture (three tiers, one direction)

Three tiers: **primitive** (raw values) → **semantic** (role) → **component**
(usage). A component that reads a primitive has skipped the design.

Rules:

- Components consume **semantic or component** tokens only; primitives appear
  in exactly one place (the theme). No `--color-1`, no aliases of aliases.
- One radius scale (2–3 steps), one spacing scale (4/8-based), one elevation
  set. Hierarchy comes from scale and contrast, not from new values.
- Theme switching (light/dark) is a semantic re-map. If a component breaks in
  dark mode, a component reached past the semantic layer.
- Contrast is a token property, not a fix-up: verify text/UI pairs at authoring
  time (WCAG AA: 4.5:1 body, 3:1 large text and UI boundaries).

## Step 4 — Type and layout are information

- One family, or two distinct in role — not three.
- A real scale with intentional steps (12/14/16/20/25/31/39), not ad-hoc sizes.
  Line-height tightens as size rises; measure stays under ~80 characters.
- Layout primitives are shared: `Stack`, `Cluster`, `Grid`, `Sidebar`, `Cover`.
  Pages compose primitives; they never hand-roll margins.
- Alignment is decided once per surface; reading surfaces default left.
- Structural devices — rules, numbering, borders — encode information or go.
  Numbered markers imply a real sequence.

## Step 5 — Component API contracts

For each shared component, the architect defines:

```ts
type CardProps = {
  density?: "comfortable" | "compact";
  interactive?: boolean;                  // focus + hover affordances
  as?: "article" | "section" | "li";      // semantics are a prop
};
```

- Variants are a closed, typed set; `className` is an escape hatch, not the API.
- Every component ships all states: default, hover, focus-visible, active,
  disabled, loading, empty, error, and dense/long-content where data-bearing.
- Components never fetch; data enters at the feature boundary. If a page sets a
  font size, the type scale is not doing its job.

## Step 6 — Budgets (written down, then enforced)

| Budget | Target |
|---|---|
| Motion | one orchestrated moment; respects `prefers-reduced-motion` |
| CLS from fonts/media | 0 — `font-display`/size-adjust, explicit dimensions |
| Hero LCP | ≤ 2.5 s on a mid-tier mobile profile |
| Critical CSS | above-the-fold inlined or preloaded; no blocking font chain |
| Keyboard | every control reachable, visible focus, logical order |
| Contrast | AA minimum; AAA on long-form reading surfaces |

## Anti-patterns that force a rewrite

- Tokens invented per component ("local styling"), so the theme can never change.
- Page layout built from absolute positioning or magic margins.
- Scroll animation for its own sake; content invisible until JS runs.
- A component library adopted with no wrapper layer, leaking its API everywhere.
- "Polish later": states and accessibility retrofitted afterwards.

## Verification receipts

Do not claim the design is done without evidence:

1. **Screens at 360 / 768 / 1440** — screenshots, not assertions.
2. **Contrast audit** of the token pairs actually used (axe or equivalent).
3. **Keyboard walk** of the primary flow, focus visible at each stop.
4. **Reduced-motion run** — nothing disappears or breaks.
5. **Lighthouse/CLS** on the heaviest page.
6. **Token diff**: no raw hex, px font-size, or one-off radius outside the theme.

If the environment cannot produce a receipt, say which and why — never report
the design as verified without it.
