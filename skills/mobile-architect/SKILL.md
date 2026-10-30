---
name: mobile-architect
description: Architect-level mobile direction — choosing native versus cross-platform from product and team constraints, shared architecture (navigation, state, data and sync), offline-first realities, platform capability boundaries, and the release path that a mobile product is held to. Use before any platform-specific mobile skill.
license: Apache-2.0
compatibility: iOS, Android; native and cross-platform stacks
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/design; developer.android.com/design; reactnative.dev; docs.flutter.dev"
  crusor-triggers: "mobile app, ios, android, cross platform, native app, app architecture, offline first, mobile release, mobile security, mobile testing, accessibility, app performance, offline sync, offline"
  crusor-verified-on: "2026-10-30"
---

# Mobile Architect

A mobile app is **a client with a hostile environment**: intermittent network,
an OS that can kill you at any moment, and a release you cannot hotfix instantly.

## Leaf map

Five shelves, 27 books.

| Shelf | Books |
|---|---|
| `platforms-architect/` | `ios` · `ios-swiftui` · `uikit-legacy` · `android` · `android-compose` · `android-views` · `react-native` · `flutter` · `kotlin-multiplatform` |
| `quality-architect/` | `mobile-testing` · `mobile-performance` · `mobile-accessibility` · `mobile-observability` · `mobile-analytics` |
| `data-architect/` | `mobile-offline-sync` · `mobile-security` |
| `devices-architect/` | `mobile-device-integration` · `adaptive-layouts` · `wearables` · `mobile-tv-and-auto` · `push-notifications` · `mobile-deep-linking` · `mobile-localization` |
| `delivery-architect/` | `mobile-release` · `mobile-build` · `mobile-modularization` · `in-app-purchases` |

Read the crown, then the one or two books the plan actually needs.

## Decision 1 — Native vs cross-platform

| Constraint | Choose |
|---|---|
| deep platform APIs, widgets, camera/AR/BLE | native |
| small team, both platforms, business UI | React Native or Flutter |
| pixel-identical UI across platforms | Flutter |
| existing web team, shared TypeScript | React Native |
| performance-critical graphics/audio | native |

- Cross-platform is a **product decision**, not a cost shortcut; you pay later at
  every platform integration.
- Sharing business logic is usually worth it; sharing UI less so.
- Decide once. A half-migrated app carries both costs forever.

## Decision 2 — Shared architecture (same on every stack)

```
Presentation   screens, navigation, design system
  Domain       entities, use-cases (no platform APIs)
    Data       repositories, local DB, network, sync
      Platform adapters  permissions, push, background, storage
```

- The domain layer must be platform-free — that is what makes it testable and
  portable.
- Navigation is state, not a stack of pushed callbacks: one place owns the route.
- Dependency injection or a service locator, chosen once; no globals reached
  from screens.

## Decision 3 — Offline-first, explicitly

- Assume the network is absent, slow and unreliable — all three.
- A local store (SQLite/Realm/Core Data/WatermelonDB) is the source of truth for
  reads; the server is the source of truth for authority.
- Sync needs: conflict policy (server-wins, client-wins, merge), retry with
  backoff, and an outbox for writes made offline.
- Optimistic UI requires a visible pending/failed state; silent data loss is the
  classic mobile bug.

## Decision 4 — Lifecycle and state restoration

- The OS can terminate the app in the background; anything not persisted is
  gone.
- Save draft state on background; restore route + scroll + form on relaunch.
- Handle deep links, push-tap navigation, and cold-start vs warm-start
  differently.
- Background work is scheduled, not assumed: budget, permissions, and OS limits
  apply.

## Decision 5 — Platform capabilities as adapters

- Permissions, push, biometrics, camera, files: each is an interface in the
  domain and an implementation per platform.
- Check capability and permission state before use; degrade with a clear
  explanation, never a silent failure.
- Never store secrets in the app bundle; the device is not a trusted
  environment.
- Analytics/crash reporting from day one, with PII rules stated.

## Decision 6 — Release reality

- Store review is a queue you do not control: no same-day hotfix without a
  server-side switch.
- Feature flags + remote config make "ship the code, release the feature"
  possible.
- Version in one place; build numbers monotonic.
- Crash-free session rate is the mobile equivalent of uptime — measure it.

## Failure modes at scale

- Business logic inside screens, so nothing can be tested or shared.
- Offline writes queued with no conflict strategy → silent overwrites.
- A hard dependency on the latest OS version, fragmenting the user base.
- Secrets or API keys in the bundle, extractable in minutes.
- No remote kill switch: a broken release waits for review while users suffer.

## Verification receipts

1. Architecture diagram: layers, adapters, ownership per module.
2. Offline test: airplane mode through the primary journey, then reconnect.
3. Process-death test: kill the app mid-flow, relaunch, state restored.
4. Capability matrix: permission denied paths designed and shown.
5. Crash-free rate and cold-start time measured on a mid-tier device.
