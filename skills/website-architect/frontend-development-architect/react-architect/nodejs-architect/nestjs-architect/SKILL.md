---
name: nestjs-architect
description: Architect-level NestJS guidance — module boundaries and dependency injection scopes, controller/provider layering, guards/interceptors/pipes ownership, configuration and request-scoped state, and the DI mistakes that break testability or leak state between requests. Use when designing or reviewing a NestJS service.
license: MIT
compatibility: NestJS 10/11; TypeScript; Node 20+
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/react-architect/nodejs-architect/nestjs-architect
  crusor-origin: original
  crusor-sources: "docs.nestjs.com; docs.nestjs.com/fundamentals/injection-scopes"
  crusor-triggers: "nestjs, nestjs module, nestjs guard, nestjs interceptor, nest module, dependency injection, guards interceptors"
  crusor-verified-on: "2026-10-30"
---

# NestJS Architect

Nest is a **module graph with dependency injection**. Every architectural
question becomes: which module owns this, and what scope does it live in?

## When to use

- A structured TypeScript backend with multiple teams or bounded contexts.
- You need DI, guards, interceptors and validation as first-class concepts.
- An existing Nest app has tangled modules or request-scoped leakage.

## When NOT to use

- A tiny service — the module ceremony costs more than it returns.
- A throughput-maximal JSON API where you would fight the decorator layer.

## Decision 1 — Modules are boundaries

- One module per bounded context; it exports only what others may use.
- `imports` is a dependency graph: a cycle means two contexts are one.
- Shared building blocks (config, logging, DB) live in `@Global()` modules —
  sparingly; global is a shortcut, not a pattern.
- Feature modules own their controller + service + repository; no cross-module
  repository imports.

## Decision 2 — Injection scopes

| Scope | Use when |
|---|---|
| default (singleton) | almost everything |
| `REQUEST` | the provider needs the current request/user |
| `TRANSIENT` | a new instance per consumer is genuinely required |

- Request scope bubbles up: injecting one request-scoped provider into a
  singleton makes the singleton request-scoped. Prefer passing the user/context
  as a method argument over a request-scoped service.
- **Never** hold per-request data in a singleton (a `this.currentUser` on a
  provider is a cross-tenant leak).
- `request.user` comes from a guard/AuthGuard; services receive it explicitly.

## Decision 3 — The request pipeline

| Layer | Owns |
|---|---|
| middleware | logging, request id, raw infrastructure |
| guards | authentication/authorisation decisions |
| pipes | validation and transformation (DTO in, typed object out) |
| interceptors | cross-cutting concerns: timeouts, mapping, tracing |
| filters | exception → HTTP response shape |
| controller | routing only |

- Validation via DTO classes + `ValidationPipe` with `whitelist: true` and
  `forbidNonWhitelisted` where strictness matters.
- One global exception filter defines the error envelope; controllers throw
  domain exceptions, never `res.status(...)`.

## Decision 4 — Configuration and persistence

- `ConfigModule` with a validated schema (fail at boot, not at first request).
- DB access through repositories; transactions opened in services, not
  controllers.
- Background/async work via queues; `@nestjs/schedule` for cron, not `setInterval`.

## Failure modes at scale

- A "shared" module imported everywhere, now everything depends on everything.
- Request-scoped providers injected into singletons → whole graph recreated per
  request, latency climbs.
- Guards doing business rules; controllers doing validation by hand.
- Circular module imports resolved with `forwardRef` instead of redesign.
- Service holding mutable state between requests.

## Verification receipts

1. Module graph printed and reviewed; no unexplained cycles.
2. Scope audit: which providers are request-scoped, and why.
3. Validation test: unknown field rejected; malformed payload rejected.
4. Auth matrix test: unauthenticated, wrong role, cross-tenant.
5. Load test showing per-request instantiation cost is bounded.
