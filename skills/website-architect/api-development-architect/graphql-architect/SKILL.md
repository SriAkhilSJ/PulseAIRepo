---
name: graphql-architect
description: Architect-level GraphQL guidance — schema design and nullability, resolver boundaries and the N+1/DataLoader problem, authorization per field, query cost and depth limits, pagination connections, and the operational cost that decides whether GraphQL is worth it. Use when designing or reviewing a GraphQL API.
license: MIT
compatibility: GraphQL 16+; Apollo/Yoga/graphql-js; any server language
metadata:
  crusor-domain: website-architect
  crusor-path: api-development-architect/graphql-architect
  crusor-origin: original
  crusor-sources: "graphql.org/learn; spec.graphql.org; graphql.org/learn/security"
  crusor-triggers: "graphql, schema, resolvers, dataloader, n+1 graphql, apollo, graphql federation, query depth"
  crusor-verified-on: "2026-10-30"
---

# GraphQL Architect

GraphQL moves **query composition to the client**, which means the server must
defend its own cost. That is the entire architecture problem.

## When to use

- Many clients need different slices of the same graph.
- Aggregating several services behind one schema (federation).
- Mobile clients that cannot afford over-fetching.

## When NOT to use

- Simple resource APIs with stable clients — REST is cheaper to operate.
- File transfer, heavy binary, or cache-heavy public content.
- A team without the budget for query cost control and schema governance.

## Decision 1 — Schema design

- Model the domain, not the database: no table-shaped types leaking `_id`.
- Nullability is a promise: non-null means "the server guarantees this", so use
  it where you can actually hold it; everything else is nullable.
- Input types are separate from output types; never reuse one for both.
- Evolve additively; deprecate with `@deprecated(reason:)`, remove on a
  schedule.
- One schema, versionless; breaking changes are additive migrations for clients.

## Decision 2 — Resolvers and N+1

- A resolver answers one field; it never runs a query per list item.
- **DataLoader is mandatory** for any relation resolved inside a list — batch +
  cache per request.
- Keep resolvers thin: auth check → service call → map. Business logic lives in
  services shared with REST if you have both.
- Resolve authorization at field level, not just at the root — a nested field
  can leak another tenant's data.

## Decision 3 — Cost control (non-negotiable)

| Control | Why |
|---|---|
| depth limit | stops `user.friends.friends…` bombs |
| query cost/complexity budget | stops one query costing 10k rows |
| pagination required on lists | `first` with a max |
| persisted queries in prod | smaller, cacheable, allow-listed |
| timeout per operation | one slow resolver must not hold the connection |

- Reject a query that exceeds budget **before** executing it.
- Introspection disabled in production for public APIs (or allow-listed).

## Decision 4 — Pagination and errors

- Relay-style connections (`edges`/`node`/`pageInfo`) or a documented cursor
  pattern — one of them, consistently.
- Partial failures: `errors[]` alongside `data`; clients must handle both.
- Error codes in `extensions.code`, stable and documented.
- Never return `null` for a permission failure — raise a typed error.

## Decision 5 — Operations

- Operation-level tracing by field; find the expensive resolver.
- Cache at the edge only for public, non-personalised queries.
- Schema registry + breaking-change detection in CI.
- Federation: entity ownership documented; no field resolved by two services.

## Failure modes at scale

- N+1 through resolvers — 200 SQL queries for one screen.
- No depth/cost limits: one client request takes the API down.
- Field-level authorization absent → nested data leaks.
- Nullable everything → clients cannot trust the schema, so they add defensive
  code everywhere.
- Introspection + playground open in production.

## Verification receipts

1. Query-cost test: a pathological query is rejected, not executed.
2. N+1 measurement: query count per operation, before/after DataLoader.
3. Field-auth matrix test on nested types (cross-tenant access denied).
4. Schema diff in CI with breaking-change report.
5. p95 latency and resolver traces for the top 5 operations.
