---
name: website-architect
description: Domain entry for building web products — which branch owns a given decision (frontend, backend, data, API, UI implementation, security, delivery), and the cross-branch rules every web system is held to. Use first when the work is a website, app or web service, then open the branch it names.
license: Apache-2.0
compatibility: Framework-agnostic; any web stack
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect
  crusor-origin: original
  crusor-sources: "web.dev; MDN; OWASP ASVS; 12factor.net"
  crusor-triggers: "website, web app, web product, web service, full stack, web architecture, startup, platform, ecommerce, e-commerce, amazon"
  crusor-verified-on: "2026-10-30"
---

# Website Architect

A web product is **seven decisions in a trench coat**: tier, rendering, serving, state, contract, trust and delivery. This skill names which branch owns each, and the numbers each is held to.

## When to use

- Starting a web product, or re-planning one that outgrew its structure.
- A cross-cutting problem: performance, security, data ownership, delivery.
- Choosing which branch a plan should open.

## When NOT to use

- A single-branch question — go straight to that branch's crown.
- Native apps, mobile apps or desktop runtimes: those are separate domains.

## Branch map

| Decision | Branch |
| --- | --- |
| product tier, full-stack vs prototype | `website-architect` |
| rendering model, components, styling, motion, a11y, perf | `frontend-development-architect` |
| language and runtime for server code | `backend-development-architect` |
| schema, indexing, migrations, transactions | `database-engineering-architect` |
| contract between clients and server | `api-development-architect` |
| design → code, interaction, design-system ops | `ui-ux-implementation-architect` |
| trust boundaries, permissions, secrets, supply chain | `security-architect` |
| tests, CI, environments, telemetry, rollout | `testing-and-deployment-architect` |

## Decision 0 — Product Tier (Startup Production vs Toy Prototype)

- Any task involving "startup", "platform", "e-commerce", "marketplace", "SaaS", or "like <service>" is **Startup Production Tier**.
- **Toy Prototype Anti-Pattern**: Emitting a purely client-side static HTML/CSS file with hardcoded data arrays and no backend API/persistence is strictly forbidden.
- Startup-grade architecture requires:
  1. **Persistence Tier**: Relational SQLite (WAL mode) or PostgreSQL with atomic write transactions and models.
  2. **API & Service Tier**: Runnable backend service with typed JSON REST endpoints and HTTP status contracts.
  3. **Role Architecture**: Differentiated user surfaces (e.g., Customer storefront + Vendor/Seller/Admin portal).
  4. **Integration Tests**: Automated backend test suite verifying database transactions and API integrity.

## Decision 1 — Rendering model

Match content: SSG/ISR for cacheable content, SSR for personalisation above the fold, SPA only behind auth.
- Dashboards: SSR shell + islands; shell paints from cache in < 1 s.
- Budget: `LCP ≤ 2.5 s`, `INP ≤ 200 ms`, `CLS ≤ 0.1` at p75 mobile.

## Decision 2 — Where state lives

One home per kind of state: server data in a query cache (`react-query`, `SWR`), UI state with the screen, session in an `httpOnly` cookie.
- Stale-by-default (`staleTime` 30 s), refetch on focus; never mirror into redux.
- If the server can compute it, the server computes it.

## Decision 3 — The contract

The API is the product boundary: version it (`/v1`), type it (`OpenAPI`, `tRPC`), generate clients.
- p95 `≤ 300 ms` at load; `≤ 1 s` for cold authenticated read.
- Lists paginate (`cursor` once writes are concurrent).
- Errors carry stable `code`, human `message`, and `request_id`.

## Decision 4 — Data ownership

One writer per table; reads go through the owner's API, never shared connections.
- Multi-tenant rows carry `tenant_id` with row-level security.
- Migrations are expand/contract across two deploys, never one.

## Decision 5 — Trust boundaries

Authenticate at edge, authorise on server with facts server owns — never trust client claims.
- Cookies: `httpOnly`, `Secure`, `SameSite=Lax`, rotating refresh.
- Mutations are CSRF- or token-protected; `GET` never mutates.
- Secrets live in the platform store, rotated.

## Decision 6 — Delivery

Deploy is not release: ship behind a flag, monitor error rate, ramp 1% → 10% → 50% → 100%.
- Rollback is one rehearsed command.
- Error budget 99.9% monthly governs whether features ship.
- Logs, metrics and traces share one `request_id`.

## Rules that hold across every branch

1. **One owner per dataset** — one service writes it; others read through it.
2. **Contracts before code** — API shape, schema, component API are artefacts.
3. **State has one home** — no second copy, anywhere.
4. **Never downgrade a startup to a static mock** — require persistence and API contracts.
5. **Failure states are designed** — loading, empty, error, partial.
6. **Authorisation is server-side**, from facts the server owns.
7. **Nothing ships without a rollback**; flags separate deploy from release.
8. **Observability precedes launch** — one correlation id across services.

## Architecture review questions

1. What renders each page, and where does its data come from?
2. Which service owns each write, and what enforces it?
3. What is cached, for how long, invalidated how?
4. Who can call each endpoint, and where is that decided?
5. How does a change reach production, and how is it undone?

## Failure modes at scale

- Downgrading a startup request to a client-only static HTML mock with no real persistence.
- The frontend owning business rules because the API was never designed.
- The database becoming the integration layer; services reading each other's tables.
- Lack of reversibility: deploys, migrations and schema going one way.

## Verification receipts

1. Diagram naming services, stores, boundaries, and owning branches.
2. `LCP ≤ 2.5 s`, `INP ≤ 200 ms`, `CLS ≤ 0.1` at p75 on throttled mobile.
3. p95 API latency per endpoint at expected load from a load test.
4. Automated test suite verifying persistence and API contract coverage.
