---
name: mobile-release-architect
description: Architect-level mobile release practice — signing and key custody, build flavours and versioning, store review realities, staged rollouts and phased releases, OTA update policy, and the kill switches that make a shipped mistake recoverable. Use when preparing or running mobile releases.
license: MIT
compatibility: App Store Connect / Google Play; EAS or Fastlane; any mobile stack
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/mobile-release-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/app-store/review/guidelines; support.google.com/googleplay/android-developer; docs.expo.dev/eas"
  crusor-triggers: "app store, play store, signing, provisioning, staged rollout, phased release, ota update, mobile ci"
  crusor-verified-on: "2026-10-30"
---

# Mobile Release Architect

Mobile release is **the only deploy where you cannot undo**. Review takes days,
users update slowly, and old versions live for months.

## When to use

- Setting up signing, CI and store pipelines.
- Planning a phased rollout or an emergency hotfix.
- A release broke something and there is no way back.

## When NOT to use

- Pre-release feature planning (see the platform skills).

## Decision 1 — Signing and keys

- Keys in a managed secret store, never in a repo or a developer laptop.
- iOS: distribution certificate + provisioning profiles automated (Fastlane
  match / EAS credentials), with a documented holder.
- Android: upload key vs app-signing key separated; Play App Signing on.
- Rotation plan exists: losing a key can end a product's ability to update.

## Decision 2 — Build and version policy

- One pipeline builds both platforms from one commit; artefacts archived.
- Version name semantic for humans, build number monotonic and unique per store
  — never reused.
- Flavours per environment with distinct bundle ids; a staging build can never
  be published as production.
- Reproducible builds: pinned toolchain, locked dependencies, recorded image
  digests.

## Decision 3 — Store reality

| Constraint | Architectural consequence |
|---|---|
| review takes 1–7 days | no emergency code fix; plan server-side switches |
| metadata review | privacy labels, permissions, screenshots are release artefacts |
| policy changes | data-collection declarations must match actual SDK behaviour |
| user update lag | old clients coexist for months; API compatibility required |

- Anything that must be instantly fixable ships as server-driven config or a
  feature flag.
- API contracts stay backwards-compatible for the supported client window
  (commonly 6–12 months).

## Decision 4 — Rollout

- Staged rollout (Play: 1% → 5% → 20% → 100%; iOS: phased release over 7 days)
  with explicit gates: crash-free rate, ANR rate, key funnel.
- Automatic halt on regression, not a human watching a dashboard.
- Rollback on mobile is "stop the rollout" — have the button and the threshold
  agreed before launch.
- OTA/JS updates: pinned to runtime version, never for native changes, always
  with a revert path.

## Decision 5 — Observability and support

- Crash-free sessions, ANR rate, cold start, and the top funnel per version.
- Version adoption dashboard: how many users are still on the previous build.
- Support can identify a user's version and platform without asking them.
- Release notes are user-facing and translated where the app is.

## Failure modes at scale

- Signing key on one engineer's laptop, gone when they leave.
- 100% rollout because "it passed QA" — the first regression reaches everyone in
  an hour.
- A server API change breaks the previous app version still installed on 30% of
  devices.
- OTA update shipped to a binary with a different native version → crash loop.
- Store rejection two days before a marketing launch because privacy
  declarations were copied from a template.

## Verification receipts

1. Signing inventory: keys, holders, rotation plan, recovery test.
2. Build reproducibility: same commit → same artefact hash (or documented
   difference).
3. Staged rollout plan with numeric halt thresholds.
4. Backwards-compatibility test against the oldest supported client.
5. Crash-free/ANR baselines per version, monitored after release.
