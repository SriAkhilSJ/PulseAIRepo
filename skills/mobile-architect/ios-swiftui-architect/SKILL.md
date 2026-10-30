---
name: ios-swiftui-architect
description: Architect-level iOS design with SwiftUI and UIKit — view and state ownership, Observation and Swift concurrency, lifecycle and scene phase, navigation stacks, UIKit interop, and the platform integration points that decide app quality. Use when building or restructuring an iOS app.
license: MIT
compatibility: iOS 17+, SwiftUI, UIKit interop, Swift 6 concurrency
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/ios-swiftui-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/swiftui; developer.apple.com/documentation/observation; developer.apple.com/documentation/swift/concurrency"
  crusor-triggers: "swiftui, uikit, ios app, swift concurrency, observable, navigationstack, scene phase, ipad, ios 18, swift"
  crusor-verified-on: "2026-10-30"
---

# iOS / SwiftUI Architect

SwiftUI is **a declaration of state, not a place to put logic**. The architecture is
deciding who owns state, who computes it, and where the async work lives.

## When to use

- Building a new iOS app or screen set.
- Migrating UIKit to SwiftUI incrementally.
- State or navigation code that has become tangled.

## When NOT to use

- The work is cross-platform UI → `react-native-architect` / `flutter-architect`.
- The problem is the backend contract.

## Decision 1 — State ownership

| Property wrapper | Owns | Use |
|---|---|---|
| `@State` | local view value | ephemeral UI (toggle, text field) |
| `@Observable` model | screen state | view model, injected |
| `@Environment` | dependency or shared value | DI, theme, session |
| `@Bindable` | two-way into observable | form fields |
| `@StateObject`/`@ObservedObject` (legacy) | pre-Observation code | migrate deliberately |

- One owner per piece of state. Two views writing the same concept is the source
  of most SwiftUI bugs.
- View bodies are pure projections: no networking, no side effects, no heavy
  computation.
- Derive rather than store: computed properties over duplicated state.

## Decision 2 — Concurrency

- Swift concurrency with actor isolation; UI-adjacent types `@MainActor`.
- Long work in detached tasks or a repository layer; never in `body` or `.task`
  without cancellation.
- Cancel on disappear; structured concurrency instead of stray `Task { }` chains.
- `Sendable` conformance is a design statement about your models — model types as
  value types where possible.
- Async sequences for streams (location, notifications) with explicit teardown.

## Decision 3 — Navigation

- `NavigationStack` with a path value type owned by one coordinator; deep links
  map into that path.
- One route enum per flow, typed, not string identifiers scattered in views.
- Sheets/full-screen covers are presentation state, not navigation state — decide
  and be consistent.
- iPad: consider `NavigationSplitView` from the start; retrofitting is expensive.

## Decision 4 — UIKit interop

- Wrap UIKit in `UIViewRepresentable`/`UIViewControllerRepresentable` behind a
  narrow interface.
- Heavy camera, map, text editing, or collection views may stay UIKit — that is a
  valid architecture, not a failure.
- Do not mix navigation systems: one stack, one owner.

## Decision 5 — Platform integration

- App lifecycle via `scenePhase`; persist and restore state deliberately.
- Background tasks are opportunistic and time-boxed; never assume execution.
- Widgets, Live Activities, App Intents, and Shortcuts each have their own process
  and data sharing (App Group) — design the shared store once.
- Permissions requested in context with an explanation, not en masse at launch.

## Decision 6 — Quality bar

- SwiftUI previews for every screen with fixture data; no preview that runs
  networking.
- XCTest for domain and view models; UI tests for the money path only.
- Instruments for launch, hitching, and memory before release.
- Localisation from day one: string catalogs, no concatenation, RTL checks.

## Failure modes at scale

- View model recreated on every body evaluation, refetching data in a loop.
- Networking inside `body`, causing cascading re-renders.
- Two `NavigationStack`s in one hierarchy; back gestures break silently.
- `Task { }` in `onAppear` without cancellation, duplicating requests on scroll.
- State distributed across five `@State` properties in three views.

## Verification receipts

1. State ownership map: which type owns which screen's state.
2. Concurrency audit: no un-cancelled tasks, `@MainActor` on UI models.
3. Navigation paths typed and deep links tested.
4. Preview and test coverage for each screen's states (loading, empty, error).
5. Launch and memory trace on the oldest supported device.
