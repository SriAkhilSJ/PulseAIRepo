---
name: prisma-architect
description: Architect-level Prisma guidance — schema ownership and migration workflows, relation loading and the N+1 traps, transaction and raw-SQL escape hatches, client instantiation for serverless, and when Prisma's abstraction is the wrong tool. Use when a TypeScript service uses Prisma.
license: MIT
compatibility: Prisma 5/6+; PostgreSQL/MySQL/SQLite
metadata:
  crusor-domain: website-architect
  crusor-path: database-engineering-architect/prisma-architect
  crusor-origin: original
  crusor-sources: "prisma.io/docs/orm; prisma.io/docs/orm/prisma-client/queries/relation-queries"
  crusor-triggers: "prisma, prisma schema, prisma migrate, orm, typescript orm, drizzle vs prisma"
  crusor-verified-on: "2026-10-30"
---

# Prisma Architect

Prisma trades SQL control for **types and migrations**. Use it where that trade
is good, and know exactly where it is not.

## When to use

- TypeScript service with a relational schema and fast iteration needs.
- Team values generated types and a declarative schema over hand-written SQL.
- CRUD-heavy domains with moderate query complexity.

## When NOT to use

- Heavy analytical SQL, CTEs, window functions → raw SQL or a SQL-first ORM
  (see `drizzle-architect`).
- Very high-throughput hot paths where the query layer must be transparent.
- Multi-schema/polyglot setups that need fine-grained DB control.

## Decision 1 — Schema is still the source of truth

- `schema.prisma` mirrors the database, not the other way round: constraints,
  indexes (`@@index`, `@@unique`) and relations declared explicitly.
- Do not let the ORM's defaults decide column types for money, timestamps, or
  enums.
- `@@map`/`@map` when the DB naming convention differs; keep one convention
  per project.

## Decision 2 — Migrations

- `prisma migrate dev` locally, `migrate deploy` in CI/CD — never `db push` on
  a shared environment.
- Every migration is reviewed; generated SQL is read before it ships.
- Destructive changes are split: expand → backfill (script) → switch → contract.
- Shadow database in CI so drift is caught before production.

## Decision 3 — Queries and N+1

- `include`/`select` explicitly; returning whole models leaks fields and joins
  more than needed.
- List endpoints: check the generated query count. A loop with `await` inside is
  N+1 — batch with `findMany({ where: { id: { in: ids } } })`.
- `select` narrow columns for hot reads; wide rows cost memory and bandwidth.
- Pagination: cursor-based (`cursor`/`take`) for large sets, not `skip`.

## Decision 4 — Transactions

- `$transaction` for multi-write invariants; interactive transactions stay
  short (default timeout is not a design tool).
- Never call an external API inside a transaction.
- Isolation level explicit where the invariant depends on it.

## Decision 5 — Runtime and escape hatches

- One client instance per process; in serverless, instantiate per invocation or
  use a pooler (`pgbouncer`/Accelerate) — a client per request exhausts
  connections.
- `$queryRaw` with tagged templates (parameterised) for what the ORM cannot
  express; typed with `$queryRaw<T>`.
- Log slow queries (`log: ['query']` in dev only); measure before optimising.

## Failure modes at scale

- `include` everything → huge payloads and slow serialisation.
- N+1 inside a map over 500 records.
- `db push` on staging silently dropping a column.
- New client per request in a serverless function → connection storm.
- Raw SQL built by string concatenation.

## Verification receipts

1. Generated SQL reviewed for the top 5 queries.
2. Query-count test on the busiest list endpoint (no N+1).
3. Migration plan for a destructive change (expand/contract).
4. Connection behaviour verified under concurrency (pooler or singleton).
5. Raw-SQL usages audited as parameterised.
