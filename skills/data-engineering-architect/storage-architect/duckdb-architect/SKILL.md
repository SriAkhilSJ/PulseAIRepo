---
name: duckdb-architect
description: Architect-level design with DuckDB and embedded analytics — when a single-node engine beats a warehouse, file formats and partitioning for scan efficiency, extension use (Parquet, Iceberg, Postgres), concurrency limits, and the pipelines that refresh local analytical stores. Use when analytics should run close to the data instead of in a cluster.
license: MIT
compatibility: DuckDB, Parquet, Arrow, SQLite, MotherDuck
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/storage-architect/duckdb-architect
  crusor-origin: original
  crusor-sources: "duckdb.org/docs; duckdb.org/docs/data/parquet; duckdb.org/docs/guides/performance"
  crusor-triggers: "duckdb, embedded analytics, single node analytics, parquet query, arrow, local warehouse, motherduck, olap in process"
  crusor-verified-on: "2026-10-30"
---

# DuckDB Architect

DuckDB is **a columnar engine inside your process**. For up to a few hundred GB it
replaces a warehouse, a cluster, and a lot of cost — if the file layout is sane.

## When to use

- Analytical workloads under ~100–500 GB.
- Per-tenant or per-customer analytics shipped with a product.
- Local development and CI pipelines that mirror warehouse SQL.
- Ad-hoc analysis over Parquet in object storage.

## When NOT to use

- Many concurrent writers or high-concurrency serving.
- Multi-terabyte joins needing distributed compute.
- Transactional OLTP requirements.

## Decision 1 — Where it runs

| Shape | Use |
|---|---|
| in-process (library) | CLI tools, services, tests |
| embedded in an app | per-customer analytics |
| server (MotherDuck/managed) | shared access, modest concurrency |
| CI/dev mirror | fast tests without a warehouse |

- One process, one writer: DuckDB is not a multi-writer database. Serialise writes
  through a queue or a single service.
- Concurrency for reads is limited by the process; scale by shipping the file to the
  client or by multiple processes on read-only copies.

## Decision 2 — Data layout

- Query Parquet directly for read-heavy analysis; ingest to DuckDB tables when
  repeated access justifies it.
- Partition files by the filter column (`year=`, `month=`) so the scan prunes.
- Avoid millions of tiny files; DuckDB's file-open cost dominates.
- Column pruning is automatic — select only the columns you need anyway, for I/O.

## Decision 3 — Extensions

- Parquet/JSON/CSV readers, Iceberg/Delta readers for lakehouse access, Postgres
  scanner for federation, httpfs for object storage.
- Federation is powerful for small lookups; do not build a distributed join across
  a remote Postgres.
- Pin extension versions in production images; behaviour changes between releases.

## Decision 4 — Performance

- Set `PRAGMA threads` to available cores; memory limit explicitly to avoid OOM on
  large joins.
- Sort/order data by common filter columns for zone-map skipping.
- Materialise expensive intermediate results as tables, not CTEs re-evaluated
  repeatedly in older versions.
- Measure with `EXPLAIN ANALYZE`; the plan shows scan and join costs directly.

## Decision 5 — Pipelines

- Build `.duckdb` files as artefacts: reproducible, versioned, refreshable.
- Refresh from source with idempotent loads; treat the file as derived state.
- Ship read-only files to clients where the data is per-tenant and small.
- For BI serving, put a thin API over queries rather than exposing SQL.

## Failure modes at scale

- One DuckDB file written by four services; lock errors and corruption risk.
- 40 GB of 2 MB Parquet files; scan overhead exceeds the actual work.
- DuckDB used as an OLTP store for a web app.
- Extension version drift between dev and production image; query behaviour differs.
- Memory limit unset; a big join OOMs the host process.

## Verification receipts

1. Workload sizing: data volume, query shapes, concurrency requirement.
2. Query timings on the chosen file layout versus a naive one.
3. Concurrency test showing the writer-serialisation plan.
4. Memory and thread limits set in the deployment configuration.
5. Refresh pipeline demonstrated to produce an identical file from source.
