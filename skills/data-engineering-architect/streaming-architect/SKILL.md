---
name: streaming-architect
description: Architect-level streaming design — event schema and keys, delivery guarantees and what exactly-once really buys, watermarks and late data, state and checkpointing, replay from a log, and the operational cost of a always-on pipeline. Use when data must move and be processed continuously.
license: MIT
compatibility: Kafka, Kinesis, Pulsar, Flink, Spark Structured Streaming, Redpanda
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/streaming-architect
  crusor-origin: original
  crusor-sources: "kafka.apache.org/documentation; nightlies.apache.org/flink/flink-docs-stable; docs.aws.amazon.com/streaming"
  crusor-triggers: "streaming, kafka, kinesis, event stream, pub sub, real time, flink, exactly once, watermark, event driven pipeline, consumer group"
  crusor-verified-on: "2026-10-30"
---

# Streaming Architect

A stream is **an append-only log plus consumers that must be replayable**. Design
the log first; the processing framework is a detail you can replace.

## When to use

- Freshness in seconds or minutes drives a named action.
- Multiple consumers need the same event flow.
- An operational system must react as events happen.

## When NOT to use

- A five-minute batch satisfies the decision → `batch-pipeline-architect`.
- The payload is large blobs — stream a pointer, not the file.
- There is one consumer and no replay need: a queue is enough.

## Decision 1 — The log

- Partition key decides ordering and parallelism: choose it for the ordering you
  actually need (per user, per account), not for even spread alone.
- Retention is a design number: long enough to replay a bad deploy and rebuild
  state. "Seven days" is a default, not a decision.
- Topic per event type, versioned schema, no mixed payload shapes.
- Compaction for entity state topics (latest value per key); delete retention for
  event topics.

## Decision 2 — Delivery semantics

| Guarantee | Reality |
|---|---|
| at-most-once | may lose events, never duplicates |
| at-least-once | duplicates possible — consumers must be idempotent |
| exactly-once | transactional within the framework's boundary only |

- Choose at-least-once plus idempotent sinks for almost everything; it is simpler
  and survives retries.
- "Exactly once" ends at the system boundary: an external API call is not covered.
- Deduplicate on a stable event id, stored with the sink write.

## Decision 3 — Time

- **Event time** is when it happened; **processing time** is when you saw it.
  Aggregations must say which they use.
- Watermarks bound how long you wait for late data; the allowed lateness is a
  product decision with a cost.
- Late events either update a window (allowed lateness) or go to a side output —
  never silently dropped.
- Windows: tumbling for reporting, sliding for detection, session for behaviour;
  each has different state cost.

## Decision 4 — State and recovery

- Stateful operators checkpoint to durable storage at an interval that bounds
  reprocessing on failure.
- The state store size sets the recovery time; large state needs incremental
  checkpoints.
- Consumer group rebalances stop the world briefly — plan for them, and use
  cooperative rebalancing.
- Restore drill: kill an operator and measure time to catch up.

## Decision 5 — Replay and change

- A new consumer starts at earliest or latest — decide per consumer and record it.
- Rebuilding a derived table means replaying into a new sink, not mutating the
  live one.
- Schema evolution: additive optional fields are safe; removing or renaming needs
  a version and a migration path.
- Backpressure is real: monitor consumer lag, not just throughput.

## Decision 6 — Cost and operations

- Streaming bills by provisioned throughput or running time — an idle cluster is
  a line item.
- Alert on consumer lag (time-based, not message count), checkpoint failures, and
  partition skew.
- One hot partition ruins parallelism; check key distribution.
- Poison messages go to a DLQ with the payload and the error.

## Failure modes at scale

- Duplicate charges from a non-idempotent sink after a rebalance.
- Consumer lag measured in messages, hiding an hour of real delay.
- A single hot key serialising 40% of traffic.
- Watermark set so tight that every late event is discarded.
- State restored from a week-old checkpoint because nobody tested recovery time.

## Verification receipts

1. Topic inventory: key, retention, partitions, schema version.
2. Duplicate-injection test: replay 10% of events, downstream counts unchanged.
3. Lag dashboard in seconds, with an alert on the SLO.
4. Recovery drill: operator killed, catch-up time measured.
5. Late-event policy exercised with an out-of-order event.
