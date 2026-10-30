---
name: backend-development-architect
description: Architect-level server-side direction — choosing the language and framework leaf for a workload, then the cross-language contracts a backend is built on (API boundary, layering, state ownership, failure and shutdown, security posture, deployment model). Use when starting or reviewing a backend service, before any framework-specific skill.
license: MIT
compatibility: Language-agnostic (Python, Node, Go, Java, Rust, .NET, Ruby, PHP). Requires ability to read and edit server source.
metadata:
  crusor-domain: website-architect
  crusor-path: backend-development-architect
  crusor-origin: original
  crusor-sources: "12factor.net; OWASP ASVS; language/framework official docs"
  crusor-triggers: "backend architecture, microservice, microservices, grpc, backend design, service architecture"
  crusor-verified-on: "2026-10-30"
---

# Backend Architect

Backend architecture is decided by **failure behaviour and ownership**, not by
the framework. Choose the leaf, then hold the contracts below.

## Leaf map

| Workload | Start with |
|---|---|
| Python service | `python-architect` → `flask-` / `fastapi-` / `django-architect` |
| Node service | `nodejs-architect` → `express-` / `nestjs-` / `fastify-architect` |
| Go service | `go-architect` |
| Java/JVM service | `java-architect` |
| Rust service | `rust-architect` |
| .NET service | `dotnet-architect` |
| Ruby service | `ruby-architect` |
| PHP service | `php-architect` |

Rules of the tree: one skill per framework, chosen by task; the language skill
holds what is portable, the framework skill holds what actually differs.

## Decision 1 — Language and framework selection

| Constraint | Points to |
|---|---|
| team velocity, integration-heavy, CRUD | Python/Django, Node/NestJS |
| high concurrency, modest CPU per request | Go, Node, Rust |
| CPU-bound or latency-critical | Go, Rust, JVM |
| existing enterprise integration | Java/.NET |
| one small service, minimal ops | Python/Flask, Go net/http |

Never choose on preference. Choose on: team's current skill, operational
familiarity, and the load shape.

## Decision 2 — The API boundary

- Contract first: the schema (OpenAPI/protobuf) is the artefact reviewed, not
  the handler.
- Versioning strategy chosen up front (`/v1`, or a gateway) — never mutate a
  published shape.
- One error envelope for the whole service, including validation failures.
- Idempotency keys for anything a client may retry.
- Pagination, filtering and limits are contract, not implementation detail.

## Decision 3 — Layering (same in every language)

```
transport  (routes, parsing, auth, status codes)
  service  (use-cases, transactions, rules)
    data   (repositories, the only SQL/ORM surface)
      domain (pure types and rules, framework-free)
```

- A framework type never reaches the domain layer.
- Transactions are opened in the service, not the handler.
- Cross-cutting concerns (logging, tracing, auth) are middleware/decorators,
  applied once.

## Decision 4 — State and scale

- Processes are disposable: no in-memory state that a restart would lose.
- Sessions in a store; caches explicit with TTLs; jobs in queues.
- Scale out by instances; every instance must be able to serve any request.
- Shared contracts (queues, events) versioned like APIs.

## Decision 5 — Failure and shutdown

- Timeouts on every outbound call; retries only where idempotent, with backoff
  and jitter.
- Circuit breaking or load shedding for known-flaky dependencies.
- Graceful shutdown on `SIGTERM`: stop accepting, drain, close pools, exit.
- Health: liveness ≠ readiness; readiness reflects dependencies.
- Logs structured, correlated by request id, no secrets or PII.

## Decision 6 — Security posture

- Deny by default: every route authenticated unless explicitly public.
- Authorise in the service layer using server-side facts, never client claims.
- Validate at the edge, parameterise every query, encode on output.
- Secrets from a manager; rotated; never in images or repos.
- Dependency policy: lockfile, audit in CI, pinned versions.

## Decision 7 — Deployment model

- One deployable artefact per service; config from environment.
- Migrations run as a step, not on boot in parallel across instances.
- Observability shipped with the service: metrics, traces, structured logs.
- Rollback plan defined before the first deploy.

## Failure modes at scale

- Business rules in controllers; the API becomes the domain.
- Migrations in the boot path racing across replicas.
- Unbounded retries amplifying an outage.
- In-memory caches that make instances non-interchangeable.
- One shared database serving five services with no ownership.

## Verification receipts

1. Contract review: schema diff, versioning, error envelope.
2. Failure drill: dependency down → timeout, shed, recover.
3. Graceful shutdown under load within the deadline.
4. Migration plan for a live table (expand → backfill → contract).
5. Load test at peak with loop/GC/queue saturation visible.
