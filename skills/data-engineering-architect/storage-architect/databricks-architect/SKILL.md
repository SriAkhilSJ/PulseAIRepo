---
name: databricks-architect
description: Architect-level Databricks design — workspace and catalog layout, cluster policies and autoscaling, jobs versus all-purpose compute, Delta Live Tables and medallion pipelines, Unity Catalog governance, and the DBU cost model that punishing always-on clusters. Use when the platform is Databricks.
license: MIT
compatibility: Databricks, Delta Lake, Unity Catalog
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/storage-architect/databricks-architect
  crusor-origin: original
  crusor-sources: "docs.databricks.com/en/clusters/cluster-config-best-practices; docs.databricks.com/en/delta-live-tables; docs.databricks.com/en/data-governance/unity-catalog"
  crusor-triggers: "databricks, dbu, unity catalog, delta live tables, medallion, cluster policy, all purpose cluster, databricks cost"
  crusor-verified-on: "2026-10-30"
---

# Databricks Architect

Databricks bills **DBUs by cluster type and uptime**. The architecture question is
always "which workload runs on which kind of cluster, for how long".

## When to use

- The lakehouse platform is Databricks.
- Cost per job or per team is unclear.
- Designing bronze/silver/gold pipelines on Delta.

## When NOT to use

- A plain warehouse handles the workload — DLUs and clusters are unnecessary.
- Strict on-prem or another cloud constraint.

## Decision 1 — Compute topology

| Workload | Compute |
|---|---|
| scheduled ETL | job clusters, autoscaling, terminated after run |
| interactive analysis | shared or per-team all-purpose clusters, auto-stop |
| streaming | dedicated long-running cluster with autoscaling |
| SQL dashboards | SQL warehouse, sized to concurrency |
| ML training | job cluster with GPU pool, spot where possible |

- All-purpose clusters are the top cost leak: set auto-stop to 10–20 minutes and
  enforce it with cluster policies.
- Job clusters cost less per DBU and are isolated per run — the default for
  pipelines.

## Decision 2 — Policies and sizing

- Cluster policies restrict node types, max workers, and autostop; teams self-serve
  inside the guardrails.
- Photon and newer runtimes usually pay for themselves on SQL-heavy work — measure.
- Autoscaling with a sensible min (0 for job clusters) and a cap that prevents one
  job from taking the workspace quota.
- Spot instances for fault-tolerant batch; keep driver on-demand.

## Decision 3 — Data layout

- Unity Catalog: catalog per environment, schema per domain, tables managed.
- Medallion layers: bronze (raw, append-only), silver (conformed, deduped), gold
  (aggregated for consumption).
- Liquid clustering or partitioning chosen by filter patterns; Z-order only where it
  measurably helps.
- Optimise writes: `optimizeWrite` and auto-compaction for small files.

## Decision 4 — Pipelines

- Delta Live Tables / Lakeflow for declarative pipelines with expectations
  (quality checks) built in.
- Streaming tables for incremental ingestion; materialised views for aggregates.
- Expectations: warn versus drop versus fail — choose per rule, not globally.
- Orchestration with jobs and dependencies, not a cron-in-a-notebook.

## Decision 5 — Governance

- Unity Catalog for tables, volumes, and ML models; grants at schema level.
- Row filters and column masks at the table; do not fork tables per audience.
- Lineage is captured automatically — use it for impact analysis before schema
  changes.
- Audit logs shipped to a central account.

## Decision 6 — Cost

- DBU per team/workload from system tables; review weekly.
- Top offenders: idle all-purpose clusters, full-refresh jobs, oversized SQL
  warehouses, and notebooks left running.
- Serverless SQL for spiky BI; classic warehouses for steady concurrency.
- Chargeback by workspace/team tags; a cost nobody sees is a cost nobody reduces.

## Failure modes at scale

- Twelve all-purpose clusters, none auto-stopping, one per analyst habit.
- Medallion names applied to tables that are actually raw + duplicate of raw.
- Z-order on a table written every five minutes; write amplification.
- Expectations set to fail on a noisy rule; the pipeline stops for a known issue.
- One warehouse sized XL for two users, sized for the loudest complaint.

## Verification receipts

1. Compute inventory: type, policy, autostop, DBUs/day.
2. Job versus all-purpose split with the cost delta.
3. Table layout report: partitions/clustering versus query filters.
4. Expectation set with severity per rule and a failure drill.
5. Cost report by team from system tables.
