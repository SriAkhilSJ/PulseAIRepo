---
name: ios-architect
description: Architect-level iOS guidance — SwiftUI versus UIKit boundaries, app and scene lifecycle, state ownership with Observation, navigation and deep linking, concurrency with structured tasks, and the platform constraints (background execution, storage, privacy) an app is built against. Use for Apple platform apps.
license: MIT
compatibility: iOS 17+; Swift 5.9+; SwiftUI + UIKit where needed
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/ios-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/swiftui; developer.apple.com/documentation/swift/concurrency; developer.apple.com/design/human-interface-guidelines"
  crusor-triggers: "ios, swift, swiftui, uikit, xcode, apple, app lifecycle, ios app"
  crusor-verified-on: "2026-10-30"
---

# iOS Architect

iOS gives you **a strict lifecycle and a cooperative OS**. The app does not own
the device; it borrows foreground time.

## When to use

- Building or reviewing an iPhone/iPad app.
- Choosing SwiftUI vs UIKit, or a hybrid.
- Background tasks, push, or state restoration misbehave.

## When NOT to use

- Cross-platform work where the shared layer matters more (see
  `react-native-architect`, `flutter-architect`).

## Decision 1 — SwiftUI vs UIKit

| Need | Choose |
|---|---|
| new screens, straightforward flows | SwiftUI |
| complex collection layouts, text input edge cases | UIKit (`UIViewRepresentable` bridge) |
| camera/AR/map-heavy surfaces | framework-native, wrapped |
| minimum deployment below iOS 16 | UIKit for the hard parts |

- Mixing is normal: SwiftUI owns composition, UIKit fills gaps behind a
  wrapper.
- Do not fight the framework with view-model-per-pixel; state belongs to the
  model layer.

## Decision 2 — Lifecycle and state

- `@State` for view-local, `@Observable`/`ObservableObject` for shared scene
  state, injected via environment — never a global singleton reached from
  views.
- Scene phase changes (`active`/`background`/`inactive`) drive persistence,
  timers and refreshes.
- Restore state explicitly (navigation path + form drafts); the OS may kill the
  app at any moment.
- Deep links and universal links resolve to a navigation path in one place.

## Decision 3 — Concurrency

- Structured concurrency: `async let`/`TaskGroup` inside a task, `@MainActor` on
  UI-touching types.
- Cancellation is cooperative — check `Task.isCancelled` in long loops.
- Never block the main actor with sync I/O; use `URLSession` async APIs.
- Background work: `BGTaskScheduler` with explicit identifiers, budgets and
  retry — not a timer.

## Decision 4 — Data and persistence

- SwiftData/Core Data for structured local data; Keychain for credentials;
  `UserDefaults` only for preferences.
- Migrations planned from v1; an unversioned store becomes unmigratable.
- Files in the app container must be backed up or excluded deliberately.
- iCloud sync needs a conflict policy (last-writer-wins is a decision).

## Decision 5 — Platform rules that affect architecture

- Privacy: permission strings, tracking transparency, data-collection
  declarations.
- Background execution is limited and revocable by the user.
- No secrets in the bundle; use short-lived tokens from a backend.
- Accessibility: Dynamic Type, VoiceOver, Reduce Motion — designed, not patched.

## Failure modes at scale

- Massive view bodies with business logic that cannot be unit tested.
- Global singletons holding per-user state across accounts.
- Blocking the main thread with image decoding or JSON parsing.
- Unversioned persistence store that must be wiped on the next release.
- Background task assumptions that fail once the user disables background
  refresh.

## Verification receipts

1. Unit tests on the domain layer without a simulator.
2. Process-death restore test on the primary flow.
3. Offline/airplane-mode journey with cached data.
4. Instruments trace: cold start, memory, main-thread hangs.
5. Accessibility pass at large Dynamic Type + VoiceOver on the main screen.
