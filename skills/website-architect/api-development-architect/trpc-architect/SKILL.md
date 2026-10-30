---
name: trpc-architect
description: Architect-level tRPC guidance — when a TypeScript-only RPC boundary beats REST, router and procedure organisation, middleware and context contracts, input validation boundaries, and keeping a monorepo-coupled API from leaking into public surfaces. Use when frontend and backend share a TypeScript repo.
license: MIT
compatibility: tRPC v11; TypeScript 5+; React/Next/Vue clients
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/api-development-architect/trpc-architect
  crusor-origin: original
  crusor-sources: "trpc.io/docs; trpc.io/docs/server/procedures"
  crusor-triggers: "trpc, typescript rpc, procedures, routers, end-to-end typesafety, rsc trpc"
  crusor-verified-on: "2026-10-30"
---

# tRPC Architect

tRPC buys **end-to-end type safety by giving up the network boundary**. That trade
is excellent internally and catastrophic the moment a non-TypeScript client
appears.

## When to use

- Frontend and backend in one TypeScript repo, deployed together or in lockstep.
- Internal tools, dashboards, admin panels.
- You want no codegen, no schema drift, no hand-written client types.

## When NOT to use

- Public API, mobile clients, partners, or anything with a release lag.
- Multi-language backend.
- Team that deploys client and server independently for long periods — coupled
  versions break builds.

## Decision 1 — The boundary is the repo

- tRPC assumes client and server versions move together. If that assumption is
  false for any consumer, expose REST/GraphQL for them and keep tRPC internal.
- Never let a public endpoint proxy 1:1 to a procedure without a real contract —
  you inherit coupling with a public promise attached.
- Version skew policy: client and server in the same deploy, or a documented
  compatibility window.

## Decision 2 — Routers as bounded contexts

```
server/api/
  trpc.ts          initTRPC, context, middleware
  routers/
    orders.ts      procedures for one context
    billing.ts
  root.ts          mergeRouters
```

- One router per bounded context, named after the domain, not the table.
- Procedures are `query` (read) or `mutation` (write) — no side effects in a
  query, because queries are retried and prefetched.
- `publicProcedure` / `protectedProcedure` derived once in `trpc.ts`;
  authorization middleware attaches the actor to context.

## Decision 3 — Input and context contracts

- Every procedure takes a zod (or valibot) input; no untyped `any`.
- Context is built per request: db client, session, request id — never a module
  global.
- Return shapes are chosen deliberately: no ORM rows leaking to the client.
- Errors: `TRPCError` with a code (`UNAUTHORIZED`, `NOT_FOUND`, `CONFLICT`) and
  a machine-readable cause; the client maps codes to UI.

## Decision 4 — Fetching on the client

- One batched link (`httpBatchLink`) with a small window; avoid waterfall calls.
- Cache/invalidation goes through TanStack Query (see
  `tanstack-query-architect`) — tRPC does not own the client cache.
- Prefetch on the server where SSR matters; hydration keys must match.

## Decision 5 — Operations

- Typed errors are not enough: log request id, user, procedure and duration
  server-side.
- Rate-limit per procedure class (expensive mutations separately).
- Timeouts on the server; the client shows a retry path, not a spinner forever.

## Failure modes at scale

- A partner integration "just calling our tRPC endpoint" — now every internal
  rename is a public breaking change.
- Monolithic `appRouter` with 200 procedures and no ownership.
- Queries with side effects (sending emails) that fire twice on retry.
- Context built from module-level state, mixing users under concurrency.
- Client and server deployed separately → type mismatch at runtime, no compile
  error.

## Verification receipts

1. Procedure inventory: owner, auth level, input schema.
2. Authorization test per router (anonymous, wrong tenant, correct user).
3. Query-side-effect audit: no mutations in `query` procedures.
4. Deploy-coupling check: client/server version compatibility documented.
5. Batch/waterfall measurement on the heaviest screen.
