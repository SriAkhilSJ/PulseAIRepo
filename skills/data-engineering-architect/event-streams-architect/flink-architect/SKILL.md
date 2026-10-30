---
name: flink-architect
description: Architect-level Flink design — event time and watermarks, stateful operators and state size, checkpointing and exactly-once sinks, savepoints for upgrades, backpressure diagnosis, and the job-graph choices that decide whether a pipeline survives a bad day. Use when stream processing is stateful and correctness-critical.
license: MIT
compatibility: Apache Flink, Flink on Kubernetes, Confluent Cloud, AWS Managed Flink
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/event-streams-architect/flink-architect
  crusor-origin: original
  crusor-sources: "nightlies.apache.org/flink/flink-docs-stable/docs/concepts; nightlies.apache.org/flink/flink-docs-stable/docs/ops/state"
  crusor-triggers: "flink, event time, watermark, checkpointing, savepoint, stateful stream, windowing, backpressure, flink job"
  crusor-verified-on: "2026-10-30"
---

# Flink Architect

Flink is **state, time, and the recovery boundary**. Get state and watermarks right
and the rest is tuning; get them wrong and no amount of parallelism helps.

## When to use

- Continuous aggregation, joins, or pattern detection over streams.
- Exactly-once semantics into a sink matter.
- Event-time correctness with late data is required.

## When NOT to use

- Stateless filtering/routing — a simpler consumer is enough.
- Micro-batch latency is acceptable and the team already runs Spark.

## Decision 1 — Time semantics

- Event time (when it happened) for analytics; processing time only for
  infrastructure-level work.
- Watermarks declare "we believe we have seen everything up to T". Bounded
  out-of-orderness, not perfection.
- Idle partitions stall watermarks — configure idleness detection.
- Allowed lateness defines how long late events can still update a window; late
  events beyond it go to a side output, never silently dropped.

## Decision 2 — State

- Keyed state is partitioned by key: choose keys so state is balanced and bounded.
- State size drives checkpoint size and recovery time — monitor both.
- Use timers instead of polling; clear state on window close or TTL.
- Value/List/Map state deliberately; a large Map state becomes a compaction problem.
- RocksDB for large state, in-memory for small and fast.

## Decision 3 — Checkpoints and exactly-once

- Checkpoint interval balances overhead versus reprocessing on failure (typically
  30–120 s).
- Incremental checkpoints for RocksDB keep them cheap.
- Exactly-once end-to-end needs a transactional sink (Kafka transactions, Iceberg
  commits); otherwise you have at-least-once and must deduplicate.
- Checkpoints to durable object storage, not local disks.
- Savepoints before every upgrade; they are the only safe migration path for stateful
  jobs.

## Decision 4 — Recovery and upgrades

- Restore time = checkpoint size ÷ throughput; large state means a long outage window.
- Plan for state schema evolution: use Avro/Protobuf with schema ids, or write
  migration code.
- Savepoint-and-restore drill on a schedule, not only during upgrades.
- Job upgrades that change the topology may not restore from a savepoint — verify.

## Decision 5 — Operations

- Backpressure: check the UI's backpressure panel and the slowest operator first, not
  total throughput.
- Watermark lag is the leading indicator of trouble — alert on it in seconds.
- Restart strategy: fixed-delay or exponential, but a poison event loops forever —
  handle deserialisation errors explicitly.
- Autoscaling streaming jobs is painful; size for peak and use savepoint-based
  rescaling deliberately.

## Failure modes at scale

- Watermark stall from an idle partition; windows never fire.
- 400 GB of RocksDB state; recovery takes 40 minutes after every failure.
- Exactly-once claimed with a non-transactional sink; duplicate rows on retry.
- Deserialisation error restarts the job forever on the same record.
- Savepoint taken days before a schema change; restore fails during the upgrade.

## Verification receipts

1. Time semantics and watermark strategy documented.
2. Checkpoint interval, size, and measured recovery time.
3. Savepoint/restore drill executed on the real job.
4. Sink semantics verified with an injected duplicate.
5. Watermark-lag alert configured and tested.
