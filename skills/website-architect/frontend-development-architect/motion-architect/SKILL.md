---
name: motion-architect
description: Architect-level motion design — purpose-driven transitions with a shared timing and easing scale, choreography and state-change continuity, reduced-motion policy, and the performance rules (transform/opacity, no layout thrash) that keep animation from costing frames. Use when adding or auditing UI motion.
license: MIT
compatibility: Framework-agnostic; CSS transitions + View Transitions / Framer Motion / GSAP
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/motion-architect
  crusor-origin: original
  crusor-sources: "web.dev/animations; developer.mozilla.org/CSS/transitions; w3.org/WAI/WCAG22 (2.3.3)"
  crusor-triggers: "motion, animation, transition, transitions, page transition, framer motion, easing, view transitions, micro-interactions, prefers-reduced-motion"
  crusor-verified-on: "2026-10-30"
---

# Motion Architect

Motion is **communication**: it explains where something came from, what changed,
and what needs attention. If it explains nothing, it is delay.

## When to use

- Adding transitions, page changes, loading and success states.
- The interface feels janky, sluggish, or over-animated.
- Choosing between CSS, View Transitions, and an animation library.

## When NOT to use

- Decorative 3D/immersive scenes (see `threejs-architect`).
- Motion that only exists because a template had it.

## Decision 1 — Purpose or nothing

| Purpose | Motion |
|---|---|
| continuity (element moves/expands) | shared-element / layout transition |
| causality (menu opened from button) | origin-aware scale+fade |
| feedback (pressed, saved) | 100–150 ms micro-transition |
| attention (error) | small nudge, once — never a loop |
| progress | determinate bar; indeterminate only when unknown |

- Every animation names its purpose. "It looked nice" is not a purpose.
- One hero moment per view; the rest stays quiet.

## Decision 2 — A scale, not ad-hoc numbers

- Durations: 100 ms (micro), 200 ms (standard), 300 ms (large), 400 ms max for
  UI.
- Easing: one standard ease-out, one ease-in for exits; no bounce except
  playful brands that own it.
- Tokens (`--motion-fast`, `--ease-standard`), used by every component — motion
  consistency is what makes a product feel designed.

## Decision 3 — Choreography

- Enter: fade + small translate (8–16 px), children stagger 20–40 ms.
- Exit: faster than enter, no stagger delay.
- Lists: animate on insert/remove only; never re-animate the whole list on
  filter.
- Layout change: animate position/size with a layout transition, not by
  measuring in JS each frame.

## Decision 4 — Performance rules

- Animate `transform` and `opacity` only. `width`, `height`, `top`, `left`
  trigger layout; `box-shadow` triggers paint.
- `will-change` is a hint, not a fix; remove it after the animation.
- Keep the main thread free: no JS animation loops competing with input (INP).
- Off-screen animation pauses.

## Decision 5 — Accessibility and restraint

- `prefers-reduced-motion: reduce` removes movement but keeps state changes
  (instant or cross-fade); never disable feedback entirely.
- No flashing above 3 Hz; no auto-playing looping motion.
- Motion never blocks interaction: the UI is usable before the animation ends.

## Failure modes at scale

- 600 ms page transitions on every navigation — the app feels slow, because it
  is.
- Animating `height: auto` → jank on every accordion open.
- Motion that ignores `prefers-reduced-motion` (a WCAG failure).
- Different easing per component → the product feels assembled, not designed.
- Animations that delay the actual content by a second.

## Verification receipts

1. Duration/easing audit against the token scale.
2. Performance panel: no layout/paint-bound animations, 60 fps maintained.
3. Reduced-motion pass: content changes still visible and instant.
4. Navigation timing: perceived transition under 300 ms.
5. One documented list of intentional motion moments.
