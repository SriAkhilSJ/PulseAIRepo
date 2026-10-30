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

A web product is **six decisions in a trench coat**: how it renders, what serves
it, where state lives, how clients talk to it, what it looks like, and how it
ships safely. This skill names which branch owns each one.

## When to use

- Starting a web product, or re-planning one that has outgrown its structure.
- A cross-cutting problem: performance, security, data ownership, delivery.
- Choosing which branch of this shelf a plan should open.

## When NOT to use

- A single-branch question — go straight to that branch's crown.
- Native apps, mobile apps or desktop runtimes: those are separate domains.

## Branch map

| Decision | Branch |
|---|---|
| rendering model, components, styling, motion, a11y, perf, SEO, i18n | `frontend-development-architect` |
| language and runtime for server code | `backend-development-architect` |
| schema, indexing, migrations, transactions | `database-engineering-architect` |
| contract between clients and server | `api-development-architect` |
| design → code, interaction, design-system ops | `ui-ux-implementation-architect` |
| trust boundaries, permissions, secrets, supply chain | `security-architect` |
| tests, CI, environments, telemetry, rollout | `testing-and-deployment-architect` |

## Rules that hold across every branch

1. **One owner per dataset.** A table or document is written by exactly one
   service/context; everything else reads through it.
2. **Contracts before code.** API shape, schema and component API are agreed
   before implementation; they are the reviewable artefacts.
3. **State has one home.** Server data in a query cache, UI state with the
   screen, cross-cutting client state in one store. Never duplicated.
4. **Every surface defines its failure states.** Loading, empty, error, partial
   and disabled are designed, not discovered.
5. **Every boundary is authenticated and authorised server-side**, using facts
   the server owns.
6. **Budgets are numbers.** Performance, bundle size, test duration and pipeline
   time have targets, and CI enforces them.
7. **Nothing ships without a rollback.** Deploys are reversible, flags separate
   deploy from release, migrations are expand/contract.
8. **Observability precedes launch.** Logs, metrics and traces with a
   correlation id exist for every service before its first user.

## Choosing a starting point

| Situation | Start with |
|---|---|
| new product, greenfield | `frontend-development-architect` for the shell, then API, then data |
| performance or SEO problem | `frontend-development-architect` → `web-performance-` / `seo-architect` |
| slow queries or data modelling | `database-engineering-architect` |
| API breaking clients | `api-development-architect` |
| security review or incident | `security-architect` |
| deploy pain, flaky tests | `testing-and-deployment-architect` |
| UI looks right but behaves wrong | `ui-ux-implementation-architect` |

## Architecture review questions

1. What renders each page, and where does its data come from?
2. Which service owns each write, and what enforces it?
3. What happens when each dependency is unavailable — for one minute, one hour?
4. What is cached, for how long, and how is it invalidated?
5. Who can call each endpoint, and where is that decided?
6. How does a change reach production, and how is it undone?
7. What will page under this design in a year?

## Failure modes at scale

- Every branch is someone's side project: no one owns the contract between them.
- The frontend owns business rules because the API was never designed.
- The database is the integration layer; services read each other's tables.
- Nothing is reversible: deploys, migrations and schema changes all go one way.
- Observability exists per service but nothing correlates across a request.
- Budgets are opinions, so regressions are discovered by users.

## Verification receipts

1. A diagram naming the services, stores and boundaries.
2. Each branch's own receipts collected for the current release.
3. A written answer to the seven questions above, reviewed by someone who did
   not write the system.
