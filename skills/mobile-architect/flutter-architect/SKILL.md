---
name: flutter-architect
description: Architect-level Flutter guidance — widget tree structure and rebuild scope, state management choice with its consequences, navigation and deep links, platform channel boundaries, isolate and performance discipline, and the build/release topology across iOS and Android. Use for Flutter apps.
license: MIT
compatibility: Flutter 3.19+/Dart 3; Material and Cupertino
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/flutter-architect
  crusor-origin: original
  crusor-sources: "docs.flutter.dev; api.flutter.dev; dart.dev/language/concurrency"
  crusor-triggers: "flutter, dart, widget tree, riverpod, bloc, platform channels, flutter app"
  crusor-verified-on: "2026-10-30"
---

# Flutter Architect

Flutter renders **every pixel itself**. That gives identical UI everywhere and
makes rebuild scope the central performance discipline.

## When to use

- One design across iOS and Android, delivered by a small team.
- Custom visual density, animation-heavy UI, or branded experiences.
- Desktop/web targets alongside mobile from one codebase.

## When NOT to use

- Teams needing deep, changing platform SDK integration (native is less friction).
- Apps where the platform look must be genuinely native-feeling and dynamic.

## Decision 1 — State management, chosen once

| Option | Consequence |
|---|---|
| `setState` + `InheritedWidget` | fine for small apps, painful at scale |
| Riverpod | testable, compile-safe, no BuildContext dependency |
| BLoC | explicit event/state, verbose, good for complex flows |
| Provider | simplest, easiest to misuse as a global |

- Pick one, document it, and forbid mixing — two systems in one app is the
  classic Flutter decay.
- Business logic lives in controllers/notifiers/not BLoCs, never in widgets.
- Immutable state objects; equality by value so rebuilds are predictable.

## Decision 2 — Widget tree discipline

- Small widgets, `const` constructors everywhere they fit — this is the single
  biggest free performance win.
- Rebuild scope: wrap only what changes (`Consumer`/`BlocSelector`/`select`), not
  the whole screen.
- `ListView.builder` (never `ListView(children: …)`) for anything dynamic.
- Layout overdraw: avoid nested stacks of `Container` with decorations when a
  `DecoratedBox`/`ClipRRect` suffices.

## Decision 3 — Navigation and deep links

- One router (go_router or Navigator 2.0) declares routes once, with typed
  parameters.
- Deep links map to routes; a link that cannot resolve shows a recovery screen,
  not a crash.
- Back behaviour is per platform: iOS swipe, Android system back — tested on
  both.

## Decision 4 — Platform boundary

- Platform channels for capabilities (permissions, push, background); each call
  is async, typed, and failure-handled.
- Isolates for CPU-heavy work; Dart is single-threaded per isolate, and a jank
  is usually synchronous work on the UI isolate.
- Plugins are dependencies with release risk: pin, audit, and prefer maintained
  ones (see `supply-chain-architect`).

## Decision 5 — Build and release

- Flavors for dev/staging/prod; configuration injected at build time, secrets
  never bundled.
- iOS and Android store metadata, signing and versioning managed in CI.
- Startup: defer plugin registration and heavy init until after first frame.
- Feature flags + remote config make "release" separable from "deploy to store".

## Failure modes at scale

- `setState` in a screen that renders 2,000 list items.
- Two state systems, so nobody knows where a value comes from.
- Widgets with 400 lines and business rules inside `build()`.
- Plugin upgrades breaking the build with no lockfile discipline.
- Everything initialised in `main()` → three-second cold start.

## Verification receipts

1. Profile-mode trace: frame times during scroll and navigation.
2. `const` audit and rebuild-count check on a hot screen.
3. Deep-link test for every declared route, including an invalid one.
4. Platform channel test on both platforms with a denied permission.
5. Cold start measured on a mid-tier Android device.
