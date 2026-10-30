---
name: lambda-architect
description: Architect-level AWS Lambda design — invocation models and their failure semantics, memory/CPU tuning, cold start control, VPC and database connectivity, event source mapping behaviour, and the observability and concurrency controls that keep a function fleet predictable. Use when building AWS-native event-driven compute.
license: MIT
compatibility: AWS Lambda
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/compute-architect/lambda-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/lambda/latest/dg; docs.aws.amazon.com/lambda/latest/operatorguide; aws.amazon.com/blogs/compute"
  crusor-triggers: "lambda, function, event source mapping, cold start, provisioned concurrency, reserved concurrency, sqs trigger, api gateway lambda"
  crusor-verified-on: "2026-10-30"
---

# Lambda Architect

Lambda is **a runtime contract**: init once, invoke many, time out at fifteen
minutes. Nearly every production issue is an assumption about that contract.

## When to use

- Event-driven work: queues, streams, S3 events, schedules.
- Light HTTP APIs where elasticity matters more than p99.
- Glue code between managed services.

## When NOT to use

- Sustained high-throughput request/response → container service.
- Long-running or CPU-heavy processing → Batch/ECS.
- Anything needing persistent connections or in-memory state.

## Decision 1 — Invocation model

| Model | Retries | Use |
|---|---|---|
| synchronous (API GW, ALB) | caller's problem | user-facing |
| asynchronous (S3, SNS, EventBridge) | 2 automatic + DLQ | background |
| poll-based (SQS, Kinesis, DynamoDB) | until success/expiry | queues, streams |

- Every async invocation needs a DLQ or a destination; silent loss is the default
  without one.
- Stream sources process a shard in order: one poison record blocks the shard —
  configure max retries and an on-failure destination.
- SQS batch failures need partial batch responses, or one bad message retries the
  whole batch.

## Decision 2 — Sizing

- Memory sets CPU proportionally; tune by sweeping, not by guessing.
- Measure duration × memory cost per invocation, then choose the cheapest point
  that meets latency.
- Timeout set to p99 + margin, always below the caller's timeout.
- Larger functions initialise faster per MB but cost more when idle: sweep.

## Decision 3 — Cold starts

- Reduce init work: lazy clients, minimal dependencies, no SDK-wide imports.
- SnapStart (Java/.NET) or provisioned concurrency where p99 is contractual.
- Provisioned concurrency costs like a server; justify it with a latency SLO.
- Keep deployment packages small; container images only when the size demands it.

## Decision 4 — Connectivity

- VPC-attached functions need ENIs: attach only when the target requires it, and
  use a NAT/endpoint strategy that does not bottleneck.
- Never open a DB connection per invocation: use RDS Proxy, a pooler, or an HTTP
  data API.
- Idempotency: dedupe on event id in a store, because at-least-once is the
  default.

## Decision 5 — Concurrency and limits

- Account concurrency is shared: reserve concurrency for critical functions and
  cap noisy ones.
- Throttles are retried by the platform for async sources — a throttled function
  plus a long queue is a backlog, not an error.
- Watch `ConcurrentExecutions`, `Throttles`, `Errors`, `Duration` p99, and DLQ
  depth. Alarm on all five.

## Decision 6 — Structure

- One function per bounded responsibility; shared libraries as layers or bundled
  code — layers add coupling, prefer bundling unless size forces otherwise.
- Configuration via environment variables; secrets via Secrets Manager/SSM with
  caching.
- Infrastructure as code per function, with alarms and DLQ in the same template.

## Failure modes at scale

- Poison message looping the shard for hours, no on-failure destination.
- 1,000 concurrent invocations exhausting database connections.
- A function calling three other functions synchronously.
- Memory at 3 GB for a 200 ms handler because "it was faster".
- Timeout at 30 s but the API Gateway timeout at 29 s, so users see 504 while the
  function keeps billing.

## Verification receipts

1. Function inventory: trigger, timeout, memory, concurrency, DLQ.
2. Power-tuning sweep showing chosen memory and cost per million invocations.
3. Idempotency test: duplicate event delivered twice, one effect.
4. Concurrency limit test: throttle behaviour and queue draining observed.
5. Alarm set exercised with a forced error and a DLQ message.
