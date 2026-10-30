---
name: android-architect
description: Architect-level Android guidance — Compose versus View system boundaries, lifecycle and configuration changes, state holders and unidirectional data flow, coroutine and work scheduling discipline, and the process-death and permission realities of the platform. Use for Android apps.
license: MIT
compatibility: Android 8+/API 26+; Kotlin; Jetpack Compose
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/platforms-architect/android-architect
  crusor-origin: original
  crusor-sources: "developer.android.com/guide; developer.android.com/jetpack/compose; developer.android.com/topic/architecture"
  crusor-triggers: "android, kotlin, jetpack compose, viewmodel, gradle android, android app, coroutines"
  crusor-verified-on: "2026-10-30"
---

# Android Architect

Android gives you **a process that can die at any time and a very wide device
range**. Architecture is about surviving both.

## When to use

- Building or reviewing an Android app.
- Choosing Compose vs the View system, or migrating.
- Lifecycle, background work or state loss problems.

## When NOT to use

- Cross-platform apps where the shared layer dominates.

## Decision 1 — Compose vs Views

| Need | Choose |
|---|---|
| new UI, most screens | Jetpack Compose |
| legacy screens, complex custom views | View system, migrated incrementally |
| interop | `ComposeView` / `AndroidView` at the seam |

- Migrate screen by screen; a half-migrated app is expected, an unplanned one is
  not.
- Compose state hoisting: UI is a function of state; state lives in a holder,
  not in composables.
- No business logic in composables — they must be previewable and testable.

## Decision 2 — Layering

```
ui/ (compose screens, viewmodels)
  domain/ (use-cases, entities — no Android imports)
    data/ (repositories, Room, Retrofit)
      framework (DI modules, platform adapters)
```

- ViewModel holds UI state and survives configuration change — not process
  death.
- One-shot effects (navigation, snackbar) are events, not state that replays.
- DI (Hilt/Koin) wires the graph; screens never construct dependencies.

## Decision 3 — Lifecycle and process death

- Configuration changes recreate activities; state must survive or be restored.
- `SavedStateHandle`/`SavedStateRegistry` for anything the user typed.
- Background work: WorkManager with constraints and backoff — never a `Thread`
  or an alarm.
- Doze and app-standby will defer your timers; design for late, not exact.

## Decision 4 — Concurrency

- Coroutines with structured scopes: `viewModelScope`, `lifecycleScope`;
  cancellation is automatic when the owner dies.
- Dispatchers explicit: `IO` for disk/network, `Default` for CPU, `Main` only
  for UI.
- Flows for streams; `StateFlow` for UI state; one source of truth per screen.
- No blocking calls on the main thread; StrictMode on in debug.

## Decision 5 — Platform realities

- Permissions: request in context, handle permanent denial with a path to
  settings.
- Storage scoped storage rules; no writes outside app directories without SAF.
- Back navigation and predictive back gestures handled by the nav graph.
- Device fragmentation: test on API floor, a mid-tier device and a foldable
  profile.

## Failure modes at scale

- God ViewModels with 40 fields and mixed responsibilities.
- State living in composables, lost on rotation.
- WorkManager chains that run forever because they are never cancelled.
- Two sources of truth (Room + in-memory cache) drifting apart.
- Blocking the main thread with JSON parsing on large payloads.

## Verification receipts

1. Rotation test on every stateful screen.
2. Process-death restore test (developer option "don't keep activities").
3. StrictMode clean in debug; no main-thread disk/network.
4. Offline journey test with WorkManager retry.
5. Baseline profile / startup time and jank trace on a mid-tier device.
