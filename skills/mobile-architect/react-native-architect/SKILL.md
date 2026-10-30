---
name: react-native-architect
description: Architect-level React Native guidance — the new architecture boundary (JSI/Fabric/TurboModules), when to write native code, navigation and state ownership, list and image performance, OTA update policy, and the shared-codebase structure that keeps the JS and native sides honest. Use for React Native apps.
license: MIT
compatibility: React Native 0.74+ (New Architecture); Expo or bare
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/react-native-architect
  crusor-origin: original
  crusor-sources: "reactnative.dev/docs; reactnative.dev/architecture; docs.expo.dev"
  crusor-triggers: "react native, expo, fabric, turbo modules, jsi, metro, mobile react, native module"
  crusor-verified-on: "2026-10-30"
---

# React Native Architect

React Native is **a JavaScript runtime hosting native views**. Every performance
and capability question is answered at that boundary.

## When to use

- A web/TypeScript team shipping to both stores.
- Business-facing UI with moderate platform integration.
- Sharing domain logic with an existing React codebase.

## When NOT to use

- Heavy graphics, audio DSP, or deep platform SDK integration (native is cheaper
  than bridged workarounds).
- Pixel-identical design requirements across platforms (see
  `flutter-architect`).

## Decision 1 — Architecture boundary

| Layer | Runs in |
|---|---|
| business logic, state, validation | JS/TS |
| navigation | JS (React Navigation) |
| media, sensors, crypto, push | native module (TurboModule) |
| heavy rendering | native view, wrapped |

- New Architecture (JSI/Fabric) is the default assumption: no bridge-batching
  excuses, but async-native calls still cost.
- Write a native module when a JS workaround costs more than the module; keep it
  behind a TS interface in the domain.
- Anything on the JS thread blocks the UI thread's effects: keep it small.

## Decision 2 — Project structure

```
src/app/         navigation, providers
  src/features/  feature modules (screens, hooks, state)
    src/domain/  entities and rules, platform-free
      src/data/  api clients, local db, sync
        native/  module interfaces + platform implementations
```

- Feature-first, not type-first; a "components/" barrel for everything rots.
- One navigation tree, deep links declared once, typed route params.
- State: local first, then a store; server state via TanStack Query (see
  `tanstack-query-architect`).

## Decision 3 — Performance rules that matter

- Lists: FlatList/FlashList with `keyExtractor`, `getItemLayout` where possible,
  memoised row components, no inline arrow props per row.
- Images: sized, cached, and never decoded on the JS thread at full resolution.
- Animations: Reanimated on the UI thread, not `Animated` driven by JS state.
- Startup: lazy screens, deferred native module init, measure with a release
  build (dev builds lie).
- Re-render discipline: narrow selectors, `React.memo` where measured — not
  everywhere.

## Decision 4 — Native integration

- Permissions and capabilities behind a typed interface with a JS fallback
  (`isAvailable`).
- iOS/Android implementations live next to each other; a missing platform is a
  compile-time or runtime-checked error, never a silent no-op.
- Native versions pinned; upgrading RN is a scheduled project, not a patch.

## Decision 5 — Release and updates

- OTA updates (EAS Update/CodePush-style) only for JS, never for native changes;
  a broken native build still needs review.
- Runtime version pinning: an OTA must never target a binary it was not built
  for.
- Crash reporting with JS error boundaries per screen; a crash in one screen must
  not white-screen the app.
- Feature flags for anything risky, because rollback is a release.

## Failure modes at scale

- Everything in one giant `App.tsx` with navigation and providers entangled.
- JS-thread work in scroll handlers → dropped frames on mid-tier Android.
- Native module with no JS-side capability check → crash on the other platform.
- OTA shipped to an incompatible binary version → immediate crash loop.
- "Works in dev build" performance claims that vanish in release.

## Verification receipts

1. Release-build profile: cold start, JS thread FPS during scroll.
2. List performance on a 5,000-item dataset.
3. Native module matrix: iOS + Android behaviour verified separately.
4. OTA compatibility test: runtime version mismatch refused.
5. Crash-free session rate by screen after release.
