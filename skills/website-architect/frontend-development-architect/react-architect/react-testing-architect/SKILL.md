---
name: react-testing-architect
description: Architect-level React test strategy — deciding what belongs in type checks, unit, component, integration and end-to-end tests, where the network boundary is mocked, how fixtures and factories are owned, and which flake and runtime budgets the suite must respect. Use when designing a test suite or when tests are slow, brittle, or passing while the app is broken.
license: MIT
compatibility: React 18+; Vitest or Jest, React Testing Library, Playwright
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/react-architect
  crusor-origin: original
  crusor-sources: "testing-library.com/docs/queries/about; playwright.dev/best-practices; vercel-labs/agent-skills@063bee94 (react-best-practices)"
  crusor-verified-on: "2026-10-30"
  crusor-triggers: "testing, vitest, jest, testing-library, playwright, msw, e2e, coverage, flake"
---

# React Testing Architecture

A test suite is an architecture document. If the suite needs a rendered DOM to
prove a business rule, the rule probably lives in the wrong layer.

## When to use

- Starting a suite, or when coverage is high and production still breaks.
- When tests are rewritten every time a component's internals change.
- When deciding whether a behaviour needs RTL, an integration test, or E2E.
- When CI time or flake rate is the actual problem.

## When NOT to use

- Fixing a single assertion in an already-sound suite.
- Pure styling work with no behaviour contract.

## The layers and their jobs

| Layer | Proves | Tool | Budget |
|---|---|---|---|
| Types | contracts between modules | `tsc --noEmit` | seconds |
| Unit | pure logic: reducers, formatters, validators, selectors | Vitest | milliseconds |
| Component | a component's observable behaviour | RTL | tens of ms |
| Integration | a feature against a mocked network boundary | RTL + MSW | ~100 ms |
| E2E | the user journey through a real browser + real server | Playwright | seconds |

Rule of thumb: **push every assertion down to the cheapest layer that can prove
it.** A validation rule tested through a browser is a suite that will be slow and
still miss the rule.

## What belongs where

- **Unit**: business rules, state machines, money/date logic, permission
  matrices, parsers. No React imports.
- **Component**: rendering branches, disabled/loading/empty/error states,
  keyboard interaction, accessible name/role. Query by role and name.
- **Integration**: form → submit → request shape → success/error UI, with the
  network mocked at the boundary (MSW), not by mocking your own hooks.
- **E2E**: the three to ten journeys the product cannot survive without — sign
  in, primary task, checkout/publish, recovery from failure. Not every page.

## Rules

1. **Test behaviour, not implementation.** No asserting on state variables,
   internal hook calls, class names, or component structure.
2. **Query like a user**: `getByRole`, `getByLabelText`, `getByText`. `data-testid`
   is the last resort for things with no accessible identity.
3. **Mock the boundary, not the module graph.** Mock HTTP (MSW) and timers;
   do not mock the component's own hooks — that tests the mock.
4. **One reason to fail.** A test that fails for three possible causes will be
   weakened until it passes for all of them.
5. **Factories own fixtures.** One builder per entity, with overrides; no
   200-line literal repeated per file.
6. **No sleeps.** Await a user-visible condition (`findBy*`, `expect.poll`,
   Playwright auto-wait). A `setTimeout` in a test is a flake with a delay.
7. **Deterministic time and randomness** in unit/integration layers.

## What not to test

- Third-party library behaviour.
- Implementation details that will be refactored (hook order, internal state).
- Snapshot blobs of whole pages: they bless whatever rendered, including bugs.
- The same rule at three layers "for safety" — that is triple maintenance, not
  triple confidence.

## Flake and runtime budgets

| Budget | Target |
|---|---|
| Full unit+component suite | < 60 s locally |
| Integration suite | < 5 min |
| E2E critical path | < 10 min, parallelised |
| Flake rate | 0 tolerated; quarantine on first unexplained failure, with an owner and a date |

A quarantined test without an owner is a deleted test with extra steps.

## Failure modes at scale

- **Coverage theatre**: 90% coverage of presentational components, 0% of the
  permission matrix.
- **Mock drift**: hand-written API mocks that no longer match the server, so
  integration tests pass against a fiction. Generate mocks from the same schema
  the server uses.
- **Shared mutable fixtures** producing order-dependent tests.
- **E2E as the only layer**: slow feedback, and failures with no localisable
  cause.
- **Tests that assert the snapshot of a design system** — every token change
  rewrites hundreds of files and hides real diffs.

## Verification receipts

1. `tsc --noEmit` and lint are part of the same gate as tests.
2. The suite fails when the behaviour is deliberately broken (mutation check on
   the critical path).
3. Timing report per layer, committed with the suite.
4. Flake log: last N CI runs, failures by test id.
5. Each critical journey has exactly one E2E owner and a named integration test
   beneath it.
