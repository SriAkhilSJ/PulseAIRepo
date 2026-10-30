---
name: messaging-architect
description: Architect-level messaging design in the cloud — queue versus topic versus stream, ordering and deduplication, visibility timeouts and dead-letter queues, fan-out patterns, schema governance, and the backlog and poison-message behaviour that decides whether a system degrades or collapses. Use when services must communicate through queues or events instead of direct calls.
license: MIT
compatibility: SQS/SNS/EventBridge, Pub/Sub, Service Bus, Kafka/MSK
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/data-services-architect/messaging-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide; cloud.google.com/pubsub/docs; learn.microsoft.com/azure/service-bus-messaging"
  crusor-triggers: "sqs, sns, eventbridge, pubsub, service bus, message queue, dead letter queue, fan out, async messaging, visibility timeout"
  crusor-verified-on: "2026-10-30"
---

# Messaging Architect

Messaging buys **decoupling at the price of eventual consistency**. The design work
is delivery semantics, ordering, and what happens when consumption falls behind.

## When to use

- A producer must not wait for, or fail with, a consumer.
- Work must be buffered, retried, or fanned out.
- Multiple consumers need the same event.

## When NOT to use

- The caller needs the result now (use a synchronous API).
- A single consumer with no retry need (a database job may be enough).
- Continuous high-volume ordered processing → `streaming-architect`.

## Decision 1 — Primitive

| Primitive | Semantics | Use |
|---|---|---|
| queue | one consumer per message, competing consumers | work distribution |
| topic | fan-out to many subscribers | notifications, events |
| event bus + rules | filtered routing, many producers | domain events |
| stream | ordered log, replay, multiple consumers | event sourcing, CDC |

- Queue for "do this once"; topic for "tell everyone"; stream when replay matters.
- Do not put a 2 MB payload in a message — store the blob, send the pointer.

## Decision 2 — Delivery

- Assume **at-least-once**; every consumer is idempotent on a message id.
- FIFO queues only where per-key ordering is required: throughput is lower and the
  constraint is real.
- Visibility timeout must exceed the consumer's real processing time, or the
  message reappears while being handled.
- Duplicate detection windows are bounded; long retries can re-deliver.

## Decision 3 — Failure handling

- Dead-letter queue on every consumer, with an alarm on depth and an owner.
- Max receive count tuned to the cost of retrying vs the cost of failing.
- Poison message handling: inspect, quarantine, and continue — never block the
  queue forever.
- Consumer errors are classified: transient (retry), permanent (DLQ), unknown
  (retry once, then DLQ).

## Decision 4 — Fan-out and choreography

- Fan-out with independent subscriptions; one slow consumer must not stall others.
- Choreography (events) over orchestration (central controller) when steps are
  genuinely independent; use a saga with compensating actions for multi-step
  transactions.
- Events describe **what happened** in past tense, with a stable schema; commands
  describe what should happen and have one owner.
- Versioned event schemas; additive-only changes within a major version.

## Decision 5 — Backlog behaviour

- Monitor **age of the oldest message**, not just depth — depth is misleading with
  variable rates.
- Autoscale consumers on backlog age; a fixed consumer count turns a spike into an
  outage.
- Backpressure to the producer when the queue cannot drain (rate limit, queue
  caps).
- Ordering plus retries means head-of-line blocking: isolate poison-prone message
  types into their own queue.

## Decision 6 — Operations

- Retention is a policy: how long can an undelivered message live before it is
  lost?
- Encryption in transit and at rest; no PII in message bodies without a reason.
- Replay tooling for stream-based systems; for queues, a re-drive mechanism.
- Cost: request-based pricing punishes polling; long polling and batching reduce
  both cost and latency.

## Failure modes at scale

- Visibility timeout shorter than processing; every message processed twice.
- One poison message retried 1,000 times, blocking the whole queue.
- DLQ with 40k messages discovered during an unrelated incident.
- Topic with 12 subscriptions, three of them broken and silently dropping.
- Replay impossible because messages expired after four days.

## Verification receipts

1. Primitive choice per flow with delivery and ordering requirements.
2. Idempotency test: duplicate delivery produces one effect.
3. DLQ alarm exercised with a deliberately failing consumer.
4. Backlog-age dashboard with autoscaling on oldest-message age.
5. Schema version and compatibility policy documented.
