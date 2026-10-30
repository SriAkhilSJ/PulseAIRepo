---
name: desktop-update-architect
description: Architect-level desktop update design — update channels and staged rollout, delta and full packages, signature verification and rollback, migration of local data on upgrade, enterprise and offline installs, and the failure behaviour when an update is half applied. Use when the app must update itself after users have installed it.
license: MIT
compatibility: electron-updater, Tauri updater, Sparkle, MSIX, MSI, snap/flatpak
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/desktop-update-architect
  crusor-origin: original
  crusor-sources: "electron.build/auto-update; v2.tauri.app/plugin/updater; sparkle-project.org; learn.microsoft.com/windows/msix"
  crusor-triggers: "auto update, updater, update channel, delta update, rollback, staged rollout, forced update, electron-updater, sparkle, app upgrade"
  crusor-verified-on: "2026-10-30"
---

# Desktop Update Architect

An updater is **the only code that runs before your code exists**. If it is wrong,
users lose data, not just a feature.

## When to use

- Shipping an app that updates itself.
- Adding channels (stable/beta), staged rollout, or forced-update policy.
- Data migrations tied to app versions.

## When NOT to use

- Store-distributed apps where the store handles updates (still read the data
  migration sections).
- Web apps — deployment is the update.

## Decision 1 — Mechanism

| Mechanism | Fit |
|---|---|
| built-in auto-updater (Squirrel/electron-updater/Tauri) | consumer apps, frequent releases |
| OS package (MSIX/MSI, pkg, snap/flatpak) | enterprise, managed fleets, admin control |
| Sparkle/appcast | macOS apps outside the store |
| manual download | rarely; support cost is permanent |

- Sign every package; the updater must verify the signature before applying.
- Update over HTTPS with an integrity hash and a pinned key.
- Enterprise/MDM deployments: respect "managed, do not self-update" and provide a
  silent install path.

## Decision 2 — Channels and rollout

- Channels: stable, beta, internal. The channel is a persisted setting, not a
  build-time flag alone.
- Staged rollout by percentage or cohort, with a halt switch on error/crash-rate
  telemetry.
- Never auto-update a fleet on a Friday afternoon; schedule windows are part of
  the design.
- Version checks are cheap; package downloads are not. Poll on startup then daily.

## Decision 3 — Applying an update

- Download in the background, apply on restart with a clear prompt.
- Delta updates where supported; full package as fallback.
- The apply step must be atomic: staging area + swap, not overwrite-in-place.
- Crash during apply → next launch detects the half-state and repairs or rolls
  back.
- Refuse to update while unsaved work exists, or offer "save and restart".
- Rollback keeps the previous version installed until the new one reports healthy.

## Decision 4 — Data migrations

- Schema version stored in the local database, not inferred from app version.
- Migrations forward-only, idempotent, and wrapped in a transaction where possible.
- Back up the database before a migration; keep it until the first successful
  launch on the new version.
- A downgrade path is a real scenario (rollback after a bad release): either
  support reading the older schema or refuse to start with a clear message.
- Test migration on a real, large user database — not the dev fixture.

## Decision 5 — Failure behaviour

- Offline or blocked CDN: continue working, retry later, never block launch.
- Signature mismatch or corrupt download: discard, log, alert, do not retry blindly.
- Update loop (fails, restarts, retries): bounded attempts, then surface a
  diagnostic and a manual link.
- Telemetry: version adoption, failure rate per stage, time-to-update after
  release.

## Failure modes at scale

- Signature check disabled in a build "temporarily"; it never comes back.
- Migration crashes at launch for 5% of users with the oldest data.
- Rollback impossible: the new version upgraded the database irreversibly.
- Forced update with no offline path, bricking air-gapped customers.
- Crash at apply time leaving a half-installed app that will not start.

## Verification receipts

1. Signed package verified on a machine with the signature check enabled.
2. Staged rollout halted mid-flight and confirmed.
3. Migration tested on a real production-size database copy.
4. Rollback rehearsed: install previous version, data intact.
5. Update failure injection: corrupt package, offline, and interrupted apply.
