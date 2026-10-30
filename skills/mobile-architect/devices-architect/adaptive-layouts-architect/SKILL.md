---
name: adaptive-layouts-architect
description: Architect-level adaptive UI — window size classes and breakpoints, split and multi-column layouts, foldables and large screens, orientation and keyboard handling, and the state model that survives a resize. Use when one app must look right on phones, tablets, foldables, and desktop-class windows.
license: MIT
compatibility: WindowSizeClass, UIKit size classes, SwiftUI layout, Jetpack Compose
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/devices-architect/adaptive-layouts-architect
  crusor-origin: original
  crusor-sources: "developer.android.com/develop/ui/compose/layouts/adaptive; developer.apple.com/design/human-interface-guidelines/layout; developer.android.com/guide/topics/large-screens"
  crusor-triggers: "adaptive layout, tablet, foldable, window size class, split view, multi pane, orientation change, large screen, responsive mobile"
  crusor-verified-on: "2026-10-30"
---

# Adaptive Layouts Architect

A mobile app now runs on **phones, tablets, foldables, and desktop-class windows**.
One layout stretched across all of them is the default failure.

## When to use

- Tablet or foldable support is expected (store listings penalise phone-only).
- ChromeOS/desktop windows or split-screen multitasking matter.
- Layout breaks on rotation or when the keyboard appears.

## When NOT to use

- A single-device, single-orientation kiosk app.

## Decision 1 — Breakpoints

| Size class | Typical width | Layout |
|---|---|---|
| compact | < 600 dp | single column, bottom navigation |
| medium | 600–840 dp | two-pane list/detail, rail nav |
| expanded | > 840 dp | persistent navigation, 2–3 columns |

- Decide by **available width**, not device type — a foldable changes class mid-session.
- Navigation should convert: bottom bar → navigation rail → permanent drawer.
- Content max-width matters: text lines wider than ~70 characters are unreadable.

## Decision 2 — Structure

- List-detail is the canonical adaptive pattern: one pane when compact, two when
  expanded.
- Keep state in a place that survives pane changes (view model, not view).
- Insets: system bars, display cutouts, and hinge areas are not usable space.
- Foldables: avoid placing critical controls across the hinge; test posture changes.

## Decision 3 — Input

- Keyboard avoidance: scroll the focused field into view; never let it hide behind the
  keyboard.
- Mouse/trackpad and stylus support where the platform allows (hover states, right-click,
  drag).
- Touch targets stay ≥ 44/48 dp regardless of window size.
- Orientation: support both unless the domain forbids it; test the transition mid-flow
  (a video call, a form).

## Decision 4 — State across resizes

- Process death, rotation, and window resize are different events — handle all three.
- Save scroll position and form input; losing either reads as a crash.
- Multi-window: the app may be paused without being destroyed; do not reload data on
  every resume.

## Decision 5 — Testing

- Emulators with resizable windows; a real foldable if you claim support.
- Test at maximum font scale in every size class — the combination is where clipping
  appears.
- Screenshot tests per size class for key screens.

## Failure modes at scale

- Phone layout stretched to a tablet; content in a 1200 dp single column.
- Bottom navigation on a tablet with a 15-inch-wide touch target row.
- State lost on rotation because it lived in the view.
- Hinge covered by a critical button on a foldable.
- Keyboard hides the submit button; users cannot complete a form.

## Verification receipts

1. Breakpoint table with the layout per size class.
2. Screenshots of three key screens in compact, medium, and expanded.
3. Rotation and resize tests with state preserved.
4. Keyboard-avoidance test on the longest form.
5. Foldable posture test if support is claimed.
