---
name: kotlin-multiplatform-architect
description: Architect-level Kotlin Multiplatform design — shared domain and data layers, expect/actual boundaries, KMP versus Compose Multiplatform, iOS interop cost, Gradle setup and build times, and the team structure that makes shared code pay. Use when Android and iOS should share logic but not necessarily UI.
license: MIT
compatibility: Kotlin Multiplatform, Compose Multiplatform, Ktor, SQLDelight
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/platforms-architect/kotlin-multiplatform-architect
  crusor-origin: original
  crusor-sources: "kotlinlang.org/docs/multiplatform.html; jetbrains.com/help/kotlin-multiplatform-dev/compose-multiplatform.html; ktor.io/docs"
  crusor-triggers: "kotlin multiplatform, compose multiplatform, shared module, expect actual, sqldelight, ktor client, kmp, shared kotlin, share kotlin, kotlin shared module"
  crusor-verified-on: "2026-10-30"
---

# Kotlin Multiplatform Architect

KMP shares **logic, not UI**. The architecture question is where the shared boundary
stops — because everything you share, you must test on every platform.

## When to use

- Android and iOS teams want one implementation of business rules and data.
- Existing Android app with a Kotlin codebase, adding iOS.
- Heavy domain logic (sync, pricing, validation) that must behave identically.

## When NOT to use

- The UI is the product and platform look-and-feel dominates.
- A small app where two native implementations are cheaper than the toolchain.
- The team has no Kotlin expertise on the iOS side.

## Decision 1 — Shared scope

| Layer | Share? |
|---|---|
| domain entities, use cases | yes |
| repositories, networking, caching | yes |
| validation, formatting rules | yes |
| navigation | usually no |
| UI | only with Compose Multiplatform, deliberately |
| platform APIs (camera, BLE, payments) | no — expect/actual |

- Share the layer that has the most logic and the least platform API surface: usually
  domain + data.
- Compose Multiplatform is a real option for UI, but it is a product decision about
  look-and-feel and hiring, not a technical convenience.

## Decision 2 — Boundaries

- `expect`/`actual` only for genuine platform capabilities (time, UUID, keychain,
  background scheduling); every one is a testing burden.
- Keep platform interop behind interfaces in the shared module; the iOS side consumes
  Swift-friendly APIs.
- Suspend functions map to Swift async; callbacks and flows need explicit bridging.
- No JVM-only libraries in shared code — check the target matrix before adding a
  dependency.

## Decision 3 — Toolchain

- Gradle versions and plugin alignment are the main source of pain; pin and upgrade
  deliberately.
- Build times grow with modules × targets; measure and split only when needed.
- SQLDelight/Room KMP for local persistence, Ktor for networking — but verify iOS
  performance, not just Android.
- CI builds both platforms on every PR; a shared module that compiles only for Android
  is a trap.

## Decision 4 — iOS integration cost

- Swift/Objective-C interop hides Kotlin types: generics, sealed classes, and
  coroutines need explicit mapping.
- Binary size increases; measure the framework size in the iOS build.
- Debugging across the boundary requires both toolchains — budget for the learning
  curve.
- Snapshot/preview workflows on iOS do not understand Kotlin: keep UI native if that
  workflow matters.

## Decision 5 — Team structure

- Shared module needs an owner; without one it becomes unowned and stale.
- Publishing a versioned shared library (internal repo) beats a source-linked module
  in two projects.
- Feature teams contribute to shared code through review, like a library.

## Failure modes at scale

- Everything shared including UI; every platform bug is now a cross-team bug.
- Shared module compiles on Android only; iOS integration broken for a week.
- JVM dependency pulled into shared code; iOS target silently unbuildable.
- Build times of 12 minutes for a one-line change.
- No owner; the shared module diverges into two forks.

## Verification receipts

1. Layer diagram showing shared versus platform-specific code.
2. Build times for both targets, measured on a clean checkout.
3. Dependency audit: every shared library supports all targets.
4. One expect/actual capability tested on both platforms.
5. iOS framework size and startup impact measured.
