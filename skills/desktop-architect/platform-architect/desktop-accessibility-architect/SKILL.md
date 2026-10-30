---
name: desktop-accessibility-architect
description: Architect-level desktop accessibility — platform accessibility APIs and the accessibility tree, keyboard-only operation and focus order, high contrast and scaling, screen reader behaviour in native and webview UIs, and the procurement requirements that make it mandatory. Use when a desktop app must be usable by everyone.
license: MIT
compatibility: UIA/MSAA, NSAccessibility, AT-SPI; NVDA, JAWS, VoiceOver, Orca
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/platform-architect/desktop-accessibility-architect
  crusor-origin: original
  crusor-sources: "learn.microsoft.com/windows/win32/accessibility; developer.apple.com/documentation/appkit/accessibility; gnome.org/accessibility"
  crusor-triggers: "desktop accessibility, screen reader, nvda, jaws, ui automation, focus order, high contrast, keyboard only, accessibility tree"
  crusor-verified-on: "2026-10-30"
---

# Desktop Accessibility Architect

Desktop accessibility is **an API contract with assistive technology**. A webview
inside a native shell inherits neither side's guarantees automatically.

## When to use

- Enterprise, government, education, or healthcare procurement.
- Any app with keyboard-driven users (developers, data entry, accessibility users).
- A webview-based app where the bridge to the native accessibility tree is unclear.

## When NOT to use

- Purely decorative or display-only surfaces — still give them names.

## Decision 1 — The accessibility tree

- Every control exposes role, name, value, state, and actions through the platform API
  (UIA / NSAccessibility / AT-SPI).
- Native toolkits do this by default; custom-drawn controls must implement it
  explicitly.
- Webview content exposes a DOM tree through the browser's bridge — verify the host
  actually surfaces it (Electron enables this; Tauri depends on the platform webview).
- Test with a real screen reader, not just an accessibility inspector.

## Decision 2 — Keyboard

- Every action reachable without a mouse, including menus, dialogs, and custom
  canvases.
- Logical tab order matching visual order; no traps except deliberate modal focus.
- Visible focus indicator with sufficient contrast — always, not only for keyboard
  users.
- Standard shortcuts (Ctrl/Cmd+C/V/Z, F1, Esc) behave as expected; Esc closes modals.

## Decision 3 — Visual

- Respect OS scaling (125–200%) and high-contrast themes; no fixed pixel layouts.
- Colour is never the only signal; icons and text reinforce.
- Minimum contrast per WCAG AA for text and controls.
- Reduced motion honoured; no essential information conveyed by animation alone.

## Decision 4 — Screen reader behaviour

- Announce async changes (validation errors, background completion) via live regions
  or platform events.
- Dialogs: focus moves in, is trapped, and returns on close.
- Tables and lists expose row/column semantics and counts.
- Long operations expose progress and cancellable state.

## Decision 5 — Process

- Accessibility checks in the component library, not per screen.
- Automated checks in CI where the toolkit allows; manual screen-reader passes per
  release.
- Procurement VPAT/ACR documents prepared from actual testing, not aspiration.
- Involve assistive-technology users in testing.

## Failure modes at scale

- Electron app where the webview is invisible to NVDA; unusable.
- Custom canvas control with no accessible name; screen reader says "pane".
- Modal that traps focus permanently.
- High-contrast mode renders white-on-yellow, unreadable.
- VPAT claims conformance; a customer audit finds otherwise.

## Verification receipts

1. Component-level accessibility checklist applied in the design system.
2. Keyboard-only walkthrough of the three core flows.
3. Screen reader pass with NVDA and VoiceOver (or Orca on Linux).
4. Scaling and high-contrast screenshots at 200%.
5. VPAT/ACR prepared from measured results.
