---
name: fastify-architect
description: Architect-level Fastify guidance — schema-first routing and validation, plugin encapsulation boundaries, hook lifecycle ownership, serialisation performance, and the TypeScript typing patterns that keep schemas and handlers in sync. Use when choosing or reviewing Fastify for a Node API.
license: MIT
compatibility: Fastify 4/5; Node 20+
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/react-architect/nodejs-architect/fastify-architect
  crusor-origin: original
  crusor-sources: "fastify.dev/docs/latest; json-schema.org"
  crusor-triggers: "fastify, fastify plugin, fastify schema"
  crusor-verified-on: "2026-10-30"
---

# Fastify Architect

Fastify's advantages are **schemas** and **encapsulation**. Use it without them
and you have paid the learning curve for an Express clone.

## When to use

- JSON APIs where request/response schemas are the contract.
- Services where throughput and validation speed matter.
- Codebases that benefit from plugin-scoped encapsulation instead of global
  middleware.

## When NOT to use

- Heavy server-rendered pages — an MVC framework is the better tool.
- A team that will not maintain JSON schemas; then schema-first is a liability.

## Decision 1 — Schemas are the contract

- Every route declares `schema.body`, `querystring`, `params`, `response`.
- Response schemas are not optional: they drive fast serialisation **and**
  prevent accidental field leakage.
- Schema → TypeScript types via `json-schema-to-ts` or `typebox`, so a schema
  change breaks compilation, not production.
- Validation errors are mapped once (`setErrorHandler`) into your envelope.

## Decision 2 — Plugins and encapsulation

```
app.ts           register plugins, no routes
  plugins/db.ts  fastify-plugin (decorates, shares)
    routes/v1/*.ts  encapsulated routers
```

- `fastify-plugin` breaks encapsulation deliberately — use it only for
  infrastructure that must decorate the root (db, config, auth).
- Feature plugins stay encapsulated: their decorators/hooks do not leak.
- Register order matters; document it (config → db → auth → routes).

## Decision 3 — Lifecycle hooks

| Hook | Use |
|---|---|
| `onRequest` | request id, rate limit |
| `preValidation` | raw body checks |
| `preHandler` | auth/authorisation, load entity |
| `onSend` | response headers, mapping |
| `onClose` | release resources |

- Hooks are applied at the narrowest scope that needs them; a root-level hook
  affects every route including health checks — usually wrong.
- Async hooks must be awaited: a forgotten `await` reorders the pipeline.
- Auth via `decorate` + `preHandler`, and skip explicit for public routes.

## Decision 4 — Performance and deployment

- `pino` logging with redaction; request ids in every line.
- Keep the event loop clean: no sync fs/crypto in handlers, offload CPU work to
  workers.
- `connectionTimeout`/`requestTimeout` set explicitly; defaults are generous.
- Graceful shutdown on `SIGTERM`: `fastify.close()` after draining.

## Failure modes at scale

- Schemas declared for requests but not responses → leaks and slow serialisation.
- `fastify-plugin` used everywhere, encapsulation gone, root decorated by five
  features.
- Root-level auth hook plus a growing `if (route === ...)` exception list.
- Schema drift from TS types discovered at runtime.
- Error handler that returns 200 with an error body.

## Verification receipts

1. Every route has body + response schemas (script-checked).
2. Validation rejection test: extra field, wrong type, oversized payload.
3. Response test: no field outside the schema is serialised.
4. Hook scope review: which hooks are root-level and why.
5. Load test: throughput and p95 with the real schema set.
