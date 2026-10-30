---
name: serverless-architect
description: Architect-level serverless guidance — function granularity and boundaries, cold start and concurrency reality, event-driven contracts with at-least-once delivery, connection and state limits, and the observability and cost behaviours of scale-to-zero systems. Use when designing Lambda/Cloud Run/Functions-style workloads.
license: MIT
compatibility: AWS Lambda, Cloud Run, Azure Functions, Cloudflare Workers
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/serverless-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/lambda; cloud.google.com/run/docs; developers.cloudflare.com/workers"
  crusor-triggers: "serverless, lambda, cloud run, functions, cold start, event driven, scale to zero"
  crusor-verified-on: "2026-10-30"
---

# Serverless Architect

Serverless trades **control for elasticity**. The architecture question is which
limitations you can live inside — because the platform will not negotiate.

## When to use

- Bursty or unpredictable traffic, event-driven processing, scheduled jobs.
- Small teams that do not want to operate clusters.
- Glue between managed services.

## When NOT to use

- Steady high-throughput services (cost per request exceeds a container).
- Long-running work (>15 min), heavy CPU, or persistent connections.
- Latency-critical paths where cold starts are visible.

## Decision 1 — Granularity

| Unit | Use |
|---|---|
| one function per route | small APIs, clear boundaries |
| one function for many routes | less cold start, worse isolation |
| one function per event type | queue/stream consumers |

- Functions are **deployment units, not design units**: keep domain logic in a
  shared package so it can be tested without invoking the platform.
- Avoid function-to-function synchronous calls — that is a distributed monolith
  with per-call latency and billing.

## Decision 2 — Cold starts and concurrency

- Minimise init work: no heavy SDK imports at module load, no eager DB
  connections.
- Provisioned concurrency or minimum instances only where latency is contractual
  — it costs like a server.
- Concurrency limits are per-region and shared: one runaway function can throttle
  the whole account.
- Reserved concurrency for critical functions; DLQ on async invocations.

## Decision 3 — State and connections

- Functions are stateless; nothing survives between invocations reliably.
- Database connections: use a pooler (RDS Proxy/PgBouncer/HTTP driver). One
  connection per invocation exhausts the database at scale.
- Cache in an external store, not in module scope — instances are recycled and
  parallel.
- Filesystem is ephemeral and small; large artefacts go to object storage.

## Decision 4 — Event contracts

- Assume **at-least-once** delivery: every consumer is idempotent, keyed by an
  event id.
- Ordering is not guaranteed unless the platform says so (FIFO queues/Kinesis
  shards).
- Poison messages go to a DLQ with an alarm; silent retries are worse than
  failures.
- Timeouts and visibility settings must exceed the function's real execution
  time.

## Decision 5 — Observability and cost

- Structured logs with a correlation id per event; traces across async hops.
- Cost drivers: invocations × duration × memory. Right-size memory (it also
  sets CPU) with a measured sweep.
- Alarms on error rate, throttles, DLQ depth, and duration approaching timeout.
- CloudWatch-style log ingestion is a hidden line item — set retention.

## Failure modes at scale

- Connection storms against RDS from a concurrency spike.
- Non-idempotent consumers double-charging on retry.
- A function calling another function synchronously through three hops.
- Memory set to 3 GB "to be safe" for a 200 ms job.
- No DLQ: failed events disappear into retry purgatory.

## Verification receipts

1. Function inventory: trigger, timeout, memory, concurrency, DLQ.
2. Load test at projected peak with cold starts measured.
3. Idempotency test: replay the same event twice → one effect.
4. Cost per 1M invocations at current duration/memory.
5. Alarm coverage for errors, throttles and DLQ depth.
