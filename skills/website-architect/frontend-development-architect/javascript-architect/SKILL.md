---
name: javascript-architect
description: Architect-level JavaScript guidance — module boundaries and load strategy, async and error-flow design, event-loop budgets, immutability and data-shape decisions, and the runtime split between browser and server. Use when designing application structure or diagnosing coupling, not for syntax.
license: MIT
compatibility: ES2022+, Node 20+ and evergreen browsers
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/javascript-architect
  crusor-origin: original
  crusor-sources: "MDN JavaScript; ECMAScript 2024; Node.js docs"
  crusor-triggers: "javascript, modules, async, event-loop, promises, errors, immutability, bundling, esm, cjs"
  crusor-verified-on: "2026-10-30"
---

# JavaScript Architecture

JavaScript failures are almost never syntax. They are **module boundaries,
async flow, and error ownership**. Decide those three, and the rest is local.

## When to use

- Splitting an application into modules/packages.
- Designing an async flow or an error contract.
- Deciding ESM vs CJS, browser vs server runtime.
- Performance work where the event loop is the suspect.

## When NOT to use

- A local refactor with no boundary change.
- Type-shape questions (see `typescript-architect`).

## Decision 1 — Module boundaries

- One public entry per module (`index.js`) exposing a deliberate surface; deep
  imports are private.
- Dependencies point inward: `app → features → domain → util`. No cycles — a
  cycle is two modules sharing a concept they have not named.
- A module owns its data and its invariants; callers ask for behaviour, not for
  raw state to mutate.
- Prefer many small pure modules over one "service" that knows everything.
- Runtime split is explicit: browser-only code never imports Node built-ins, and
  server-only code never reaches a client bundle.

## Decision 2 — Async and error flow

- Every async boundary has an owner: who retries, who cancels, who surfaces.
- `async/await` at the boundary, promise combinators for concurrency:
  `Promise.all` (fail-fast), `allSettled` (independent), `any` (race) — choose
  deliberately, they are not interchangeable.
- Cancellation is part of the contract (`AbortController`); a stale response must
  not overwrite a fresh one.
- No floating promises: unhandled rejections are defects.
- Errors are values at module boundaries and thrown only inside; convert once.
- Never swallow: `catch {}` is a bug unless a comment states the recovery.

## Decision 3 — Event loop and budgets

- Long tasks (>50 ms) are architecture problems: move parsing, sorting and
  crypto off the critical path or into a worker.
- Chatty async is a waterfall: independent work runs in parallel, dependent work
  is explicit.
- Avoid per-item timers and per-row listeners; batch, delegate, or observe.
- Timers are not scheduling: prefer `requestIdleCallback`/`scheduler` semantics
  for deferrable work.

## Decision 4 — Data shape

- Immutable at boundaries; mutation stays inside one owner's functions.
- Normalise only when the same entity appears in multiple views; otherwise keep
  shapes aligned with their producer.
- Validate at trust boundaries (network, storage, user input); inside the app,
  trust types.

## Failure modes at scale

- Barrel files making every import pull the world.
- One global event bus as the integration strategy — boundaries lost, order
  undefined.
- Async errors surfacing as a blank screen because nobody owned them.
- ESM/CJS dual-loading the same dependency, breaking identity checks.
- `JSON.parse(JSON.stringify(x))` as "deep clone" — drops Dates, Maps, undefined.

## Verification receipts

1. Dependency graph has no cycles (madge/graph tool, committed output).
2. `node --experimental` / build passes with strict ESM resolution.
3. A cancellation test: slow request loses to a newer one.
4. Bundle analyse: no module pulls a dependency it does not use.
5. Long-task profile of the primary interaction.
