---
name: vitest-architect
description: Architect-level Vitest guidance — what belongs in unit versus component tests, mocking only at boundaries with MSW, fake timers and async determinism, coverage as a signal rather than a target, and keeping the suite fast enough to run on every save. Use when setting up or repairing a frontend unit/component test suite.
license: MIT
compatibility: Vitest 1/2+; jsdom or happy-dom; @testing-library
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/vitest-architect
  crusor-origin: original
  crusor-sources: "vitest.dev; testing-library.com/docs/queries/about; mswjs.io"
  crusor-triggers: "vitest, unit tests, testing library, msw, mocking, coverage, fake timers, component tests"
  crusor-verified-on: "2026-10-30"
---

# Vitest Architect

The unit/component layer is where you get **fast, precise failure**. Its enemies
are over-mocking, snapshot sprawl, and tests that assert implementation instead
of behaviour.

## When to use

- Setting up the fast test layer of a frontend.
- A suite is slow, brittle, or green while the app is broken.
- Deciding where a test belongs (unit, component, E2E — see
  `playwright-architect`).

## When NOT to use

- Full user journeys (E2E), or visual regression (screenshot tooling).

## Decision 1 — What each test asserts

| Layer | Asserts |
|---|---|
| pure unit | rules, reducers, formatters, parsers |
| hook/composable | state transitions over time |
| component | rendered output for a given input + user interaction |
| integration | component + real data layer (mocked network) |

- Test behaviour through the DOM/API the user or caller uses — not internal
  state, not private methods.
- One behaviour per test; the name states the behaviour, not the function.

## Decision 2 — Mock at boundaries only

- Network: MSW with handlers per endpoint — never `vi.mock` a fetch module.
- Time: `vi.useFakeTimers()` for debounce/polling; advance explicitly.
- Modules: mock third-party SDKs and browser APIs, not your own code. If your
  own module needs mocking to test, the boundary is wrong.
- Global mock bleed is a suite-wide hazard: restore in `afterEach`.

## Decision 3 — Component tests that survive refactors

- Query by role/label (`getByRole('button', {name: /save/i})`), not by test id
  or class.
- Use `userEvent`, not `fireEvent`, so focus/keyboard paths are exercised.
- Assert visible outcome and accessible state, not class lists.
- Snapshots only for stable, intentional output — never for whole pages.

## Decision 4 — Speed and CI

- Target: full unit+component suite under ~60 s locally.
- Parallel by file; isolate globals; no shared mutable fixtures.
- Coverage is a **signal** (untested branches in critical modules), not a gate
  at 100%. Gate new code, not legacy.
- Flaky unit test = broken test; fix or delete. Never retry in-suite.

## Decision 5 — What not to test

- Framework behaviour, library internals, trivial getters.
- Implementation details that a refactor legitimately changes.
- The same rule at three layers (that is how suites rot).

## Failure modes at scale

- 400 tests, 90% mocked, none of them catch a real regression.
- `vi.mock('../api')` in every file → the wiring is never tested.
- Fake timers leaking between files → order-dependent failures.
- Snapshot files with 2000 lines nobody reads, updated with `-u` blindly.
- Suite takes 8 minutes, so nobody runs it before pushing.

## Verification receipts

1. Suite duration and file count recorded; CI shards balanced.
2. Mock audit: third-party boundaries only (MSW for HTTP).
3. A deliberate bug in a core rule is caught by a unit test.
4. No `.only`, no skipped tests without a linked issue.
5. Coverage report reviewed for critical modules, not for the percentage.
