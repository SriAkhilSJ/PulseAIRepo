---
name: mobile-performance-architect
description: Architect-level mobile performance — cold start budgets, frame and jank targets, list and image strategy, memory limits and the jetsam killer, battery and network cost, app size, and the measurement discipline that keeps numbers honest on real devices. Use when an app feels slow, drains battery, or is too big.
license: MIT
compatibility: iOS Instruments, Android Studio Profiler, Flutter DevTools, Hermes/Flipper
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/mobile-performance-architect
  crusor-origin: original
  crusor-sources: "developer.android.com/topic/performance; developer.apple.com/documentation/xcode/improving-your-app-s-performance; docs.flutter.dev/perf"
  crusor-triggers: "mobile performance, cold start, jank, frame drop, app size, memory leak, battery drain, slow list, startup time, anr, slow to start, startup, app keeps crashing on low memory, memory pressure"
  crusor-verified-on: "2026-10-30"
---

# Mobile Performance Architect

Mobile performance is **a budget in milliseconds and megabytes, measured on the
worst device you support** — not on the newest phone in the room.

## When to use

- Users report lag, heat, or drain; ANRs; slow start.
- The app is too large to install over cellular.
- Adding a feature whose cost must be bounded before it ships.

## When NOT to use

- The problem is a backend latency issue visible on all clients.
- Profiling a debug build and concluding anything.

## Decision 1 — Budgets

| Metric | Target |
|---|---|
| cold start to first frame | < 1.5 s mid-tier, < 2.5 s low-end |
| warm start | < 500 ms |
| frame time | < 16.7 ms (60 Hz), < 8.3 ms (120 Hz) |
| jank | < 1% of frames |
| app download | < 30 MB baseline, on-demand for assets |
| memory | well under the OS limit for the oldest supported device |
| battery | no sustained > 5%/hour background use |

Budgets are per screen and per feature, written in the plan, checked in CI where
possible.

## Decision 2 — Start-up

- Measure cold, warm, and hot separately; only cold start is mostly yours.
- Defer everything not needed for first frame: analytics SDKs, heavy DI graphs,
  model loading, remote config.
- No network call blocking first frame; render cached state, revalidate after.
- SDK initialisation on a background thread with explicit ordering.
- Static initialisers and large object graphs are the usual hidden cost.

## Decision 3 — Rendering and lists

- Lists: recycle/virtualise, stable ids, fixed item heights where possible, no
  layout thrash inside the cell.
- Images decode off the main thread, at the size displayed, with a memory-bounded
  cache.
- Avoid nesting scrollables; avoid per-frame allocations in draw paths.
- Animation on the compositor where available (transform/opacity), not layout.
- Measure with the profiler; "feels smooth" on a flagship is not data.

## Decision 4 — Memory

- iOS kills on pressure (jetsam); Android kills in the background. Both are
  silent in crash reports unless you read the termination reason.
- Hold no more than N screens of data; paginate.
- Leaks: retain cycles from closures/listeners/observers; verify with heap dumps
  after navigation churn.
- Large media is streamed/file-backed, not held in memory.

## Decision 5 — Network and battery

- Batch and coalesce requests; respect connectivity and metered networks.
- Backoff and cache headers over polling; no wake-lock abuse.
- Location accuracy tier is a decision: precise GPS costs battery.
- Push instead of background polling wherever possible.
- Measure with the platform's energy instrument during a realistic session.

## Decision 6 — Size

- Strip unused architectures, resources, and locales.
- On-demand asset delivery for media and rarely-used features.
- Fonts subset; vector assets over bitmaps.
- Watch size per release and fail the build on a regression above the threshold.

## Failure modes at scale

- Six SDKs initialised in `Application.onCreate`, 900 ms of the cold start.
- List rebuilt with new ids each refresh, so the recycler never reuses.
- Images decoded at source resolution in a 60 pt avatar.
- A "performance pass" done on an emulator.
- App grew 40 MB in a quarter; nobody noticed until store reviews mentioned it.

## Verification receipts

1. Cold-start measurement on the oldest supported device, with a profile trace.
2. Frame stats during a real scroll of the heaviest list.
3. Memory graph across 10 minutes of navigation and backgrounding.
4. Size report per release with the delta and the largest contributors.
5. Battery measurement for a 30-minute representative session.
