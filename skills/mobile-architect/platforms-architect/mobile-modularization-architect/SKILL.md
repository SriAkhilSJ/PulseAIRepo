---
name: mobile-modularization-architect
description: Architect-level app modularisation — module boundaries by feature and layer, dependency rules and API surfaces, build-time impact, dynamic feature delivery, and the ownership model that makes modules worth their cost. Use when an app has outgrown a single module.
license: MIT
compatibility: Gradle modules, Xcode frameworks/Swift packages, Bazel
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/platforms-architect/mobile-modularization-architect
  crusor-origin: original
  crusor-sources: "developer.android.com/topic/modularization; developer.apple.com/documentation/xcode/creating-a-multiplatform-framework; developer.android.com/guide/playcore/feature-delivery"
  crusor-triggers: "modularization, gradle modules, swift packages, xcode framework, dynamic feature, module boundaries, build times, dependency graph, modularize, modularise, split into modules, feature module"
  crusor-verified-on: "2026-10-30"
---

# Mobile Modularisation Architect

Modules buy **boundaries and build parallelism**, at the cost of ceremony. Split for a
reason; every module has an owner and a tax.

## When to use

- Build times over ~5 minutes on the main path.
- Multiple teams editing the same module daily.
- Features that should ship independently or on demand.

## When NOT to use

- A small app with one team — modules add configuration and indirection for nothing.
- Splitting before you have a dependency problem; measurement comes first.

## Decision 1 — Boundary type

| Split by | Use when |
|---|---|
| feature | teams own vertical slices |
| layer (data/domain/ui) | strict dependency direction matters |
| library/SDK | reused across apps |
| dynamic feature | on-demand install, large optional flows |

- Feature modules with internal layers beat layer-per-module-everywhere at small scale.
- One module per screen is over-fragmentation; one module per bounded feature is the
  usual sweet spot.

## Decision 2 — Dependency rules

```
app → feature-*  →  core-ui / core-domain
                     ↑
             feature-* never depends on feature-*
```

- Features communicate through the app module or a shared domain API, not by direct
  dependency.
- Enforce with build tooling (`implementation` vs `api`, or a lint rule); documented
  rules decay in a quarter.
- Public surface = a small API module per feature; internals stay `internal`.

## Decision 3 — Build performance

- Measure clean and incremental builds before and after each split.
- Gradle configuration cache and Kotlin incremental compilation matter more than module
  count.
- iOS: Swift packages and frameworks parallelise better than one target with folders.
- A split that increases build time is a net loss — revert it.

## Decision 4 — Dynamic delivery

- Dynamic features for large, rarely used flows (onboarding extras, editor tools).
- Every dynamic module adds install-time state and failure modes; test on low-end
  devices and slow networks.
- Base module size is the download metric users feel; keep it lean.

## Decision 5 — Ownership

- Each module has an owner team and a CODEOWNERS entry; orphan modules are deleted.
- Module boundaries are architecture: changes go through review.
- Document the graph; a diagram nobody updates is fiction — generate it from the build.

## Failure modes at scale

- 80 modules, 9-minute builds, no ownership.
- Features depending on each other's internals; boundaries are decorative.
- One "core" module that everything imports and everyone edits.
- Dynamic feature that breaks on first launch for 2% of devices.
- Modules split by layer only; every feature change touches five modules.

## Verification receipts

1. Module graph generated from the build, with ownership.
2. Clean and incremental build times before and after the split.
3. Dependency rule violation caught by tooling in a test PR.
4. Dynamic feature installed and exercised on a slow network.
5. Base app download size tracked per release.
