---
name: accessibility-architect
description: Architect-level accessibility guidance — WCAG 2.2 AA as an engineering budget, semantic HTML before ARIA, focus and keyboard ownership, live regions for async UI, and the review gates that keep a design system accessible as it grows. Use when building or auditing a web frontend.
license: MIT
compatibility: Framework-agnostic (React, Vue, Angular, Svelte, static HTML)
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/accessibility-architect
  crusor-origin: original
  crusor-sources: "w3.org/TR/WCAG22; w3.org/WAI/ARIA/apg; web.dev/accessibility"
  crusor-triggers: "accessibility, a11y, wcag, aria, screen reader, keyboard navigation, focus management, contrast"
  crusor-verified-on: "2026-10-30"
---

# Accessibility Architect

Accessibility is **structural**, not a checklist applied at the end. If the
primitives are accessible, features inherit it; if they aren't, every feature
pays for it again.

## When to use

- Building a component library or any user-facing surface.
- An audit flags contrast, keyboard traps, or unlabeled controls.
- Designing async UI: modals, toasts, live search, optimistic lists.

## When NOT to use

- Purely internal tooling with no human UI? Still applies — but the review depth
  can be scoped explicitly.

## Decision 1 — Semantics first

- Use the element that already means the thing: `button`, `a[href]`, `label`,
  `fieldset/legend`, `dialog`, `nav`, `main`.
- A `div` with a click handler is a broken button: no keyboard, no role, no
  announcement.
- ARIA is a repair tool for gaps HTML cannot express — every `role` needs its
  required states, and bad ARIA is worse than none.
- Headings form the document outline; one `h1`, no skipped levels for styling.

## Decision 2 — Keyboard and focus (the hard part)

- Everything operable by mouse is operable by keyboard, in a logical order.
- Visible focus is non-negotiable (`:focus-visible`, never `outline: none`).
- Modals: trap focus inside, return focus to the trigger on close, `Esc` closes,
  background is `inert`.
- Route changes move focus to the new heading and announce the new page.
- Skip link to main content; no positive `tabindex`.

## Decision 3 — Names, states, and errors

- Every control has an accessible name (visible label > `aria-label`).
- State is exposed (`aria-expanded`, `aria-pressed`, `aria-invalid`,
  `aria-busy`), not only conveyed by colour.
- Errors: associated with the field (`aria-describedby`), announced, and
  summarised at submit for long forms.
- Async updates use `role="status"` (polite) for counts/saves and
  `role="alert"` (assertive) sparingly — assertive floods screen readers.

## Decision 4 — Visual requirements

- Contrast: 4.5:1 body text, 3:1 large text and UI boundaries; focus indicators
  3:1 against adjacent colours.
- Never encode meaning in colour alone (required, error, status).
- Text scales to 200% without loss; no fixed-height text containers.
- Motion respects `prefers-reduced-motion`; no autoplay beyond 5 s without
  control.

## Decision 5 — Verification is a gate, not a phase

- Automated: axe in component tests and CI on key routes (catches ~30%).
- Manual, per release: keyboard-only pass, screen-reader pass on critical
  journeys (VoiceOver/NVDA), zoom 200%.
- Accessibility acceptance criteria live on the component contract, so a new
  variant cannot ship without them.

## Failure modes at scale

- A design-system Button that is a `div` — the whole product inherits it.
- Focus lost after modal close → keyboard users stranded at page top.
- Toast-only confirmation, invisible to screen readers.
- Icon-only buttons with no name.
- Automated scans green, real usage broken.

## Verification receipts

1. axe: zero serious/critical on key routes.
2. Keyboard-only journey completed end to end, focus visible at every step.
3. Screen-reader pass on the primary journey, notes attached.
4. Contrast audit on tokens (not on individual pages).
5. Reduced-motion and 200% zoom verified.
