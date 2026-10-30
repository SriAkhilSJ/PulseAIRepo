---
name: batch-pipeline-architect
description: Architect-level batch and ELT design — full versus incremental loads, watermarks and late-arriving data, idempotent and replayable jobs, backfill strategy, partitioning for pruning, and the cost behaviour of large scans. Use when building scheduled pipelines from operational systems into an analytical store.
license: MIT
compatibility: dbt, Spark, SQL warehouses, Airflow/Dagster, Fivetran/Airbyte
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/ingestion-architect/batch-pipeline-architect
  crusor-origin: original
  crusor-sources: "docs.getdbt.com/docs/build/incremental-models; spark.apache.org/docs/latest/sql-performance-tuning.html"
  crusor-triggers: "etl, elt, batch job, incremental load, backfill, watermark, spark job, nightly job, data ingestion, cdc, nightly etl, duplicate rows"
  crusor-verified-on: "2026-10-30"
---

# Batch Pipeline Architect

A batch pipeline is **a deterministic function of a time window**. Idempotency and
replay are not refinements — they are the difference between a platform and a
guess.

## When to use

- Scheduled extraction from databases, APIs, or files into a warehouse.
- A nightly job is slow, expensive, or silently wrong.
- Designing incremental loads and backfills.

## When NOT to use

- Sub-minute freshness is required → `streaming-architect`.
- The job has no schedule and no consumer — it is an exploration.

## Decision 1 — Full or incremental

| Load | Use when |
|---|---|
| full refresh | small tables (<1M rows), volatile schemas, correctness first |
| incremental append | immutable events |
| incremental upsert/merge | mutable entities with an `updated_at` |
| CDC | high volume, deletes matter, source can emit a log |

- Incremental requires a **reliable high-water mark**: `updated_at` with a skew
  margin, or a monotonic source id.
- Deletes need an explicit strategy: soft-delete flag, tombstone table, or CDC.
  Most "missing rows" incidents are unhandled deletes.

## Decision 2 — Idempotency and replay

- Every job writes to a partition keyed by the logical batch (date/hour/run id),
  and replaces it atomically rather than appending twice.
- Retries must produce the same result: `MERGE` on a stable key, or
  delete-partition-then-insert.
- Late-arriving data has a stated policy: re-open the affected window, or accept
  and document the cutoff.
- A job that cannot be re-run for a past window is a bug, not a design choice.

## Decision 3 — Backfills

- Backfill is a first-class operation: parameterised by window, rate-limited,
  and separate from the daily schedule.
- Order backfills oldest-first only if downstream is not consumed mid-run;
  otherwise publish only after the whole window completes.
- Isolate backfill compute so it cannot starve the production run.
- Estimate cost before starting; large scans surprise people.

## Decision 4 — Layout and performance

- Partition by the column you filter on (usually date); cluster/sort by the high
  cardinality filter (tenant, id).
- Partition granularity matches the query pattern — daily is the default,
  hourly only when needed.
- Prune before you scale: most slow jobs read 100× more than they need.
- Push filters to the source; never extract everything then filter in the
  warehouse.
- File sizes: avoid millions of tiny files — compact.

## Decision 5 — Schema evolution

- Land raw with schema-on-write where possible; capture unexpected columns rather
  than dropping them.
- Type changes (int→float, string dates) get an explicit migration, not a cast
  that silently nulls.
- Track schema drift with alerts — a new nullable column is harmless, a renamed
  one is an outage.

## Failure modes at scale

- Append-only incremental job double-loading after a retry.
- `updated_at` without a skew margin, so a transaction committing at 23:59:59
  lands after the 00:00 run and is lost forever.
- A backfill that rewrites the table while dashboards read it.
- Daily partition, hourly queries: every query scans the full history.
- Twelve thousand 2 KB parquet files in one partition.

## Verification receipts

1. Same window run twice → identical output row counts and checksums.
2. Watermark and skew margin documented, with the late-data policy.
3. One backfill executed in isolation, cost measured.
4. Partition pruning shown in a query plan for a typical filter.
5. Delete propagation test: a removed source row disappears downstream.
