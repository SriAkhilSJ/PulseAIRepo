---
name: express-architect
description: Architect-level Express guidance — router/middleware layering, error-handling contracts, validation and auth placement, async handler safety, and the deployment model for a stateless Node service. Use when designing or reviewing an Express API.
license: MIT
compatibility: Express 4/5; Node 20+
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/react-architect/nodejs-architect/express-architect
  crusor-origin: original
  crusor-sources: "expressjs.com/en/guide; nodejs.org/api/http"
  crusor-triggers: "express, expressjs, express router, express middleware, node http, req res next"
  crusor-verified-on: "2026-10-30"
---

# Express Architect

Express gives you a middleware chain and nothing else. Architecture is the
**order of that chain** and what is allowed to know what.

## When to use

- A Node HTTP API where you want explicit control and minimal surface.
- Existing Express app that has become a pile of `app.use`.
- A service small enough that a framework's conventions would be overhead.

## When NOT to use

- Structured, DI-heavy, TypeScript-first service (see `nestjs-architect`).
- Throughput-critical JSON APIs where schema-first speed matters
  (`fastify-architect`).
- Anything needing async-by-default semantics — Express 4 is callback/promise
  land; misconfigured async handlers crash or hang.

## Decision 1 — Chain order (fixed, documented)

```
request id → logging → body limit → security headers → cors
  → auth (router-scoped) → validation → handler → error handler
```

- Error handler is **last** and has 4 args; it is the only place that formats
  errors.
- Auth is applied per router, not globally, so public routes are explicit.
- Body size limits before any parsing of untrusted input.

## Decision 2 — Layering

```
routes/      express.Router(), path + validation wiring
  controllers/ parse req -> call service -> res
    services/  use-cases, no req/res
      repos/   DB/queue
```

- Controllers never contain SQL; services never touch `req`.
- Mount routers by bounded context (`/v1/orders`, `/v1/auth`).
- Async errors: wrap handlers (`asyncHandler`) so rejections reach the error
  middleware — an unhandled rejection in Express 4 is a silent hang.

## Decision 3 — Contracts

- One error envelope: `{error: {code, message, details?}}` for every failure.
- Validation at the edge (zod/joi), typed thereafter; never trust `req.body`.
- 404 handler for unmatched routes; 405 where methods differ.
- Pagination/filtering parameters validated and capped.

## Decision 4 — Runtime and deployment

- Stateless processes; sessions in a store, never in memory.
- `trust proxy` set correctly behind a load balancer, or rate limits and IPs
  lie.
- Graceful shutdown: stop accepting, drain, close DB pool.
- Health endpoints separate liveness from readiness.

## Failure modes at scale

- Middleware added "temporarily" that mutates `req` for everyone.
- Async handler throwing → request hangs until timeout.
- Global `app.use(auth)` with a growing exception list.
- Error messages leaking stack traces in production.
- Business logic duplicated across three route files.

## Verification receipts

1. Middleware order documented and covered by an integration test.
2. Error path test: thrown service error → correct status + envelope, no stack.
3. Auth test: public, authenticated, and cross-tenant access.
4. Shutdown test under load.
5. Load test at peak with event-loop delay measured.
