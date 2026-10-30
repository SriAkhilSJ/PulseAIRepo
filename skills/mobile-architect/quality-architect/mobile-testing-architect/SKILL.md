---
name: mobile-testing-architect
description: Architect-level mobile testing — the pyramid that fits apps (unit, component, integration, device E2E), what to fake at the boundary, device and OS matrix strategy, flakiness control, snapshot testing, and the release gate that catches what CI cannot. Use when structuring tests for an app across platforms.
license: MIT
compatibility: XCTest, JUnit/Espresso, Detox, Maestro, Appium, Firebase Test Lab
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/quality-architect/mobile-testing-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/xctest; developer.android.com/training/testing; wix.github.io/Detox; maestro.dev"
  crusor-triggers: "mobile testing, ui test, espresso, xctest, detox, maestro, device farm, flaky test, snapshot test, test matrix, appium"
  crusor-verified-on: "2026-10-30"
---

# Mobile Testing Architect

Mobile tests fail for reasons web tests never see: **devices, OS versions, permissions,
backgrounding, and the store binary**. The pyramid is the same; the boundaries are
not.

## When to use

- Structuring tests for a new app or an untested one.
- E2E suites that are slow and flaky.
- Choosing what runs on a device farm versus locally.

## When NOT to use

- Server-side logic → web backend testing books.

## Decision 1 — The pyramid, adjusted

| Layer | Share | Runs |
|---|---|---|
| unit (domain, mappers, reducers) | 60–70% | every commit, seconds |
| component/UI (single screen, fakes) | 20% | every commit, minutes |
| integration (DB + sync + network fake) | 10% | every commit or PR |
| E2E on device (critical paths) | 5–10 scenarios | PR or nightly, device farm |

- E2E is expensive and flaky by nature: keep it to the money paths (login, core
  task, purchase, restore).
- Every bug fixed gets a test at the **lowest** layer that can catch it.

## Decision 2 — Fakes at the boundary

- Fake at the repository/API interface, not at the HTTP library — fakes must
  express domain scenarios ("offline", "conflict", "401").
- One contract test ensures the fake matches the real client's shape.
- Clock, id generator, and connectivity are injected; otherwise tests are
  untestable by construction.
- Local database tests run against a real engine (in-memory SQLite), not a mock —
  SQL behaviour is the thing you are testing.

## Decision 3 — Device and OS matrix

- Support the two most recent OS majors for features, plus the oldest you promise
  to run on for a smoke test.
- Screen sizes: smallest, largest, and a tablet if supported.
- One low-end Android device — it finds what flagships hide.
- Real devices for anything involving camera, BLE, biometrics, push, or payments;
  simulators for the rest.

## Decision 4 — Flakiness

- No `sleep`; wait on conditions or ids, with a timeout.
- Animations disabled in E2E; time and randomness controlled.
- Each test seeds its own state; no ordering dependence; reset the app between tests.
- Quarantine flaky tests automatically and fix within a sprint — a suite people
  re-run "just in case" has stopped working as a gate.
- Track flake rate per test; treat > 2% as a defect.

## Decision 5 — Snapshots and visual checks

- Snapshot tests on the design system components, not on whole screens with dynamic
  data.
- Run at every supported text scale and in dark mode.
- Golden images are per platform/OS-version; keep the matrix small.

## Decision 6 — The release gate

- CI green is necessary, not sufficient: a smoke pass on a real device build,
  signed the same way as release.
- Test migrations: upgrade from the previous release with real data in place.
- Test the upgrade path and the store binary, not just a debug build.
- Crash-free rate in the wild is the final test; wire it to an alert.

## Failure modes at scale

- 200 E2E tests, 40 minutes, 30% flaky, ignored by everyone.
- Unit tests mock everything, so nothing about the real dependencies is verified.
- Only iPhone 16 and Pixel 9 in the matrix; the low-end market breaks first.
- Migration untested: v2.3 crashes for every user upgrading from v2.1.
- Snapshot suite updated blindly with `--update-snapshots` to make CI green.

## Verification receipts

1. Pyramid counts per layer, with the E2E list named.
2. Contract test tying the fake to the real client.
3. Device/OS matrix documented and reflected in CI configuration.
4. Flake report with quarantine policy and current rate.
5. Upgrade test from the last shipped version, executed.
