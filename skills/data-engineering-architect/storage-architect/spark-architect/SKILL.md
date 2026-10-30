---
name: spark-architect
description: Architect-level Spark job design — partitioning and shuffle mechanics, join strategies and skew, file layout and small-file problems, memory and executor sizing, checkpointing for long jobs, and the tuning order that finds the real bottleneck. Use when large transforms run on Spark.
license: MIT
compatibility: Apache Spark, Databricks, EMR, Dataproc
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/storage-architect/spark-architect
  crusor-origin: original
  crusor-sources: "spark.apache.org/docs/latest/sql-performance-tuning.html; spark.apache.org/docs/latest/tuning.html; docs.databricks.com/en/optimizations"
  crusor-triggers: "spark, pyspark, shuffle, data skew, executor memory, broadcast join, partition tuning, small files, spark job slow"
  crusor-verified-on: "2026-10-30"
---

# Spark Architect

Spark performance is **shuffle, skew, and file layout** — in that order. Cluster
size is usually the last thing to change.

## When to use

- Transforms over hundreds of GB to petabytes.
- Existing jobs that are slow, expensive, or failing on memory.
- Designing a lakehouse write path.

## When NOT to use

- Data fits comfortably in a warehouse or DuckDB — Spark is overhead.
- Simple scheduled SQL on a warehouse that has its own engine.

## Decision 1 — Partitioning

- Target 100–200 MB per output file, 128 MB–1 GB per task input.
- Repartition before writing, not after: the file layout is what downstream pays.
- Partition columns must match query filters; too many partitions = small files.
- `repartition` for even distribution, `coalesce` for reducing without a full
  shuffle — know which one you are paying for.

## Decision 2 — Shuffle

- Every `groupBy`, `join`, `distinct`, and `repartition` is a shuffle: network,
  disk, and time.
- Reduce shuffle by filtering before joins and projecting only needed columns.
- `spark.sql.shuffle.partitions` default is wrong for most data sizes — tune to
  data volume ÷ ~200 MB.
- Adaptive query execution (`AQE`) coalesces partitions and handles skew; enable it
  and verify it is actually engaging.

## Decision 3 — Joins

| Size | Strategy |
|---|---|
| small (< ~100 MB) | broadcast join, no shuffle |
| large × large | sort-merge, tuned partitions |
| skewed key | salting, or AQE skew join |
| range/interval | bucketing or range join carefully |

- Broadcasting something too large causes OOM on the driver/executors — check
  sizes, do not guess.
- Key skew is the classic: one tenant with 80% of rows. Salt the hot key or let AQE
  split it.
- Join order matters less than filter pushdown; ensure predicates reach the scan.

## Decision 4 — Memory and sizing

- Executor memory must hold a partition plus overhead; more executors do not fix a
  skewed partition.
- Driver memory for collect-heavy operations; avoid `collect()` on large results.
- Cache only what is reused multiple times; caching everything evicts what matters.
- Dynamic allocation where available; static sizing over-provisions for the peak
  stage.

## Decision 5 — Reliability

- Idempotent writes: partition overwrite or merge with a deterministic key.
- Checkpoint long lineages/streaming jobs to durable storage.
- Retry with task-level retries; a single bad record should not kill the job —
  quarantine it.
- Job metrics exported: stage times, shuffle read/write, spill, task failures.

## Decision 6 — Tuning order

1. Read the Spark UI: which stage dominates?
2. Fix file layout and pruning before touching memory.
3. Fix skew before adding executors.
4. Tune shuffle partitions and AQE next.
5. Then memory/executors.
6. Only then consider a bigger cluster.

## Failure modes at scale

- 300k small files; job spends more time listing than computing.
- One hot key; 199 tasks finish in a minute, one runs for an hour.
- Broadcasting a 2 GB table; executor OOM loop.
- `collect()` on 50M rows to "just check".
- Cluster doubled to fix a skew problem that needed salting.

## Verification receipts

1. Spark UI stage breakdown for the heaviest job, with the bottleneck named.
2. File-size and partition-count report for the output table.
3. Skew analysis: key distribution for the main join.
4. Before/after timings for each tuning change, one at a time.
5. Cost per run (DBUs/executor-hours) recorded before and after.
