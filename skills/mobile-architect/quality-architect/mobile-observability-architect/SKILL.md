---
name: mobile-observability-architect
description: Architect-level mobile observability — crash reporting and symbolication, ANR and watchdog detection, network and startup telemetry, session breadcrumbs, sampling and privacy, and the release-health gate that stops a bad build from rolling out. Use when you need to know what the app does in the field.
license: MIT
compatibility: Crashlytics, Sentry, Embrace, New Relic, Datadog RUM
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/quality-architect/mobile-observability-architect
  crusor-origin: original
  crusor-sources: "firebase.google.com/docs/crashlytics; docs.sentry.io/platforms/apple; developer.android.com/topic/performance/vitals/anr"
  crusor-triggers: "crash reporting, crashlytics, anr, symbolication, mobile telemetry, session replay, release health, dSYM, obfuscation mapping, crash reports, unreadable crash, symbolicate"
  crusor-verified-on: "2026-10-30"
---

# Mobile Observability Architect

You cannot reproduce a user's device, OS version, memory state, and network. In the
field, **telemetry is the only debugger you have**.

## When to use

- Shipping to a large or heterogeneous user base.
- Crash triage that stalls on "cannot reproduce".
- Staged rollouts that need a health signal.

## When NOT to use

- Pre-release development where you control the device.
- Low-traffic internal apps — logs may suffice.

## Decision 1 — Signals

| Signal | Catches |
|---|---|
| crash reports | fatal errors, stack traces |
| non-fatal errors | caught exceptions, failed states |
| ANR / watchdog | main-thread blocking, hangs |
| performance traces | startup, screen load, jank |
| network logs | failing endpoints, slow calls |
| session breadcrumbs | what the user did before |

- Symbolication must work: upload dSYMs (iOS) and mapping files (Android) on every
  build, or crashes are unreadable noise.
- Track "crash-free users" and "ANR-free sessions" as release metrics.

## Decision 2 — Context

- Attach: app version, build number, OS, device model, locale, network type, account
  tier (not identity).
- Breadcrumbs for navigation and key actions, with a bounded buffer.
- Correlation ids from API responses, so a client error maps to a server trace.
- Never log PII, tokens, or full request bodies.

## Decision 3 — Sampling and volume

- Sample non-fatal events and traces; keep 100% of fatal crashes.
- Budget ingestion cost per MAU; a chatty SDK can cost more than the backend.
- Client-side buffering with flush-on-background; losing the last few events is
  acceptable, losing the crash is not.

## Decision 4 — Release health

- A rollout gate: crash-free sessions below threshold triggers a halt.
- Staged rollout with metric comparison against the previous version for the same
  cohort.
- Alert on new crash signatures (a new top-1 crash is a stop signal), not just volume.
- Link the release tag to the build so the dashboard answers "which version".

## Decision 5 — Privacy and compliance

- Consent for any telemetry beyond crash diagnostics in regulated markets.
- Disclose third-party SDK collection; some collect device identifiers by default.
- Data retention per policy; crash data often holds screenshots or user text — scrub.

## Failure modes at scale

- Crashes reported but unsymbolicated; the top signature is a memory address.
- ANRs invisible because only crashes are instrumented.
- Telemetry SDK initialised before consent; a compliance finding.
- Rollout continues at 8% crash rate because nobody wired the gate.
- Logs contain user emails; the incident is a privacy one, not a bug.

## Verification receipts

1. Crash and ANR rates for the current release, with symbolication verified.
2. Breadcrumb and context fields reviewed for PII.
3. Sampling configuration and estimated ingestion cost.
4. Rollout gate configured and tested with a simulated failure.
5. One real crash triaged end to end from report to fix.
