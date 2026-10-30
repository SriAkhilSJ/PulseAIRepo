---
name: fastapi-architect
description: Architect-level FastAPI guidance — ASGI and async boundary discipline, pydantic request/response contracts, dependency injection and lifespans, router layering, background work, OpenAPI-first design, and the blocking-call traps that break it. Use when designing or reviewing a FastAPI service (not Flask or Django).
license: MIT
compatibility: FastAPI 0.110+, pydantic v2, uvicorn/gunicorn
metadata:
  crusor-domain: website-architect
  crusor-path: backend-development-architect/python-architect/fastapi-architect
  crusor-origin: original
  crusor-sources: "fastapi.tiangolo.com; docs.pydantic.dev; asgi.readthedocs.io"
  crusor-triggers: "fastapi, pydantic, asgi, dependency injection, openapi, uvicorn"
  crusor-verified-on: "2026-10-30"
---

# FastAPI Architect

FastAPI is an **ASGI** framework: correctness under load is decided by what you
do inside `async def`, not by the decorators.

## When to use

- New HTTP API, typed contracts, OpenAPI as a deliverable.
- High concurrency with I/O-bound work.
- Replacing Flask where async or first-class validation is now required.

## When NOT to use

- CPU-bound service (async buys nothing; use workers/queues).
- A content app with templates and admin (see `django-architect`).
- A tiny internal endpoint where Flask's simplicity wins (see `flask-architect`).

## Decision 1 — Async discipline (the whole game)

- `async def` handlers may only await async I/O. **One blocking call**
  (requests, sync DB driver, `time.sleep`, heavy CPU) stalls the event loop for
  every request on that worker.
- Blocking libraries go behind `run_in_threadpool` or a worker, explicitly.
- `def` handlers are fine for blocking work — FastAPI runs them in a threadpool;
  choosing `def` deliberately is architectural, not lazy.
- Per-request state lives in a dependency, never in module globals.

## Decision 2 — Contracts at the boundary

- Separate models: `CreateRequest`, `UpdateRequest`, `Response`. Do not return
  ORM objects directly.
- `response_model` on every route; forbid extra fields on input
  (`model_config = ConfigDict(extra="forbid")` where appropriate).
- Validation errors are part of the public contract: shape them once, not per
  route.
- Version the API at the router level (`/v1`), not by editing schemas in place.

## Decision 3 — Layering

```
app/main.py        create_app(), routers, lifespan, middleware
  api/routers/     HTTP shape: parsing, status codes, auth deps
    services/      use-cases; no Request/Response objects
      repositories/ DB/queue access; the only place with SQL
        models/    pydantic + ORM separated
```

- Routers are thin: parse → call service → map result to response.
- Services raise domain errors; one exception handler maps them to HTTP.
- Dependencies (`Depends`) are composition, not a service locator: auth, DB
  session, pagination, feature flags.

## Decision 4 — Sessions, lifespans, background work

- DB sessions: one per request (`yield` dependency), never a global session.
- `lifespan` for clients/pools that must outlive a request (HTTP clients, cache,
  ML models); close them on shutdown.
- `BackgroundTasks` is for short, non-critical work; anything durable belongs in
  a queue (Celery/RQ/arq) with retries.
- Graceful shutdown: stop accepting, drain, close pools.

## Decision 5 — Security defaults

- Auth as a dependency (`get_current_user`), applied at router level by default;
  public routes opt out explicitly.
- CORS allowlists, not `*`, once credentials are involved.
- Rate limits at the edge/middleware; body-size caps before parsing.
- Never trust client-supplied IDs for ownership; authorise in the service layer.

## Failure modes at scale

- Sync SQLAlchemy in `async def` — works in dev, collapses under concurrency.
- A single global `AsyncClient`/session shared across requests with mutable state.
- Giant `dependencies.py` that becomes a second application layer.
- Returning ORM models → accidental field leakage and N+1 serialisation.
- Validation split between pydantic and hand-written checks in the service.

## Verification receipts

1. Load test proving the loop is not blocked (loop delay stays low at peak).
2. `/openapi.json` reviewed as the contract; response models present everywhere.
3. Shutdown test: lifespan closes clients, in-flight requests finish.
4. Auth test: an unauthenticated and a cross-tenant request both denied.
5. Failure test: dependency down → typed 5xx/timeout, not a hang.
