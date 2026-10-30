---
name: html-css-architect
description: Architect-level HTML and CSS guidance — semantic document structure, cascade and specificity ownership, layout primitives (flex/grid), responsive strategy, container queries, and the accessibility semantics that survive refactors. Use when designing page structure, the cascade model, or a responsive system, not for one-off styling fixes.
license: MIT
compatibility: Modern evergreen browsers; framework-agnostic
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/html-css-architect
  crusor-origin: original
  crusor-sources: "WHATWG HTML; MDN CSS layout; W3C WCAG 2.2"
  crusor-triggers: "html, css, layout, flexbox, grid, responsive, cascade, specificity, container-queries, semantics, accessibility"
  crusor-verified-on: "2026-10-30"
---

# HTML & CSS Architecture

Markup and the cascade are the two contracts every other frontend decision rests
on. Get them wrong and no framework, token system or component library can save
the codebase.

## When to use

- Defining page structure, landmarks and heading order.
- Choosing a layout system, or a responsive strategy that is more than breakpoints.
- The cascade is unpredictable (every fix needs `!important`).
- Before adopting a CSS-in-JS library, utility framework or design tokens.

## When NOT to use

- A single spacing or colour value inside an existing system.
- Component behaviour (that is the framework skill's job).

## Decision 1 — Semantics before styling

- Landmarks: one `<main>`, `<header>`/`<footer>` per region, `<nav>` for
  navigation groups.
- One `<h1>` per page; heading levels are structure, never font sizes.
- Buttons do things, links go places. A `<div onClick>` is a keyboard and
  screen-reader failure, not a style choice.
- Forms: every control has a `<label>`; errors are announced, not just coloured.
- Lists are lists; tables are tabular data with `<th scope>`.

## Decision 2 — The cascade model

Pick one ownership model and enforce it:

| Model | Use when | Cost |
|---|---|---|
| **Utility-first** (Tailwind) | speed, consistency, small teams | markup density; needs a token layer anyway |
| **CSS Modules / scoped** | component libraries, long-lived apps | harder cross-component theming |
| **Layered global + components** (`@layer`) | a real design system | requires discipline on layer boundaries |
| **CSS-in-JS** | runtime theming, heavy dynamic styles | runtime cost, SSR complexity |

Rules that apply to all of them:

- Specificity budget: element → class → (rare) attribute/state. No IDs for
  styling, no `!important` outside a documented escape hatch.
- `@layer` (reset, tokens, base, components, utilities) makes order explicit;
  unlayered CSS silently wins over everything — keep it at zero.
- One owner per concern: spacing comes from the layout primitive or the token
  scale, never from both.

## Decision 3 — Layout and responsiveness

- Layout primitives first: `Stack` (vertical rhythm), `Cluster` (wrapping row),
  `Grid` (2D), `Sidebar`, `Cover`. Pages compose these; they do not invent
  margins.
- Flexbox for one dimension, grid for two. Do not simulate grid with flex.
- Responsive strategy is **intrinsic first**: `min()`, `clamp()`, `auto-fit`,
  container queries. Breakpoints are a fallback for genuinely different
  layouts, not a substitute for fluid type and spacing.
- Container queries beat viewport queries for components; a card must respond to
  its container, not the window.
- Logical properties (`margin-inline`, `padding-block`) for anything that may be
  localised RTL.

## Failure modes at scale

- Specificity wars: each fix raises specificity until nothing can be overridden.
- Breakpoint explosion: 11 media queries for one page.
- Utility soup with no token layer: the palette drifts by copy-paste.
- Layout shift from unsized media/fonts.
- Accessibility regressions from div-based controls "because it was faster".

## Verification receipts

1. Heading/landmark outline reviewed (one h1, no skipped levels).
2. Keyboard walk of the page; visible focus at every stop.
3. Viewport pass at 360 / 768 / 1440 with no horizontal scroll.
4. `prefers-reduced-motion` and 200% zoom both usable.
5. CSS audit: no `!important`, no id selectors, no magic pixel values outside
   tokens.
