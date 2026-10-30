---
name: desktop-telemetry-architect
description: Architect-level desktop telemetry — crash reporting and symbol upload per platform, opt-in consent and privacy expectations, session and performance metrics, release health gates for staged rollouts, and the offline buffering a desktop app needs. Use when you must know what the app does on users' machines.
license: MIT
compatibility: Sentry, Crashpad, Backtrace, custom endpoints
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/quality-architect/desktop-telemetry-architect
  crusor-origin: original
  crusor-sources: "docs.sentry.io/platforms/native; chromium.googlesource.com/crashpad; learn.microsoft.com/windows/win32/wer"
  crusor-triggers: "desktop telemetry, crash reporting, crashpad, sentry native, symbol upload, release health, usage analytics desktop, opt in telemetry, desktop crash, crash reports, usage analytics"
  crusor-verified-on: "2026-10-30"
---

# Desktop Telemetry Architect

Desktop users are **guests on their own machines**. Telemetry here is a consent and
privacy problem before it is a monitoring problem.

## When to use

- Shipping to end users outside a managed fleet.
- Crash reports that cannot be symbolicated.
- Staged rollout that needs a health signal.

## When NOT to use

- Fully air-gapped or regulated deployments where collection is prohibited — provide
  local logs instead.

## Decision 1 — Consent model

- Opt-in (or clearly disclosed opt-out) depending on jurisdiction and product type;
  enterprise deployments often require off-by-default.
- A visible setting that actually works, plus a documented data list.
- No telemetry before consent is recorded, including crash handlers if the policy says
  so.
- Provide an export/log path for users who decline.

## Decision 2 — Crash reporting

- Native crash handler (Crashpad/Breakpad/WER) plus the language runtime's handler;
  both are needed for native and managed crashes.
- Symbol files uploaded per build (PDB/dSYM/DWARF); unsymbolicated reports are noise.
- Minidumps with privacy scrubbing: memory dumps can contain user data — scrub or
  disable full dumps.
- Correlate crashes with app version, OS build, and the last logged action.

## Decision 3 — Product telemetry

- Event taxonomy as in mobile (`mobile-analytics-architect`): named, typed, documented.
- Session and performance: startup time, window open time, IPC latency.
- Feature usage to guide investment; no keystroke or content capture, ever.
- Sampling for high-volume events; batch and send on idle.

## Decision 4 — Offline behaviour

- Buffer locally with a bounded queue; flush on network availability and on quit.
- Do not block shutdown on a network call; write to disk and send next launch.
- Deduplicate resent events with an id.

## Decision 5 — Release health

- Crash-free sessions and startup failures per version, compared against the previous
  release.
- Staged rollout halted automatically on threshold breach.
- Alert on new crash signatures, not just volume.

## Failure modes at scale

- Telemetry on by default in a regulated market; a compliance finding.
- Crashes unsymbolicated because symbol upload was manual.
- Full memory dumps shipped to a third party; user data leaked.
- Shutdown blocked waiting for a flush; app appears hung.
- Rollout continues at 6% crash rate because nobody wired the gate.

## Verification receipts

1. Consent flow with the exact data collected listed.
2. Symbol upload automated and verified against one real crash.
3. Dump scrubbing policy documented and tested.
4. Offline buffer and resend verified.
5. Rollout gate configured and exercised.
