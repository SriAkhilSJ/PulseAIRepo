---
name: dagster-architect
description: Architect-level Dagster design — software-defined assets over tasks, partitions and backfills, resources and IO managers, schedules and sensors, and the asset checks that make data quality part of orchestration. Use when orchestration should be modelled as data products.
license: MIT
compatibility: Dagster, Dagster+
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/scheduling-architect/dagster-architect
  crusor-origin: original
  crusor-sources: "docs.dagster.io/concepts/assets/software-defined-assets; docs.dagster.io/guides/partitions; docs.dagster.io/concepts/assets/asset-checks"
  crusor-triggers: "dagster, software defined asset, asset check, io manager, partitions dagster, sensors, dagster cloud, asset graph"
  crusor-verified-on: "2026-10-30"
---

# Dagster Architect

Dagster models **data assets, not tasks**. The orchestration question becomes "is
this table fresh and correct", which is the question you actually have.

## When to use

- The team thinks in tables/datasets rather than jobs.
- Quality checks should gate materialisation.
- Multiple environments and teams share a lineage.

## When NOT to use

- A handful of cron jobs with no dependencies — Dagster is overhead.
- An existing Airflow estate with no pain — migration is expensive.

## Decision 1 — Assets

- Define an asset per materialised table/partition; its dependencies are the
  upstream assets, not task ordering.
- Asset keys are stable identifiers; renaming is a migration for downstream
  consumers.
- Group by domain; keep the graph readable rather than clever.
- Ops for side effects (email, trigger) — do not disguise them as assets.

## Decision 2 — Partitions

- Partition by day/hour/region/dynamic key per asset; backfills become a first-class
  operation.
- Partition mappings connect differently partitioned assets — the usual place for
  correctness bugs.
- Backfill in bounded chunks with concurrency limits; a 2-year backfill is not one
  run.
- Partitioned assets need idempotent materialisation (overwrite per partition).

## Decision 3 — Resources and IO

- Resources carry connections/config (warehouse, S3, dbt) and are injected, not
  imported globally.
- IO managers decide where outputs live: warehouse tables, files, or nothing
  (in-place writes).
- Environment-specific config in YAML per deployment; no code branches for envs.
- Secrets from the platform's secret manager, never in `dagster.yaml`.

## Decision 4 — Scheduling

- Schedules for predictable cadence; sensors for event-driven (new file, upstream
  freshness, external API).
- Freshness policies declare the expected update cadence; violations surface as
  alerts, not silent staleness.
- Auto-materialisation policies for incremental chains — but verify they do not
  thrash.

## Decision 5 — Checks

- Asset checks: row-count bands, null rates, uniqueness, freshness, business rules.
- Severity: error blocks downstream, warn records; do not make every check fatal.
- Checks run with the asset and appear in the UI next to lineage — that is the whole
  value.
- Alert routing per asset group to the owning team.

## Failure modes at scale

- Task-shaped DAGs ported wholesale to Dagster; assets are just renames.
- Partition mapping wrong; a daily asset feeds an hourly one with stale data.
- Unbounded backfill saturates the warehouse during business hours.
- Checks defined but not wired to block downstream; bad data flows through.
- Resources configured per deployment by hand; staging points at production.

## Verification receipts

1. Asset graph for one domain, with grouping and owners.
2. Backfill executed in bounded chunks with concurrency limits.
3. Partition mapping verified between two differently partitioned assets.
4. One asset check failing and blocking downstream, observed.
5. Freshness policy configured with an alert on violation.
