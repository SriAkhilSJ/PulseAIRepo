---
name: kafka-architect
description: Architect-level Kafka design — topic and partition strategy, key choice and ordering guarantees, replication and min-ISR, retention and compaction, consumer groups and rebalancing, and the lag and disk failures that take a cluster down. Use when Kafka (or MSK/Confluent) carries event data.
license: MIT
compatibility: Apache Kafka, MSK, Confluent Cloud, Redpanda
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/event-streams-architect/kafka-architect
  crusor-origin: original
  crusor-sources: "kafka.apache.org/documentation; docs.confluent.io/platform/current; docs.aws.amazon.com/msk"
  crusor-triggers: "kafka, topic, partition, consumer group, offset, isr, retention, compaction, broker, msk, rebalance"
  crusor-verified-on: "2026-10-30"
---

# Kafka Architect

Kafka is **an ordered log per partition**. Every design decision follows from the
key: it decides ordering, parallelism, and hot spots simultaneously.

## When to use

- Event streams with multiple consumers and replay.
- Durable buffering between producers and consumers.
- Event sourcing or log-based integration.

## When NOT to use

- Simple task queues (SQS-style semantics are simpler).
- Low volume where an HTTP call or a table would do.

## Decision 1 — Topics and partitions

- One topic per event type with a stable schema; not one topic for everything.
- Partitions = target throughput ÷ per-partition throughput; more partitions mean more
  parallelism but slower rebalances and more files.
- Ordering is guaranteed **within a partition only** — if you need per-entity order,
  key by entity.
- Partition count is easy to increase and hard to decrease; start conservative and
  leave headroom.

## Decision 2 — Keys

| Key | Consequence |
|---|---|
| entity id | per-entity order, uneven partitions if skewed |
| none (round-robin) | even spread, no ordering |
| tenant id | isolation and order per tenant, hot tenants |
| composite (tenant+id) | spread with intra-entity order |

- A skewed key creates a hot partition: one broker saturates while others idle.
  Check key distribution against real data before launch.

## Decision 3 — Durability

- Replication factor 3, `min.insync.replicas=2`, `acks=all` for anything that must
  not be lost.
- `unclean.leader.election=false` — availability is not worth silent data loss.
- Producer idempotence on; transactions only when consuming and producing atomically.
- Retention by time and size; compacted topics for entity state (latest per key).

## Decision 4 — Consumers

- One consumer group per application; partitioning of work across members is
  automatic.
- Rebalances stop consumption — use cooperative/sticky assignment and static
  membership for long-running consumers.
- Commit offsets after processing, not before; at-least-once is the honest default.
- Lag in **time**, not messages: offset lag hides a slow consumer.

## Decision 5 — Operations

- Monitor: under-replicated partitions, offline partitions, ISR shrinks, disk usage,
  controller changes, consumer lag.
- Disk is the classic outage: retention × throughput must fit with headroom; alert at
  70%.
- Broker upgrades and rolling restarts need a plan for the partition movement they
  trigger.
- Schema registry with backward-compatible evolution (`event-schema-architect`).

## Failure modes at scale

- Key by a low-cardinality field; one partition takes 60% of traffic.
- Retention set to 7 days on a topic with a 10-day backlog after an incident.
- Consumer commits before processing; an outage loses a batch.
- Partition count increased during peak; rebalance storm for an hour.
- Disk full on one broker because replicas are unevenly distributed.

## Verification receipts

1. Topic inventory: partitions, replication, retention, cleanup policy.
2. Key-distribution analysis on real data.
3. Failure test: broker killed, production continues, no data loss.
4. Lag dashboard in seconds with alerting.
5. Disk capacity model with growth projection and alert thresholds.
