---
name: airflow-architect
description: Architect-level Airflow design — DAG patterns that scale, idempotent tasks, executors and worker sizing, XCom boundaries, pools and priorities, backfill mechanics, and the scheduler and metadata-database health that decides whether anything runs on time. Use when orchestration is Airflow.
license: MIT
compatibility: Airflow 2/3, MWAA, Cloud Composer, Astronomer
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/scheduling-architect/airflow-architect
  crusor-origin: original
  crusor-sources: "airflow.apache.org/docs/apache-airflow/stable/best-practices.html; airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment; astronomer.io/blog"
  crusor-triggers: "airflow, dag, scheduler, kubernetes executor, xcom, pools, backfill, mwaa, composer, airflow task"
  crusor-verified-on: "2026-10-30"
---

# Airflow Architect

Airflow schedules **DAGs, not data**. Every problem it causes traces back to that:
tasks that are not idempotent, DAGs that mean "everything", or a scheduler that
became the bottleneck.

## When to use

- Multiple heterogeneous jobs with dependencies.
- Existing Airflow estate needs structure or performance work.
- Bridging systems that lack their own scheduler.

## When NOT to use

- Pure dbt/SQL lineage — a dbt-native scheduler may be simpler.
- Event-driven flows where a stream already orders the work.

## Decision 1 — DAG shape

- One DAG per domain/pipeline, not one per team or per table.
- Task granularity: retriable, bounded, and meaningful — not one task per file.
- Prefer `TaskFlow`/decorators for Python tasks; keep callables importable and
  testable.
- Dynamic task mapping for fan-out over a list computed at runtime, not Python loops
  generating 500 static tasks.

## Decision 2 — Idempotency

- Every task can run twice safely: partition overwrite, merge by key, or a
  `delete-then-insert` scope.
- Pass references (paths, partitions, table names) between tasks via XCom — not
  datasets.
- No hidden state in a mutable table that tasks read-modify-write.
- Retries are configured per task with a rationale; blind retries mask logic errors.

## Decision 3 — Execution

| Executor | Fit |
|---|---|
| Local | dev only |
| Celery | many small tasks, existing workers |
| Kubernetes | isolation per task, heavy or heterogeneous work |
| CeleryKubernetes | mixed workloads |

- Worker sizing: concurrency per worker × workers ≤ what the target can accept.
  Airflow will happily launch 200 database connections.
- Pools to cap concurrency per external system (warehouse, API, SFTP endpoint).
- Task timeouts and `execution_timeout` on everything; a hung task blocks a slot
  forever otherwise.

## Decision 4 — Scheduler health

- Metadata database size and query latency decide throughput; clean old task
  instances and logs.
- One scheduler is fine for most estates; two for HA with a shared DB.
- DAG parse time matters: heavy top-level code runs on every parse. Keep imports
  lazy.
- File processing interval and DAG count interact — thousands of DAGs need tuning.

## Decision 5 — Backfills and SLAs

- Backfill with `--start-date/--end-date`, against an idempotent DAG, in an isolated
  pool.
- Never backfill by clearing tasks in bulk without understanding downstream readers.
- SLAs alert when a task passes a deadline; they do not stop anything.
- Catchup is a decision per DAG: enable only where historical runs are meaningful.

## Failure modes at scale

- 3,000 DAGs parsed every 30 seconds; scheduler CPU pegged, runs delayed.
- XCom carrying a 5 MB DataFrame per task; metadata DB explodes.
- No pools; a backfill of 500 tasks saturates the warehouse and blocks production.
- Catchup accidentally on; a new DAG triggers two years of runs.
- Tasks without timeouts; one hung task holds the only slot for a pool.

## Verification receipts

1. DAG inventory with owner, schedule, pool, and SLA.
2. Idempotency test: rerun the same interval, no duplicates.
3. Pool configuration protecting the warehouse during a backfill.
4. Scheduler metrics: parse time, dag count, queue latency.
5. Metadata DB maintenance job and retention configured.
