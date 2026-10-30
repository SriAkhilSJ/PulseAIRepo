# website-architect

Architect-level skills for building web products: frontend, backend, data, API,
UI/UX, security, testing and deployment.

This is a **taxonomy container**, not a skill. Only leaf directories that carry a
`SKILL.md` are loadable skills (Agent Skills standard —
`agentskills.io/specification`). Containers hold structure; they are never
injected into the model.

## Branches

| Branch | Skills | Covers |
|---|---|---|
| `frontend-development-architect/` | 33 | markup, languages, styling, build, motion, pwa, a11y, perf, seo, i18n, forms, tests, frameworks, runtime, 3d |
| `backend-development-architect/` | 5 | service layout, runtimes, python (flask/fastapi/django), node (express/nestjs/fastify) |
| `database-engineering-architect/` | 6 | postgres, mongodb, redis, prisma, drizzle, schema/migrations/transactions |
| `api-development-architect/` | 7 | contracts, REST, GraphQL, tRPC, gRPC, auth, rate limiting |
| `ui-ux-implementation-architect/` | 5 | handoff contract, interaction patterns, design-system ops, microcopy |
| `security-architect/` | 6 | threat models, OWASP classes, authz models, secrets, supply chain, browser |
| `testing-and-deployment-architect/` | 7 | test strategy, CI gates, containers, observability, rollout, incidents |

`69` architect skills in total; every branch directory carries its own `SKILL.md`.

## What "architect-level" means here

A skill in this tree answers **decisions and boundaries**, not "how to write
code":

- when to use the technology, and **when not to**
- the decision matrix against its alternatives
- canonical structure: folder ownership, module boundaries, import rules
- contracts between layers, and where data may cross
- failure modes, scale limits, and what degrades silently
- the anti-patterns that cause rewrites
- verification receipts that prove a design holds
- version notes: what changed, what is deprecated

If a skill could be replaced by reading the framework's own documentation, it
does not belong here.

## Naming

`name` in `SKILL.md` must equal the leaf directory name and be globally unique
(Agent Skills spec). The path carries the taxonomy; the name carries the
identity. Collisions across domains are resolved with a qualifier
(`react-testing`, not `testing`).

## Provenance

Every skill records where it came from in `metadata`:

```yaml
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development/react
  crusor-origin: adapted | original
  crusor-sources: "repo@sha (skill)"
  crusor-verified-on: "YYYY-MM-DD"
```
