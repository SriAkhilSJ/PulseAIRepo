---
name: postgres-architect
description: Architect-level PostgreSQL guidance — relational schema design, index selection and query plans, transaction isolation and locking, connection pooling, partitioning and vacuum, and the queries that quietly kill a production database. Use when designing or tuning Postgres.
license: MIT
compatibility: PostgreSQL 14+
metadata:
  crusor-domain: website-architect
  crusor-path: database-engineering-architect/postgres-architect
  crusor-origin: original
  crusor-sources: "postgresql.org/docs/current; use-the-index-luke.com; wiki.postgresql.org (lock monitoring)"
  crusor-triggers: "postgres, postgresql, psql, explain analyze, indexes, vacuum, partitioning, sql tuning, isolation level"
  crusor-verified-on: "2026-10-30"
---

# PostgreSQL Architect

Postgres is an **index and concurrency machine**. Most production pain is a
missing index, a wrong index, or a transaction holding a lock too long.

## When to use

- Designing a relational schema or reviewing one.
- A query is slow, a lock is blocking, or the DB is CPU-bound.
- Choosing between JSONB, a join table, or partitioning.

## When NOT to use

- Key-value or cache workloads (see `redis-architect`).
- Document aggregates with no relational needs (see `mongodb-architect`).

## Decision 1 — Schema

- Natural keys are rare: use `bigint generated always as identity` or UUIDv7.
- Constraints do the enforcing: `NOT NULL`, `UNIQUE`, `FOREIGN KEY`, `CHECK`.
- Normalise first; denormalise with a measured reason (and a way to rebuild).
- JSONB for genuinely open data, indexed with GIN where queried — never as a
  substitute for columns you filter on.
- `timestamptz` everywhere; money as `numeric` or integer minor units.

## Decision 2 — Indexes

| Query shape | Index |
|---|---|
| equality + range on one table | composite, equality column first |
| sort + filter | index matching `ORDER BY` |
| substring/array/JSON search | GIN (`pg_trgm`, `jsonb_path_ops`) |
| hot subset only | partial index (`WHERE status = 'open'`) |
| covering read | `INCLUDE` columns |

- Every index is write cost; drop the unused ones (`pg_stat_user_indexes`).
- Multi-column order matters; a leading low-cardinality column is usually wrong.
- Functions on columns kill index use — index the expression instead.

## Decision 3 — Queries

- Read the plan: `EXPLAIN (ANALYZE, BUFFERS)`. Seq scan on a big table is a
  finding, not a mystery.
- `SELECT *` on wide tables moves bytes you discard; project columns.
- Pagination: keyset (`WHERE id > $1`) not `OFFSET` on large sets.
- N+1 → join or batch; measure queries per endpoint in tests.

## Decision 4 — Transactions and locks

- Default `READ COMMITTED`; know when you need `REPEATABLE READ` or explicit
  locking.
- Lock rows in a **consistent order** to avoid deadlocks; retry on 40P01/40001.
- Keep transactions short: no network calls inside a transaction.
- `SELECT ... FOR UPDATE SKIP LOCKED` for queues.
- Long-running DDL: `CREATE INDEX CONCURRENTLY`, `ALTER TABLE ... ADD COLUMN`
  with defaults (safe in PG 11+), avoid rewrites.

## Decision 5 — Operations

- Pool per app instance sized to `max_connections` (or a pooler like PgBouncer
  in transaction mode).
- Set `statement_timeout` and `idle_in_transaction_session_timeout`.
- Autovacuum tuned for high-churn tables; watch bloat and wraparound.
- Partition large time-series tables by range; keep partition pruning in mind
  for queries.

## Failure modes at scale

- Missing index on a foreign key → sequential scans under load.
- A transaction held open while calling an external API → locks pile up.
- `OFFSET 100000` pagination getting slower every month.
- Unbounded `IN (...)` lists from a batch job.
- Bloat never addressed; disk and latency creep.

## Verification receipts

1. `EXPLAIN (ANALYZE, BUFFERS)` for the top 5 queries, before/after.
2. Index inventory with usage stats; unused indexes listed for removal.
3. Lock/deadlock check under a concurrency test.
4. Migration executed with concurrent index creation and measured time.
5. Pool sizing vs `max_connections`, with `statement_timeout` set.
