---
name: mobile-accessibility-architect
description: Architect-level mobile accessibility — screen reader semantics, dynamic type and reflow, touch target and contrast minimums, focus order and announcements, motion and haptics, and the assistive-technology testing that proves it. Use when an app must be usable by everyone, and when platforms regulate it.
license: MIT
compatibility: VoiceOver, TalkBack, Switch Control, Android Accessibility Scanner
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/quality-architect/mobile-accessibility-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/design/human-interface-guidelines/accessibility; developer.android.com/guide/topics/ui/accessibility; w3.org/TR/WCAG22"
  crusor-triggers: "mobile accessibility, voiceover, talkback, dynamic type, screen reader, contrast, touch target, a11y, large text, accessibility label"
  crusor-verified-on: "2026-10-30"
---

# Mobile Accessibility Architect

Accessibility is **a property of the component library**, not a cleanup pass at the
end. If the design-system primitives carry semantics, every screen inherits them.

## When to use

- Building or auditing a design system.
- Shipping to regulated markets, government, health, finance, or enterprise.
- Any app with text, forms, or navigation — which is all of them.

## When NOT to use

- Purely decorative, non-interactive content with no alternatives.

## Decision 1 — Minimums

| Requirement | Target |
|---|---|
| touch target | 44×44 pt (iOS) / 48×48 dp (Android) |
| text contrast | 4.5:1 body, 3:1 large text |
| non-text contrast | 3:1 for controls and focus |
| text scaling | full support to 200% without loss |
| reflow | no horizontal scrolling at large sizes |
| motion | reduced-motion respected |

## Decision 2 — Semantics

- Every interactive element exposes: role, label, value, state, and hint where
  needed.
- Group related content into one announcement; do not stream fragments.
- Decorative images are hidden from the tree; informative images get a
  description.
- Custom-drawn controls must declare their role explicitly — a canvas button is
  invisible to a screen reader by default.
- Labels are action-oriented ("Add to cart"), not visual ("green plus").

## Decision 3 — Layout and text

- No fixed heights around text; let it grow and scroll.
- Truncation is acceptable only for non-essential content; never for prices,
  errors, or confirmation text.
- Multi-column layouts collapse to one at large text sizes.
- Use the platform's text styles so scaling is automatic.
- Support bold-text and high-contrast OS settings.

## Decision 4 — Focus and interaction

- Logical focus order matching visual order; no traps inside modals.
- Focus moves to the new screen's heading on navigation, and back on return.
- Announcements for async changes: validation errors, toasts, loading completion.
- Full operability with Switch Control / keyboard: every action reachable without
  gestures, including swipe-only interactions.
- Gesture alternatives: a swipe action needs a visible button equivalent.

## Decision 5 — Test with the tool, not the intention

- VoiceOver and TalkBack on every navigation path, at maximum text size.
- Accessibility Scanner / Xcode accessibility inspector in CI where possible.
- Real assistive-technology users in usability testing — not just automated scans.
- Test the flows that matter: login, search, checkout, error recovery.

## Failure modes at scale

- Icons-only buttons with no labels; the screen reader says "button, button".
- Custom fonts that ignore dynamic type, so 200% text does nothing.
- Contrast checked in light mode only.
- A modal with no dismiss path for Switch Control users.
- Accessibility audited once, then the design system drifted.

## Verification receipts

1. Component-level a11y checklist applied in the design system.
2. VoiceOver/TalkBack walkthrough of the three core flows, recorded.
3. Largest text size screenshot per key screen, with no clipping.
4. Automated scan report with zero critical findings.
5. One session with an assistive-technology user, findings triaged.
