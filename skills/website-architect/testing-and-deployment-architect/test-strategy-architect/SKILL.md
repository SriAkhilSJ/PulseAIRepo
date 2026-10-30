---
name: test-strategy-architect
description: Architect-level test strategy — allocating assertions across unit, integration, contract and end-to-end layers, designing for testability through dependency boundaries, fixture and data strategy, and the flake and coverage policies that keep a suite trustworthy. Use when defining how a codebase is tested.
license: MIT
compatibility: Any language; any test runner
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/testing-and-deployment-architect/test-strategy-architect
  crusor-origin: original
  crusor-sources: "martinfowler.com/articles/practical-test-pyramid.html; testing.googleblog.com (test sizes); xunitpatterns.com"
  crusor-triggers: "test strategy, test plan, test pyramid, testing pyramid, test suite, flaky, test coverage, e2e strategy, integration tests, contract tests, testability, fixtures"
  crusor-verified-on: "2026-10-30"
---

# Test Strategy Architect

A test suite is **a decision about where failures should be caught**. Everything
else — mocks, fixtures, coverage — follows from that decision.

## When to use

- Starting a codebase, or a suite is slow, flaky or ignored.
- Deciding where a new behaviour should be tested.
- Coverage is being used as a target instead of a signal.

## When NOT to use

- Framework-specific mechanics (see `vitest-`, `react-testing-`,
  `playwright-architect`).

## Decision 1 — Allocate by cost of failure

| Question | Layer |
|---|---|
| is this rule correct? | unit |
| does this talk to the database/queue correctly? | integration |
| did the contract change? | contract (consumer-driven) |
| can a user complete the journey? | e2e |
| is it fast / accessible / secure enough? | non-functional gate |

- One behaviour, one layer. Duplicating a rule at three layers buys nothing and
  costs three times the maintenance.
- The cheapest layer that can catch the bug owns the test.

## Decision 2 — Testability is architecture

- Pure functions for rules; side effects at the edges — that is what makes unit
  tests fast.
- Depend on interfaces you own (repository, clock, HTTP client), injected not
  imported — no mocking of your own modules.
- Time, randomness and IDs are injectable; otherwise tests become
  non-deterministic and get deleted.
- If a behaviour is hard to test, the coupling is the bug.

## Decision 3 — Test data

| Approach | Use |
|---|---|
| builder/factory functions | default; explicit per-test data |
| shared fixtures | read-only reference data only |
| database transactions/rollback | integration tests |
| seeded snapshots | never for mutable state |
| production-like anonymised dump | rare, large-scale perf work |

- Each test creates the state it needs and leaves nothing behind.
- No test depends on another test's side effects or ordering.
- IDs/timestamps generated per run, never hard-coded dates in the future.

## Decision 4 — Non-functional gates

- Performance: a budget test on critical paths (p95, bundle size).
- Accessibility: automated scan plus a manual checklist per release.
- Security: dependency audit, SAST, and an authorization matrix test.
- These run in CI like any other gate; "we'll check before launch" means never.

## Decision 5 — Trust policies

- Flake policy: any test failing intermittently twice is fixed, quarantined or
  deleted — decided within a sprint, never tagged and forgotten.
- Coverage: track per-module trend in critical paths; a global percentage gate
  invites useless tests.
- Test names describe behaviour and the failure mode, not the function.
- Delete tests that no longer protect anything; a suite is code and carries
  maintenance cost.

## Failure modes at scale

- 3,000 mocked unit tests, zero integration tests, production surprises weekly.
- A shared fixture mutated by tests, producing order-dependent failures.
- Coverage gate at 85% satisfied by snapshot tests asserting nothing.
- E2E used to verify validation rules already covered by unit tests.
- Nobody runs the suite locally because it takes 20 minutes.

## Verification receipts

1. Portfolio table: tests per layer, runtime per layer.
2. Failure drill: introduce a real bug — which layer catches it, and how fast?
3. Flake report over the last 50 CI runs with actions taken.
4. Testability review: no mocking of in-repo modules; clock/randomness injected.
5. Critical-path coverage trend, not a single percentage.
