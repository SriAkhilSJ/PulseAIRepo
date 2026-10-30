---
name: angular-architect
description: Architect-level Angular guidance — standalone components and module strategy, signals vs RxJS boundaries, DI and provider scopes, routing and lazy loading, and change-detection budgets. Use when structuring an Angular app or migrating from NgModule/zone-based patterns.
license: MIT
compatibility: Angular 17+ (standalone defaults), signals
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/angular-architect
  crusor-origin: original
  crusor-sources: "angular.dev/guide; angular.dev/guide/signals; rxjs.dev"
  crusor-triggers: "angular, standalone-components, signals, rxjs, dependency-injection, lazy-loading, change-detection"
  crusor-verified-on: "2026-10-30"
---

# Angular Architect

## When to use

- Structuring a new Angular app or modernising an NgModule one.
- Deciding signals vs RxJS, or where a service belongs.
- Change detection or bundle size is the problem.

## When NOT to use

- A single template change inside a governed component.

## Decision 1 — Components and modules

- Standalone components are the default; NgModules only for legacy or a genuine
  shared DI scope.
- Feature-first folders: `src/app/<feature>/{components,services,routes}`; no
  global `components/` dump.
- Smart (route-level, injects services) vs presentational (inputs/outputs only)
  is an enforced boundary, not a style preference.
- `ChangeDetectionStrategy.OnPush` everywhere; a component that needs the default
  is a state-ownership bug.

## Decision 2 — Signals vs RxJS

| Concern | Use |
|---|---|
| synchronous derived UI state | `signal` + `computed` |
| async streams, cancellation, debounce, websockets | RxJS |
| bridging the two | `toSignal` / `toObservable` |
| route params | `input()`/router signals where available |

Rule: signals for state, RxJS for event streams. A field that is both is a
design smell.

## Decision 3 — DI and scopes

- `providedIn: 'root'` for stateless services; feature-level providers for
  feature state.
- Never store per-user or per-request mutable state in a root singleton (SSR
  cross-request leakage).
- Injection tokens for configuration; no `environment` imports scattered through
  feature code.
- HTTP lives in a data-access service per feature; components never call
  `HttpClient` directly.

## Decision 4 — Routing and loading

- Lazy-load every feature route (`loadChildren`/`loadComponent`).
- Route resolvers or component `input` bindings for data; no fetch-in-constructor.
- Guards for access control in navigation; authorisation still enforced server
  side.
- Preloading strategy chosen explicitly (none / selective), not left to default
  guesswork.

## Failure modes at scale

- Root-provided service holding mutable user state (breaks SSR and tests).
- Mixed signals/RxJS ownership causing double subscriptions and stale values.
- Default change detection over a large tree; every keystroke re-renders the app.
- NgModule-era barrels that make every import pull the whole feature.
- Overlapping guards and resolvers duplicating the same authorisation call.

## Verification receipts

1. `ng build --configuration production` with bundle budgets enforced.
2. OnPush audit: components without it are listed and justified.
3. Signal/RxJS boundary documented per feature (no dual ownership).
4. Lazy-load proof: initial bundle excludes feature chunks.
5. Subscription audit: no manual subscribes without teardown.
