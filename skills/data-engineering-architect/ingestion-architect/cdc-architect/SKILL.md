---
name: cdc-architect
description: Architect-level change data capture — log-based versus query-based capture, Debezium-style connectors, schema history, tombstones and deletes, exactly-once into a sink, snapshot-then-stream bootstrap, and the operational failure modes that silently diverge replicas. Use when a replica must track an operational database.
license: MIT
compatibility: Debezium, Kafka Connect, Postgres logical replication, DynamoDB Streams
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/ingestion-architect/cdc-architect
  crusor-origin: original
  crusor-sources: "debezium.io/documentation; postgresql.org/docs/current/logical-replication.html; docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html"
  crusor-triggers: "cdc, change data capture, debezium, logical replication, wal, binlog, tombstones, snapshot, replica divergence"
  crusor-verified-on: "2026-10-30"
---

# CDC Architect

CDC is **a second copy of your database with a lag and its own failure modes**. The
architecture question is how divergence is detected before a human notices.

## When to use

- Analytics or search must track an OLTP database without querying it directly.
- Row-level changes matter (updates and deletes, not just inserts).
- Polling by `updated_at` cannot keep up or misses deletes.

## When NOT to use

- Small tables where a nightly full extract is trivial.
- The source has no changelog and no reliable ordering column.

## Decision 1 — Capture method

| Method | Trade-off |
|---|---|
| log-based (WAL/binlog) | complete, ordered, no query load; needs privileges and slots |
| query-based (timestamp/watermark) | simple; misses deletes and hard deletes between polls |
| trigger-based | complete; adds write load to the source |
| dual-write from app | no lag, but app now owns consistency — avoid |

- Log-based is the default for correctness; the operational cost is a replication
  slot you must monitor.
- Query-based is acceptable only for append-mostly, soft-delete data.

## Decision 2 — Bootstrap

```
consistent snapshot → stream from that snapshot's LSN/position → replay deltas
```

- Snapshot and stream must be bound to the same position, or rows inserted during the
  snapshot are lost or doubled.
- Incremental snapshots for large tables avoid a long lock window.
- Re-snapshotting a table means a coordinated swap, not a rebuild in place.

## Decision 3 — Events

- Event contains: before, after, op type, source position, timestamp, schema version.
- Deletes need tombstones or an explicit delete event — otherwise "missing" is
  ambiguous downstream.
- Keying by primary key lets downstream compact to current state.
- Ordering is per key, not global; a consumer that assumes global order is broken.

## Decision 4 — Sinks

- Idempotent upserts keyed by primary key and event position.
- Exactly-once is only within a transactional sink; otherwise design for duplicates.
- Schema changes propagate: a new source column must not break the sink. Additive
  safe, renames/drops need a versioned migration.
- DDL changes are a common outage: capture them and alert.

## Decision 5 — Operations

- Monitor: replication slot lag, connector lag (seconds not rows), error counts, and
  schema-history failures.
- A stalled connector holds WAL and can fill the source disk — the most dangerous
  failure in this design.
- Slot retention must be bounded and alerted; a dropped connector must release its
  slot.
- Reconcile periodically: row counts and checksums per table between source and sink.

## Failure modes at scale

- Connector down for a day; WAL fills the primary disk and takes down production.
- Deletes never captured; the replica grows forever with dead rows.
- Snapshot taken with concurrent writes and no position binding; silent duplicates.
- Schema rename propagated; downstream jobs fail with confusing null columns.
- Lag measured by offset, hiding a 40-minute real delay.

## Verification receipts

1. Capture method chosen with the correctness rationale.
2. Lag dashboard in seconds with an alert threshold.
3. Delete propagation test: row removed at source, removed downstream.
4. Reconciliation query comparing counts/checksums per table.
5. Slot retention and disk-growth alarm verified.
