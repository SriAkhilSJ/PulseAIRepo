---
name: wearables-architect
description: Architect-level watch and wearable design — glanceable interaction models, complication and tile strategy, phone-watch data sync and connectivity, battery and sensor budgets, and the health-data privacy rules that apply to wrist-worn devices. Use when the product extends to a watch or band.
license: MIT
compatibility: watchOS, Wear OS, HealthKit, Health Connect
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/devices-architect/wearables-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/design/human-interface-guidelines/designing-for-watchos; developer.android.com/training/wearables; developer.apple.com/documentation/healthkit"
  crusor-triggers: "wearable, watchos, wear os, smartwatch, complication, tile, healthkit, health connect, watch app, glanceable"
  crusor-verified-on: "2026-10-30"
---

# Wearables Architect

A watch app is **not a small phone app**. Interactions last seconds, the screen is
often off, and connectivity is intermittent by design.

## When to use

- Notifications or quick actions belong on the wrist.
- Health/fitness tracking or sensor data collection.
- A companion experience to an existing phone app.

## When NOT to use

- The task needs more than a few seconds of interaction — keep it on the phone.
- The value is a static complication with no interaction (consider a widget instead).

## Decision 1 — Interaction model

| Surface | Purpose |
|---|---|
| notification | alert with one action |
| complication/tile | glanceable status, tap to open |
| app screen | 5–15 second task |
| dictation/voice | input without a keyboard |

- One primary action per screen; scroll, do not nest.
- Assume the screen turns off mid-task: persist state immediately.
- Complications are the highest-value surface — most users never open the app.

## Decision 2 — Data and sync

- The phone is usually the source of truth; the watch caches a small projection.
- Use the platform's sync mechanism (`WatchConnectivity`, Wear Data Layer), and design
  for long disconnection.
- Queue writes made offline; reconcile on reconnect with idempotent operations.
- Do not attempt large payloads; send ids and fetch on demand.

## Decision 3 — Battery and sensors

- Sensor sampling rates dominate battery: choose the lowest rate the feature needs.
- Background workouts need explicit session APIs; otherwise the OS suspends you.
- Measure: a watch app draining 20% per hour is a one-star review.
- Thermal and battery state should degrade gracefully (reduce sampling, warn user).

## Decision 4 — Health data

- HealthKit / Health Connect permissions are per data type and highly sensitive.
- Never upload health data without explicit consent; store minimally, encrypt.
- Read-only access for most features; write access only when the app is the source.
- Regulatory classification matters in some markets (medical device claims).

## Decision 5 — Release

- Watch apps ship with the phone app; version alignment matters.
- Review the watch-specific screenshots and complications in store metadata.
- Test on a real device: simulators misrepresent battery, connectivity, and sensor
  behaviour.

## Failure modes at scale

- Phone feature ported wholesale to a 40 mm screen; unreadable.
- Complication stale because refresh budget was misunderstood.
- Offline workout lost because writes were only sent on reconnect.
- Health data uploaded without consent; a compliance incident.
- Watch app battery drain from 1 Hz sensor polling.

## Verification receipts

1. Surface inventory: complication, tile, screens, notifications.
2. Sync behaviour tested through a 30-minute disconnection.
3. Battery measurement for a representative session.
4. Health permission and consent flow verified.
5. Store metadata includes watch screenshots and complications.
