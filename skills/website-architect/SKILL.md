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
  crusor-triggers: "website, web app, web product, web service, full stack, web architecture"
  crusor-verified-on: "2026-10-30"
---

# Website Architect

A web product is **six decisions in a trench coat**: rendering, serving, state,
contract, trust and delivery. This skill names which branch owns each, and the
numbers each is held to.

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
| rendering model, components, styling, motion, a11y, perf, SEO, i18n | `frontend-development-architect` |
| language and runtime for server code | `backend-development-architect` |
| schema, indexing, migrations, transactions | `database-engineering-architect` |
| contract between clients and server | `api-development-architect` |
| design → code, interaction, design-system ops | `ui-ux-implementation-architect` |
| trust boundaries, permissions, secrets, supply chain | `security-architect` |
| tests, CI, environments, telemetry, rollout | `testing-and-deployment-architect` |

## Decision 1 — Rendering model

Match the content, not the team's habit: SSG/ISR for anything cacheable, SSR for
personalisation above the fold, SPA only for app-shaped surfaces behind auth.

- Dashboards: SSR shell + islands; the shell paints from cache in < 1 s.
- Hold the site to `LCP ≤ 2.5 s`, `INP ≤ 200 ms`, `CLS ≤ 0.1` at p75 mobile.

## Decision 2 — Where state lives

One home per kind of state or every bug becomes a sync bug: server data in a
query cache (`react-query`, `SWR`, `apollo`), UI state with the screen, session
in an httpOnly cookie.

- Stale-by-default (`staleTime` 30 s), refetch on focus; never mirror into `redux`.
- If the server can compute it, the server computes it.

## Decision 3 — The contract

The API is the product boundary: version it (`/v1`), type it (`OpenAPI`,
`tRPC`, `GraphQL`), generate clients instead of hand-writing them.

- p95 `≤ 300 ms` at expected load; `≤ 1 s` for a cold authenticated read.
- Lists paginate from day one (`cursor` once writes are concurrent).
- Errors carry a stable `code`, a human `message`, and a `request_id`.

## Decision 4 — Data ownership

One writer per table or document; no service reads another's tables. Reads go
through the owner's API or a published view, never a shared connection.

- Multi-tenant rows carry `tenant_id` with row-level security, not an app filter.
- Migrations are expand/contract across **two** deploys, never one.

## Decision 5 — Trust boundaries

Authenticate at the edge, authorise on the server with facts the server owns —
never a `role` claim the client supplies.

- Cookies: `httpOnly`, `Secure`, `SameSite=Lax`, 30-minute idle, rotating refresh.
- Mutations are CSRF- or token-protected; `GET` never mutates.
- Secrets live in the platform store, rotated; a leaked key is a 1-hour incident.

## Decision 6 — Delivery

Deploy is not release: ship behind a flag, watch the error rate for 10 minutes,
then ramp 1 % → 10 % → 50 % → 100 %.

- Rollback is one rehearsed command; a runbook is a broken rollback.
- Error budget 99.9 % monthly (43 minutes) governs whether features ship.
- Logs, metrics and traces share one `request_id` before the first user.

## Rules that hold across every branch

1. **One owner per dataset** — one service writes it; everything else reads through it.
2. **Contracts before code** — API shape, schema, component API are artefacts.
3. **State has one home** — no second copy, anywhere.
4. **Failure states are designed** — loading, empty, error, partial.
5. **Authorisation is server-side**, from facts the server owns.
6. **Budgets are numbers**, enforced by CI.
7. **Nothing ships without a rollback**; flags separate deploy from release.
8. **Observability precedes launch** — one correlation id across services.

## Choosing a starting point

| Situation | Start with |
| --- | --- |
| new product, greenfield | `frontend-development-architect`, then API, then data |
| performance or SEO | `frontend-development-architect` → `web-performance-` |
| slow queries or data modelling | `database-engineering-architect` |
| API breaking clients | `api-development-architect` |
| security review or incident | `security-architect` |
| deploy pain, flaky tests | `testing-and-deployment-architect` |
| UI looks right but behaves wrong | `ui-ux-implementation-architect` |

## Architecture review questions

1. What renders each page, and where does its data come from?
2. Which service owns each write, and what enforces it?
3. What happens when each dependency is unavailable for one minute, one hour?
4. What is cached, for how long, invalidated how?
5. Who can call each endpoint, and where is that decided?
6. How does a change reach production, and how is it undone?
7. What will page under this design in a year?

## Failure modes at scale

- No one owns the contract between branches; each is someone's side project.
- The frontend owns business rules because the API was never designed.
- The database is the integration layer; services read each other's tables.
- Nothing is reversible: deploys, migrations and schema all go one way.
- Observability is per service and correlates nothing across a request.
- Budgets are opinions, so regressions are found by users.

## Verification receipts

1. A diagram naming the services, stores and boundaries, and the branch owning each.
2. `LCP ≤ 2.5 s`, `INP ≤ 200 ms`, `CLS ≤ 0.1` at p75 on throttled mobile, traced.
3. p95 API latency per endpoint at expected load, from a load test not a `curl`.
4. A timed restore of the latest backup into a scratch environment.
5. A rollback executed in staging, timed and evidenced.
6. Each branch's receipts for the current release, plus answers to the seven
   questions above, reviewed by someone who did not write the system.
