---
name: api-development-architect
description: Architect-level API direction — contract-first design, choosing REST vs GraphQL vs tRPC vs gRPC, versioning and evolution, one error envelope, pagination and idempotency, and the boundary rules that keep an API stable for years. Use before any transport-specific API skill.
license: MIT
compatibility: Transport-agnostic (HTTP/REST, GraphQL, tRPC, gRPC)
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/api-development-architect
  crusor-origin: original
  crusor-sources: "openapis.org; graphql.org/learn; grpc.io/docs; trpc.io/docs"
  crusor-triggers: "api design, api contract, openapi, api versioning, rest vs graphql, api architecture"
  crusor-verified-on: "2026-10-30"
---

# API Architect

An API is a **promise to clients you cannot see**. Every decision here is about
keeping that promise while the system underneath changes.

## When to use

- Designing a new API surface, or choosing a transport for one.
- Contract, versioning, pagination or auth decisions that clients depend on.
- Reviewing an API that external or long-lived clients consume.

## When NOT to use

- Internal function boundaries inside one process.
- A single endpoint on an otherwise settled API.

## Leaf map

| Need | Skill |
|---|---|
| resource-oriented HTTP for many clients | `rest-architect` |
| flexible client-driven queries, one endpoint | `graphql-architect` |
| TypeScript-only, internal, type-safe RPC | `trpc-architect` |
| service-to-service, streaming, strict contracts | `grpc-architect` |
| who may call this, and how they prove it | `api-auth-architect` |
| protecting the API from its clients | `rate-limiting-architect` |

## Decision 1 — Transport from the client set

| Clients | Choose |
|---|---|
| third parties, mobile, unknown consumers | REST + OpenAPI |
| many varied UIs over one graph | GraphQL |
| own TypeScript monorepo only | tRPC |
| internal services, low latency, streaming | gRPC |

- Public API ⇒ REST unless you can afford GraphQL's operational cost.
- tRPC is not an external API: expose REST/GraphQL if anyone outside owns a
  client.

## Decision 2 — Contract first

- The schema (OpenAPI/proto/GraphQL SDL) is the reviewed artefact; handlers
  follow it.
- Generate clients and server types from it; hand-written duplicates drift.
- The contract covers success **and** failure shapes, plus limit behaviour.

## Decision 3 — Versioning and evolution

| Change | Allowed? |
|---|---|
| add optional field | yes, no version bump |
| add required field to request | no — breaking |
| remove/rename a field | no — deprecate, then remove |
| change type or semantics | no — new field or version |
| add endpoint | yes |

- Prefer additive evolution over `/v2`. Version at the edge (`/v1`) when you
  must break.
- Deprecation has a timeline, a header (`Deprecation`/`Sunset`), and a migration
  note.
- Tolerant reader on both sides: unknown fields are ignored, not rejected.

## Decision 4 — The shared envelope

- One error shape everywhere: `{ error: { code, message, details?, request_id } }`.
- Machine-readable `code` (stable) plus human `message` (translatable).
- HTTP status conveys class (4xx/5xx); the code conveys the specific reason.
- Validation failures list field paths; never a bare "invalid input".

## Decision 5 — Lists, pagination, mutation

- Cursor pagination for anything that grows; offset only for small fixed sets.
- Default and maximum page size enforced server-side.
- Filtering/sorting are explicit, allow-listed parameters — never raw query
  passthrough.
- Mutations that clients may retry take an idempotency key; creation returns the
  existing resource on replay.

## Decision 6 — Trust boundaries

- Authn at the edge, authz in the service (server-side facts only).
- Every request carries a correlation id, echoed in responses and logs.
- Clients never send IDs they are allowed to choose (ownership, price, role).
- Timeouts, size limits and rate limits are part of the contract.

## Failure modes at scale

- Response shapes that differ between endpoints ("sometimes `data`, sometimes
  the array").
- A breaking field rename shipped as a patch.
- Pagination without a stable sort → duplicated/missing rows.
- Authz decisions made from client-supplied claims.
- No idempotency → duplicate charges on retry.

## Verification receipts

1. Contract diff in the PR; breaking changes flagged by a checker.
2. Error envelope conformance test across endpoints.
3. Pagination stability test (insert during paging).
4. Idempotent replay test on a create endpoint.
5. Authz matrix test per resource (owner/other/admin/anonymous).
