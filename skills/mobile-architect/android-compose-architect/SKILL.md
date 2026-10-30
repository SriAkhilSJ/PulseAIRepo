---
name: android-compose-architect
description: Architect-level Android design with Jetpack Compose — unidirectional state, ViewModel and state holders, process death and saved state, Navigation Compose, coroutines and Flow, and the platform integration points that decide app quality. Use when building or restructuring an Android app.
license: MIT
compatibility: Android 8+, Jetpack Compose, Kotlin coroutines, Hilt, Room
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/android-compose-architect
  crusor-origin: original
  crusor-sources: "developer.android.com/develop/ui/compose; developer.android.com/topic/architecture; developer.android.com/kotlin/coroutines"
  crusor-triggers: "jetpack compose, composable, viewmodel, android app, kotlin coroutines, stateflow, navigation compose, process death, hilt"
  crusor-verified-on: "2026-10-30"
---

# Android / Compose Architect

Compose is **a function of state, recomposed on change**. The architecture is where
that state lives, who survives process death, and where the effects run.

## When to use

- New Android app, or a Views-to-Compose migration.
- Recomposition, state, or lifecycle bugs.
- Structuring modules and dependency injection.

## When NOT to use

- Cross-platform UI work → `react-native-architect` / `flutter-architect`.
- The issue is a backend contract or authentication flow.

## Decision 1 — State and events

- Unidirectional: UI emits events up, state flows down. No composable mutates a
  shared model directly.
- `ViewModel` exposes one immutable `UiState` via `StateFlow`; the screen collects
  with lifecycle awareness (`collectAsStateWithLifecycle`).
- Model states as explicit types: `Loading | Content | Empty | Error`, not three
  booleans.
- Hoist state only as high as needed; local UI state stays in the composable with
  `rememberSaveable`.
- `derivedStateOf` for costly derivations; avoid state writes during composition.

## Decision 2 — Lifecycle and process death

- Any state the user would notice losing must be in `SavedStateHandle` or
  persisted — Android kills backgrounded processes without warning.
- Effects: `LaunchedEffect(key)` for suspend work, `DisposableEffect` for teardown;
  never launch work directly in a composable body.
- Coroutines in `viewModelScope`; cancellation on clear is automatic.
- Collect flows with the lifecycle, or background collection leaks and burns
  battery.

## Decision 3 — Navigation

- Navigation Compose with typed routes (serialisable route classes), single
  `NavHost`.
- Arguments are validated at the destination; a bad deep link must not crash.
- Back behaviour defined for nested flows and bottom sheets.
- Shared element and multi-pane (window size classes) designed, not discovered on
  tablets.

## Decision 4 — Structure and injection

```
app/       wiring, navigation, DI graph
feature/   screen + ViewModel + UI state (one module per feature as it grows)
core/      design system, network, database, analytics
```

- Hilt (or Koin) from the start; constructor injection into ViewModels and
  repositories, no service locator reach-ins from composables.
- Interfaces at module boundaries; the repository hides Room/Retrofit from the UI.
- Modules for build speed and ownership, not for purity.

## Decision 5 — Platform integration

- Permissions requested in context; handle denial and "don't ask again".
- Background work via WorkManager with constraints and retry policy — not a
  foreground service for periodic sync.
- Compose previews with fake state for every screen; no preview touching the
  network.
- Material 3 theming with dynamic colour plus a brand fallback; dark mode from day
  one.
- Predictive back, per-app language, and large-screen resizability are platform
  expectations, not extras.

## Decision 6 — Quality bar

- Unit tests for ViewModels (coroutine test dispatcher), Compose UI tests for core
  flows, macrobenchmark for startup and list scrolling.
- Baseline profiles for release builds; without them Compose startup is slow.
- R8 with keep rules verified; test the minified build, not just debug.

## Failure modes at scale

- Screen state in `remember` and lost on rotation or process death.
- Flow collected outside the lifecycle, updating a destroyed screen.
- A composable that calls the repository directly in the body.
- Recomposition storms from unstable parameters (lists, lambdas created inline).
- Debug build is fine, minified release crashes on a missing keep rule.

## Verification receipts

1. UiState type per screen with all four states handled.
2. Process-death test: kill from background, state restored.
3. Macrobenchmark numbers for startup and the heaviest list.
4. Release (minified) build exercised through core flows.
5. Compose previews and tests covering loading, empty and error.
