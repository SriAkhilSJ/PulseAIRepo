---
name: iceberg-architect
description: Architect-level open table format design — Iceberg/Delta layout, partition evolution and hidden partitioning, snapshots and time travel, compaction and file sizing, catalog and metadata management, and the read/write engine compatibility that decides whether the format pays off. Use when a lakehouse must be engine-agnostic.
license: MIT
compatibility: Apache Iceberg, Delta Lake, Hudi; Spark, Trino, Flink
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/storage-architect/iceberg-architect
  crusor-origin: original
  crusor-sources: "iceberg.apache.org/docs/latest; iceberg.apache.org/docs/latest/spec; delta.io/docs"
  crusor-triggers: "iceberg, delta lake, hudi, table format, lakehouse, snapshot, time travel, compaction, manifest, open table format"
  crusor-verified-on: "2026-10-30"
---

# Iceberg / Open Table Format Architect

An open table format is **a metadata layer that turns files into a table**. It buys
engine independence and time travel; it costs you table maintenance.

## When to use

- Multiple engines (Spark, Trino, Flink, Snowflake, DuckDB) must read the same data.
- Object storage holds the source of truth, not a proprietary warehouse.
- You need time travel, schema evolution, or ACID writes on files.

## When NOT to use

- A single warehouse engine already serves everything reliably.
- Small data (< a few hundred GB) where plain Parquet is fine.

## Decision 1 — Format

| Format | Notes |
|---|---|
| Iceberg | broadest engine support, hidden partitioning, strong evolution |
| Delta | best in the Databricks/Spark ecosystem |
| Hudi | upserts and incremental reads, heavier operational story |

- Choose by the engines you actually run, not by benchmark blogs.
- Mixing formats in one lake doubles the maintenance burden.

## Decision 2 — Partitioning

- Hidden partitioning: define `days(ts)` once; queries filter on `ts` and prune
  automatically.
- Partition on the column used in **most** filters; over-partitioning creates
  metadata explosion with tiny files.
- Partition evolution is supported — but rewriting history to a new spec is a
  migration, not a config change.
- Prefer fewer, larger partitions plus sort/cluster within files.

## Decision 3 — Files and compaction

- Target 128–512 MB per data file; millions of small files kill planning time and
  cost.
- Compaction (rewrite) jobs are mandatory: scheduled, monitored, and budgeted.
- Sort within files on the filter column to enable data skipping.
- Delete files (position/equality deletes) accumulate; a reader that handles them
  slowly is a symptom, not a bug.

## Decision 4 — Metadata and catalog

- Catalog choice matters: REST catalog, Glue, Nessie, Polaris — it holds the pointer
  to current metadata and is the concurrency authority.
- Metadata files should be small in number; expire old snapshots on a schedule.
- Time travel is retention, not free storage — expire snapshots deliberately.
- Access control is enforced at catalog/table level; file-level ACLs are not a
  security model on object storage.

## Decision 5 — Write path

- Writers need optimistic concurrency support; two writers to one table without a
  commit protocol corrupt expectations, not files.
- Streaming writes create many small files — pair with compaction or use engines
  that handle it.
- Schema evolution: adding columns is safe; dropping/renaming needs a migration
  plan and consumer coordination.
- Exactly-once claims depend on the engine and sink; test duplicates explicitly.

## Failure modes at scale

- 900k files in one table; every query spends 30 s planning.
- Iceberg table read by a version of Trino that predates the delete-file support
  used; wrong results.
- Snapshots never expired; metadata storage rivals data storage.
- Two Spark jobs writing the same table with no catalog lock; lost commits.
- Partitioned by hour over three years; 26k partitions, metadata thrash.

## Verification receipts

1. Format and catalog choice with the engines that must interop.
2. File-size distribution report before and after compaction.
3. Time-travel query demonstrating a previous snapshot.
4. Snapshot expiry job configured with retention policy.
5. Concurrent-write test proving one commit wins cleanly.
