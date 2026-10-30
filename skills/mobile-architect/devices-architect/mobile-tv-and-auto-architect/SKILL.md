---
name: mobile-tv-and-auto-architect
description: Architect-level design for TV and in-car surfaces — ten-foot UI and focus navigation, remote/D-pad input, Android Auto and CarPlay templates, media session and playback architecture, and the store and safety rules that constrain what those surfaces may show. Use when the product extends to television or vehicles.
license: MIT
compatibility: Android TV, tvOS, CarPlay, Android Auto, Media3/AVPlayer
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/devices-architect/mobile-tv-and-auto-architect
  crusor-origin: original
  crusor-sources: "developer.android.com/training/tv; developer.apple.com/design/human-interface-guidelines/designing-for-tvos; developer.android.com/training/cars"
  crusor-triggers: "android tv, tvos, apple tv, android auto, carplay, ten foot ui, focus navigation, media session, d-pad, in car app"
  crusor-verified-on: "2026-10-30"
---

# TV & In-Car Architect

These surfaces have **no touch, no scrollbar, and no patience**. Focus and templates
are the architecture; everything else is content.

## When to use

- The product has video/audio content users consume on a big screen.
- Navigation or messaging has a genuine in-car use case.
- Existing app is expected on TV by customers or the store.

## When NOT to use

- Text-heavy or form-driven experiences — they do not belong on either surface.
- In-car apps with interactive content beyond the approved templates.

## Decision 1 — TV interaction

- D-pad/remote focus: every actionable element must be reachable and focus order must
  be predictable.
- Ten-foot UI: large type, high contrast, minimal text; body text is not a thing on TV.
- Rows of content with a hero area; avoid deep hierarchy — three levels maximum.
- No hover; focus state must be unmistakable (scale, outline, elevation).
- Back behaviour: back from a row → previous row → exit; never a dead end.

## Decision 2 — Media architecture

- Media session/now-playing integration: play, pause, seek, and metadata in the system
  UI.
- Background audio and picture-in-picture have platform rules; implement the platform's
  playback service.
- Resume playback across devices; store position server-side.
- Buffer/quality adaptation is part of the UX: show a progress state, not a frozen
  frame.

## Decision 3 — In-car constraints

- CarPlay/Android Auto require template-based UIs; custom drawing is not allowed.
- Limit list length and item count; the driver must glance, not read.
- Navigation apps use the platform's map surface; media and messaging apps use
  templates.
- Voice interaction is the primary input; design for it before touch.
- The phone app must remain functional when the car surface is unavailable.

## Decision 4 — Distribution

- TV apps have separate store listings, screenshots, and review guidelines (including
  content ratings).
- Car apps require entitlement approval from the platform; plan lead time.
- Version alignment between the mobile app and the extended surfaces.

## Decision 5 — Testing

- Real remotes / emulator with a keyboard mapped to D-pad; test focus loops.
- Car testing requires the platform's simulator plus a real head unit for final checks.
- Performance: TV hardware is weaker than phones; measure startup and scrolling on the
  lowest supported device.

## Failure modes at scale

- Focus trapped in a row; the user cannot reach the play button.
- Text-heavy screen ported from mobile; unreadable at three metres.
- Media session not integrated; playback stops when the app is backgrounded.
- In-car app rejected for using a custom UI instead of templates.
- TV build shipped without a separate listing; invisible in the TV store.

## Verification receipts

1. Focus-navigation map for the main flows, tested with a remote.
2. Media session verified in the system player UI.
3. Car template inventory with the platform's approved set.
4. Performance measurement on the lowest supported TV device.
5. Separate store listing and screenshots prepared.
