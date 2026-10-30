---
name: mobile-build-architect
description: Architect-level build pipeline design for mobile — Gradle and Xcode build configuration, caching and remote build caches, signing and CI secrets, flavours and schemes, and the feedback-loop budgets that decide how often the team ships. Use when build times or build reliability are the constraint.
license: MIT
compatibility: Gradle, Xcode/xcodebuild, Fastlane, Bitrise/GitHub Actions
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/delivery-architect/mobile-build-architect
  crusor-origin: original
  crusor-sources: "docs.gradle.org/current/userguide/build_cache.html; developer.apple.com/documentation/xcode; docs.fastlane.tools"
  crusor-triggers: "mobile build, gradle config, xcode build, build cache, fastlane, flavours, schemes, ci signing, remote cache, slow build, build takes, build time, long build"
  crusor-verified-on: "2026-10-30"
---

# Mobile Build Architect

Build time is **how often the team can verify a change**. Every architectural choice
that adds minutes compounds across a year.

## When to use

- Builds exceed ~5 minutes locally or ~15 in CI.
- Build failures are flaky or unexplained.
- Adding flavours, schemes, or signing to a pipeline.

## When NOT to use

- A prototype with one developer and two-minute builds.

## Decision 1 — Configuration

- Gradle: version catalogs for dependencies, convention plugins for shared config,
  configuration cache on.
- Xcode: one shared scheme per shipping configuration; avoid per-developer scheme
  edits.
- Flavours/schemes per environment, not per developer branch.
- Keep `build.gradle` declarative; imperative build logic is slow and unreadable.

## Decision 2 — Caching

- Gradle build cache (local + remote) and configuration cache; measure the hit rate.
- Xcode derived data caching and ccache-style remote caching in CI.
- Dependency resolution offline-first in CI; a network flake should not fail a build.
- Cache keys must include build config; wrong keys produce silently stale artefacts.

## Decision 3 — CI shape

- PR job: compile, unit tests, lint, and a debug build of the changed targets.
- Merge job: full test suite, release build, artefact upload.
- Signing keys in the CI secret store; never in the repo or on a developer machine by
  default.
- Reproducible release builds: pinned toolchain versions, locked dependencies.

## Decision 4 — Feedback budgets

| Stage | Target |
|---|---|
| incremental local build | < 30 s |
| clean local build | < 3 min |
| PR CI to first result | < 10 min |
| full release pipeline | < 30 min |

- Publish timings per stage; the slowest stage is the next project.
- Parallelise test shards and module builds; do not just buy bigger runners.

## Decision 5 — Reliability

- Flaky builds get quarantined and fixed, like flaky tests.
- Toolchain upgrades are scheduled work with a rollback plan.
- Keep an offline-capable path for dependency resolution; registries go down.

## Failure modes at scale

- Nine-minute CI with a 3-minute dependency download every run.
- Two engineers with different Xcode versions; "works on my machine".
- Build cache disabled after one bad key, never re-enabled.
- Signing certificates on a shared drive.
- Flavour per customer; build matrix explodes to 40 variants.

## Verification receipts

1. Timing breakdown per build stage, local and CI.
2. Cache hit rates for Gradle and Xcode.
3. Clean-checkout build reproduced on a second machine.
4. Signing verified in CI with a release artefact.
5. Build failure rate over the last 30 days.
