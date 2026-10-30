---
name: playwright-architect
description: Architect-level Playwright guidance — what belongs in E2E versus unit/component tests, fixture and page-object boundaries, deterministic waits and network control, auth and seeded state, CI parallelism and flake policy. Use when designing or repairing a browser test suite.
license: MIT
compatibility: Playwright 1.40+; any frontend stack
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/playwright-architect
  crusor-origin: original
  crusor-sources: "playwright.dev/docs/best-practices; playwright.dev/docs/test-fixtures"
  crusor-triggers: "playwright, e2e test, end-to-end, browser test, flaky test, e2e suite, browser automation, trace viewer"
  crusor-verified-on: "2026-10-30"
---

# Playwright Architect

E2E is the most expensive layer per assertion. Architecture is the discipline of
**spending it only on journeys that must not break** — and making those
deterministic.

## When to use

- Designing the browser-test layer for a web app.
- A suite is slow, flaky, or failing without a product bug.
- Deciding where a test belongs: unit, component, or E2E.

## When NOT to use

- Testing pure functions or component rendering (unit/component layer).
- Load testing and visual-regression-at-scale (different tools and budgets).

## Decision 1 — The test pyramid, stated plainly

| Layer | Owns | Budget |
|---|---|---|
| unit | rules, formatting, reducers | thousands, ms |
| component | one component's states | hundreds, ms |
| E2E | critical journeys (login, checkout, publish) | tens, minutes |
| visual | layout regressions on key pages | few, stable pages |

- If a bug can be caught at a lower layer, it does not get an E2E test.
- Every E2E test names the business journey it protects.

## Decision 2 — Fixtures and page objects

- One fixture per *actor* (anonymous user, signed-in user, admin), each
  producing an authenticated context — auth setup runs once, reused via storage
  state.
- Page objects hold **locators and user-level actions**, never assertions about
  business rules (those live in the test).
- Locators: role + accessible name (`getByRole`), then test ids. Never CSS
  chains into component internals.
- Data setup through API/seed, not by clicking through the UI.

## Decision 3 — Determinism

- No `waitForTimeout`. Wait on state: `expect(locator).toBeVisible()`, URL, or
  a network response.
- Control the network: mock third parties, stub failures and slow responses to
  test the sad path deliberately.
- Freeze time and randomise seeds where output depends on them.
- Each test creates its own data and cleans up; no ordering dependencies.

## Decision 4 — CI reality

- Shards in parallel; retries limited (1) and **reported**, never used to hide
  flake.
- Trace + video on first retry; artefacts uploaded.
- Quarantine policy: a test failing intermittently twice is fixed or deleted
  within a sprint — a permanent `@flaky` tag is a broken gate.
- Runs on every PR for the smoke subset; full suite on main/nightly.

## Failure modes at scale

- A 40-minute suite nobody runs locally.
- Sleeps everywhere → 5% flake rate → team ignores red.
- Page objects with 300 methods, mirroring the DOM.
- Tests that depend on shared seed data and pass only in order.
- E2E used to verify styling that a screenshot test covers in 200 ms.

## Verification receipts

1. Flake audit: pass rate over the last 50 runs per test; zero unexplained.
2. Suite duration and shard balance recorded.
3. Trace artefacts present on retry.
4. Every critical journey covered exactly once (no duplicates).
5. `waitForTimeout` count in the suite: zero.
