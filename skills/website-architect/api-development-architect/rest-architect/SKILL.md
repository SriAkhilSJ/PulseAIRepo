---
name: rest-architect
description: Architect-level REST design — resource modelling and URI structure, method and status-code semantics, representation and caching headers, pagination and filtering, and the versioning practices that keep an HTTP API usable for a decade. Use when designing or reviewing a REST API.
license: MIT
compatibility: HTTP/1.1–2–3; OpenAPI 3.1
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/api-development-architect/rest-architect
  crusor-origin: original
  crusor-sources: "RFC 9110 (HTTP semantics); RFC 9457 (problem details); OpenAPI 3.1"
  crusor-triggers: "rest, restful, http api, openapi, status codes, http caching, pagination, hal"
  crusor-verified-on: "2026-10-30"
---

# REST Architect

REST is **HTTP used honestly**: resources identified by URLs, semantics carried by
methods and status codes, and caching made possible by design.

## When to use

- Public or multi-client HTTP APIs.
- An existing API that returns 200 for everything and confuses every client.
- Designing URLs, status codes, or pagination.

## When NOT to use

- One TypeScript client in your own repo (see `trpc-architect`).
- Highly variable client query shapes (see `graphql-architect`).

## Decision 1 — Resources and URLs

- Nouns, plural, stable: `/v1/orders`, `/v1/orders/{id}/items`.
- Hierarchy expresses containment, not ownership rules: deep nesting beyond two
  levels is a sign you need filters (`/items?order_id=`).
- Actions that are not CRUD get a sub-resource or a verb endpoint used sparingly:
  `POST /v1/orders/{id}/cancel`.
- IDs opaque in URLs; never leak database internals.
- No verbs in resource paths, no file extensions, no trailing slashes.

## Decision 2 — Methods and status codes

| Method | Semantics | Safe | Idempotent |
|---|---|---|---|
| GET | read | yes | yes |
| POST | create/non-idempotent action | no | no |
| PUT | full replace | no | yes |
| PATCH | partial update | no | not guaranteed |
| DELETE | remove | no | yes |

- 200 read/update · 201 create (+`Location`) · 204 no content · 400 malformed ·
  401 unauthenticated · 403 unauthorised · 404 missing · 409 conflict ·
  422 semantic validation · 429 rate limited · 5xx server.
- Never 200-with-error-body; never 500 for expected validation failure.

## Decision 3 — Representations

- JSON by default; consistent casing; timestamps ISO-8601 UTC; money as
  `{amount, currency}` with integer minor units.
- Envelope decision, made once: either always wrap (`{data, meta}`) or never.
- Partial representations via sparse fieldsets (`?fields=id,name`) rather than
  many endpoints.
- `ETag`/`Last-Modified` on cacheable reads; `If-None-Match` → 304.

## Decision 4 — Collections

- Cursor pagination: `?limit=50&cursor=…` returning `next_cursor`.
- Stable sort guaranteed; default sort documented.
- Filtering and sorting are allow-listed (`?status=open&sort=-created_at`).
- Total counts are opt-in and expensive — expose them when the product needs
  them.

## Decision 5 — Caching and conditional requests

- `Cache-Control` explicit per endpoint: `no-store` for user-specific data,
  `private, max-age` for user data, `public, s-maxage` for shared.
- `Vary` on the headers that change the representation (auth, accept-language).
- Clients must be able to revalidate rather than refetch.

## Decision 6 — Idempotency and concurrency

- `Idempotency-Key` on POSTs that create billable/side-effecting resources;
  replay returns the original result.
- Optimistic concurrency with `If-Match`/version; 409 on conflict, with the
  current representation.

## Failure modes at scale

- `GET /getOrders` — RPC in REST clothing.
- 200 for failures; every client re-implements error parsing.
- Offset pagination on a table that grows hourly.
- `Cache-Control` missing → CDN caches one user's data for everyone.
- Field rename in a patch release breaking mobile clients in the wild.

## Verification receipts

1. OpenAPI 3.1 spec is the source of truth; linted in CI.
2. Status-code matrix tested per endpoint (success + each failure class).
3. Conditional-request test: ETag → 304 with no body.
4. Pagination test with concurrent inserts (no duplicates/skips).
5. Cache-header audit on one user-specific and one public endpoint.
