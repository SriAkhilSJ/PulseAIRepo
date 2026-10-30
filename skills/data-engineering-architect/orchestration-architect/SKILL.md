---
name: orchestration-architect
description: Architect-level pipeline orchestration — DAG design and asset dependencies, idempotent task contracts, scheduling and concurrency control, SLA and timeout policy, retries that do not hide failures, and the recovery path when a run breaks at 02:00. Use when multiple jobs must run in order, on time, and recoverably.
license: MIT
compatibility: Airflow, Dagster, Prefect, Argo Workflows, dbt Cloud, Step Functions
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/orchestration-architect
  crusor-origin: original
  crusor-sources: "airflow.apache.org/docs; docs.dagster.io; docs.prefect.io; argo-workflows.readthedocs.io"
  crusor-triggers: "airflow, dagster, prefect, orchestration, dag, scheduler, cron, workflow, sla, retry, backfill job"
  crusor-verified-on: "2026-10-30"
---

# Orchestration Architect

An orchestrator's only real job is **to know what is done, what is running, and
what must happen next** — including after a failure nobody was awake for.

## When to use

- Several jobs with real dependencies and SLAs.
- Scheduled work that must be recoverable and observable.
- Choosing between a workflow tool, cron, and an event trigger.

## When NOT to use

- A single job with no dependencies — cron plus a log is fine.
- Event-driven processing where the log already carries ordering →
  `streaming-architect`.

## Decision 1 — Model

| Style | Use when |
|---|---|
| task DAG (Airflow) | imperative jobs with explicit steps |
| asset/declarative (Dagster) | data products, lineage-first thinking |
| one big job with internal steps | simplest; you lose granular retry |
| cron + script | no dependencies, low stakes |

- Model **data assets**, not just tasks, wherever the tool supports it: "table X
  is stale" is the question, not "task 4 failed".
- One DAG per domain, not one mega-DAG; blast radius grows with graph size.

## Decision 2 — Task contracts

- Each task: idempotent, bounded runtime, explicit inputs and outputs, and a
  timeout.
- Pass references (paths, partitions, table names) between tasks, not big
  payloads through the scheduler's metadata database.
- No hidden shared state through a mutable table — that is how tasks become
  order-dependent.
- Configuration from the orchestrator, secrets from the secret manager, never
  from the DAG file.

## Decision 3 — Schedule and concurrency

- Align to real data arrival: a 00:00 run against a source that lands at 03:00 is
  a guaranteed empty load.
- Sensor/asset-based triggering beats fixed times when upstream is unpredictable;
  sensors need timeouts and poke intervals that do not hammer the source.
- Cap concurrent runs per DAG and per pool: a backfill must not starve production.
- Stagger schedules that hit the same warehouse — a midnight stampede is a design
  smell.

## Decision 4 — Retries and failure

- Retry only transient failures; a logic error retried five times just costs five
  times as much and delays the alert.
- Exponential backoff with a cap; alert on the final failure, not each attempt.
- Every DAG has an owner, an SLA, and an alert route with a named human.
- Fail fast on contract violations; checkpoint long jobs so retries resume rather
  than restart.

## Decision 5 — Recovery

- Runbook per critical DAG: how to identify the failed step, how to re-run a
  window, how to clear a partial write.
- Partial writes are cleaned by the next run because writes are partition-replace,
  not append.
- SLA misses alert before consumers notice — alert on "will miss", not "missed".
- Keep run history long enough to answer "what changed last Tuesday".

## Failure modes at scale

- 400-task DAG where one failure blocks everything, retried blindly.
- Sensors polling every 30 seconds against a production database.
- SLA alerts that fire at 09:00 for a 06:00 deadline.
- Backfill and production sharing one pool; production loses.
- Scheduler metadata database full of XCom payloads.

## Verification receipts

1. DAG inventory with owner, schedule, SLA, and alert route.
2. Idempotency test: run the same interval twice, output unchanged.
3. Concurrency/pool limits shown protecting production during a backfill.
4. Timeout and retry policy demonstrated on an injected failure.
5. Runbook executed in a game day: failure detected and recovered in a measured time.
