---
name: database-engineering-architect
description: Architect-level data-layer direction — choosing the store from the access pattern, owning schema as a contract, the repository boundary, migration strategy for live systems, transaction and consistency rules, and the query budgets a service is built against. Use before any engine-specific database skill.
license: MIT
compatibility: Engine-agnostic (PostgreSQL, MongoDB, Redis, SQLite); any ORM
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/database-engineering-architect
  crusor-origin: original
  crusor-sources: "postgresql.org/docs; mongodb.com/docs; redis.io/docs; use-the-index-luke.com"
  crusor-triggers: "database, data model, schema design, migrations, transactions, indexing, sql, data layer"
  crusor-verified-on: "2026-10-30"
---

# Database Architect

The data layer outlives the application. Choose it by **access pattern**, write it
once, and never let a framework decide its shape.

## Leaf map

| Need | Skill |
|---|---|
| relational core, transactions, reporting | `postgres-architect` |
| document-shaped aggregates, flexible fields | `mongodb-architect` |
| cache, queues, ephemeral counters | `redis-architect` |
| TypeScript schema + migrations | `prisma-architect`, `drizzle-architect` |

## Decision 1 — Store from the access pattern

| Pattern | Store |
|---|---|
| entities with relationships, joins, constraints | relational (Postgres) |
| whole document read/written as a unit | document (Mongo) |
| counters, sessions, rate limits, hot reads | Redis (+ durable source) |
| derived read models, search, analytics | separate store, fed asynchronously |

- Polyglot persistence means **ownership**: exactly one service writes each
  dataset.
- Redis is never the only copy of anything you cannot regenerate.
- Do not add a second store to solve a query problem a good index would fix.

## Decision 2 — Schema is the contract

- Tables/documents are versioned by migration, reviewed like code, never edited
  by hand in production.
- Constraints in the database (not null, unique, foreign keys, check) — the
  application is not the only writer.
- IDs: stable, chosen once (UUIDv7/ULID for distributed, bigint for locality).
- Timestamps: UTC, with `created_at`/`updated_at` owned by the database.
- Money as integer minor units or `numeric`; never float.

## Decision 3 — Access boundary

```
service → repository → query (SQL/ORM)
```

- SQL lives in repositories only; a query in a controller is untestable.
- Transactions are opened at the service boundary, scoped to one use-case.
- Every query has an expected cost: rows scanned, rows returned, index used.
- N+1 is a design defect: batch/join or eager-load explicitly.

## Decision 4 — Migrations on a live system

- Expand → migrate → contract: add column, backfill, dual-write, switch reads,
  drop old.
- Long indexes built concurrently; no table-locking DDL in deploy windows.
- Backfills are batched, resumable, and idempotent.
- Every migration has a rollback plan or is provably forward-only.

## Decision 5 — Consistency and failure

- Know the isolation level you rely on; default is rarely what you assume.
- Money/inventory operations: row locks or optimistic versioning — decide.
- Timeouts on every query; a missing statement timeout is an outage waiting.
- Backups: restore rehearsed, not assumed; measure RPO/RTO.

## Decision 6 — Operations

- Connection pooling sized to the database, not to the app's concurrency.
- Monitoring: slow queries, lock waits, bloat/vacuum, replication lag.
- Read replicas for scale, with an explicit staleness policy.

## Failure modes at scale

- An ORM generating N+1 queries on the busiest list page.
- A migration that rewrote a 40M-row table during a deploy.
- Redis treated as the source of truth; a flush loses orders.
- Every service owning a different table in the same schema.
- No statement timeout: one bad query exhausts the pool.

## Verification receipts

1. Schema reviewed with constraints and indexes documented.
2. Query budget per endpoint: rows scanned + index used (EXPLAIN).
3. Migration plan for the riskiest table (expand/contract).
4. Restore rehearsal completed with measured time.
5. Pool sizing documented against DB limits.
