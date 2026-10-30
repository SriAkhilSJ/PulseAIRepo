---
name: nodejs-architect
description: Architect-level Node.js guidance — process and deployment model, module boundaries, event-loop and backpressure budgets, stream and worker decisions, error and shutdown contracts, and the security posture a Node service is built with. Use when designing or reviewing a Node backend, CLI or build service.
license: MIT
compatibility: Node 20+ LTS; ESM-first
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/react-architect
  crusor-origin: original
  crusor-sources: "nodejs.org/api; nodejs.org/en/learn (event loop, streams); OWASP Node security"
  crusor-triggers: "nodejs, node, express, fastify, streams, workers, event-loop, backend, runtime, server"
  crusor-verified-on: "2026-10-30"
---

# Node.js Architect

Node is a single-threaded event loop wrapped in an operating-system process.
Almost every production incident is one of: blocking the loop, losing an error,
or leaking a resource.

## When to use

- Designing a Node service, API, CLI or build worker.
- The service degrades under load or stalls without CPU saturation.
- Choosing between a monolith, workers, or a queue.
- Reviewing shutdown, error and security behaviour.

## When NOT to use

- A pure frontend task with no server runtime.
- A one-file script with no operational surface.

## Decision 1 — Process model

| Need | Model |
|---|---|
| HTTP API, modest CPU | single process, clustered by the platform (not by hand) |
| CPU-heavy work (images, crypto, parsing) | `worker_threads` pool, or a separate service |
| Long-running jobs | queue + workers, never inside the request path |
| CLI | one process, explicit exit codes, no hidden globals |

Rules:

- Scale horizontally by process/container, not by spawning inside a request.
- The request path never awaits CPU-bound work; it enqueues or offloads it.
- State lives outside the process (Redis/DB), or the process is disposable.

## Decision 2 — Event loop and backpressure

- A synchronous operation over unbounded input is an outage: cap payload and
  array sizes before processing.
- Streams for anything larger than memory; `pipeline()` for multi-stage flows so
  errors and cleanup propagate.
- Respect backpressure: honour `write()` returning `false` and drain before
  more input.
- No `JSON.parse` on untrusted unbounded bodies; enforce body limits at the edge.
- Timers and `setInterval` are not scheduling; they drift and pile up.

## Decision 3 — Modules and layering

```
http/ (transport: routes, validation, status codes)
  service/ (business rules; no Express/req objects)
    repo/ (data access; the only place with SQL/ORM)
      lib/ (pure utilities)
```

- ESM with explicit extensions; one public entry per module.
- Handlers validate input at the edge and pass typed domain objects inward.
- The service layer never imports `req`/`res` — that is what makes it testable.
- No cyclical imports; they are two modules sharing an unnamed concept.

## Decision 4 — Errors and shutdown

- One error taxonomy: expected (4xx/domain) vs unexpected (5xx/infra).
- Every async path terminates in a handler; unhandled rejections crash the
  process by design in production.
- Graceful shutdown: stop accepting, drain in-flight, close pools, exit with a
  code — on `SIGTERM`, with a deadline.
- Health endpoints: liveness (process alive) vs readiness (dependencies usable).

## Decision 5 — Security posture

- Secrets from the environment/secret manager; never in code or logs.
- Validate and normalise every external input; deny by default on routes.
- Escape on output; parameterise every query.
- No `eval`, no dynamic `require` of user input.
- Dependency policy: lockfile, audit in CI, pinned versions, no install scripts
  from unknown packages.

## Failure modes at scale

- Blocking the loop with sync crypto/fs/JSON on hot paths.
- Unbounded concurrency: 10k parallel DB calls that exhaust the pool.
- Memory leak via listeners added per request and never removed.
- Zombie timers keeping the process alive through shutdown.
- Logging whole request bodies (secrets and PII).

## Verification receipts

1. Load test at expected peak: p95 latency, loop delay, memory curve.
2. Graceful-shutdown test: `SIGTERM` under load exits cleanly within the deadline.
3. Stream/backpressure test with a slow consumer.
4. Dependency audit and lockfile diff in CI.
5. Health/readiness behaviour when a dependency is down.
