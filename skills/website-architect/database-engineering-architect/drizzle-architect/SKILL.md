---
name: drizzle-architect
description: Architect-level Drizzle ORM guidance — SQL-first schema definition, migration generation and review, typed query composition, relation and join strategy, and the cases where Drizzle beats Prisma or hand-written SQL. Use when a TypeScript service needs transparent SQL with types.
license: MIT
compatibility: Drizzle ORM 0.30+; drizzle-kit; PostgreSQL/MySQL/SQLite
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/database-engineering-architect/drizzle-architect
  crusor-origin: original
  crusor-sources: "orm.drizzle.team/docs/overview; orm.drizzle.team/docs/migrations"
  crusor-triggers: "drizzle, drizzle orm, drizzle kit, sql first orm, typescript sql"
  crusor-verified-on: "2026-10-30"
---

# Drizzle Architect

Drizzle is **SQL with types bolted on**. It does not hide the query, so the
architect's job is to keep the SQL honest and the schema deliberate.

## When to use

- TypeScript service where the team wants to see and control the SQL.
- Complex reads (joins, aggregates, CTEs) that fight a higher-level ORM.
- Serverless/edge runtimes needing a thin client.
- Greenfield projects comfortable writing SQL.

## When NOT to use

- Team without SQL fluency — the abstraction will not save them.
- A CRUD app where generated migrations and admin tooling matter more than
  query control (see `prisma-architect`).

## Decision 1 — Schema in TypeScript, rules in the database

- Table definitions carry constraints: `primaryKey`, `notNull`, `uniqueIndex`,
  `references`, `check`.
- Indexes declared next to the table they serve; a query without an index is a
  decision someone must justify.
- Column types explicit (money, timestamps with timezone, enums) — the ORM will
  happily accept a worse default.
- Relations (`relations()`) are for the query API, not the source of truth;
  the FK in the schema is.

## Decision 2 — Migrations

- `drizzle-kit generate` produces SQL you **read**; `migrate` applies it.
- Migrations are committed, ordered, and applied by the deploy pipeline, not by
  a developer's laptop.
- `drizzle-kit push` is for local prototyping only.
- Destructive changes split into expand/backfill/contract like any other
  migration system.

## Decision 3 — Queries

- Use the query builder for composition; drop to `sql``` ` for expressions
  (window functions, CTEs, `ON CONFLICT`).
- Always parameterise; template interpolation in `sql``` ` is bound, string
  concatenation is injection.
- Select explicit columns for wide tables.
- Joins: prefer explicit `leftJoin`/`innerJoin` with `where` on the driving
  table so the planner has an index to use.
- Batch reads with `inArray`; never loop a query inside a map.

## Decision 4 — Transactions and connections

- `db.transaction(async (tx) => …)` for invariants across writes; keep them
  short, no external calls inside.
- One client per process; serverless needs a pooled driver (Neon/PlanetScale/
  PgBouncer).
- Set statement timeouts at the connection level.

## Decision 5 — Type discipline

- Infer types from the schema (`InferSelectModel`, `InferInsertModel`); never
  hand-write a duplicate row type.
- Map DB rows to domain objects at the repository boundary; do not leak table
  shapes through the app.
- Zod schemas for input validation stay separate from table types.

## Failure modes at scale

- Schema drift because `push` was used on a shared database.
- Every query joining five tables because relations were declared casually.
- `sql` strings interpolating user input.
- Row types leaking into API responses (and columns you did not mean to expose).
- New client per request in a serverless handler.

## Verification receipts

1. Generated migration SQL reviewed in the PR.
2. `EXPLAIN` for the top queries from the repository layer.
3. No string-concatenated SQL (grep + review).
4. Query-count test on list endpoints.
5. Connection strategy documented for the deploy target.
