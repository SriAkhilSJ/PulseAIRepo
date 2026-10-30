---
name: snowflake-architect
description: Architect-level Snowflake design — virtual warehouse sizing and auto-suspend, storage versus compute separation, micro-partitioning and clustering, time travel and fail-safe, secure data sharing with consumers, and the cost model that punishes idle warehouses. Use when the warehouse is Snowflake.
license: MIT
compatibility: Snowflake
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/storage-architect/snowflake-architect
  crusor-origin: original
  crusor-sources: "docs.snowflake.com/en/user-guide/warehouses-overview; docs.snowflake.com/en/user-guide/tables-clustering-micropartitions; docs.snowflake.com/en/user-guide/data-sharing-intro"
  crusor-triggers: "snowflake, virtual warehouse, micro partition, clustering key, time travel, data sharing, snowflake cost, warehouse size"
  crusor-verified-on: "2026-10-30"
---

# Snowflake Architect

Snowflake bills **compute by the second and storage by the byte**. Most designs
fail on warehouse sizing and idle credits, not on SQL.

## When to use

- The analytical platform is Snowflake.
- Warehouse cost or query latency needs a structural fix.
- Sharing data with external consumers.

## When NOT to use

- Another warehouse is already in place — this is not a migration argument.
- OLTP workload — Snowflake is not that.

## Decision 1 — Warehouses

| Workload | Design |
|---|---|
| BI dashboards | XS/S with auto-suspend 60 s, one per team |
| ELT transforms | M/L, scheduled, separate from BI |
| ad-hoc analysts | S with a query timeout |
| heavy ML feature builds | dedicated XL, off hours |

- Separate warehouses per workload class: contention becomes a queue, and cost is
  attributable.
- Auto-suspend 60 s and auto-resume; an always-on warehouse is a subscription you
  did not intend.
- Multi-cluster warehouses for concurrency spikes, not for faster single queries.

## Decision 2 — Storage and clustering

- Micro-partitions make most filters fast without indexes; do not port an
  index-heavy schema.
- Clustering keys only on very large tables with a stable, selective filter —
  they cost credits on write.
- `cluster by` the column your queries filter on; verify with the clustering depth
  and pruning stats in the query profile.
- Time travel (1–90 days) and fail-safe (7 days) are storage costs; set retention
  per table deliberately.

## Decision 3 — Transformation placement

- ELT into Snowflake, transform with dbt/SQL (`dbt-architect`) rather than
  external compute where the data volume is moderate.
- Dynamic tables / streams + tasks for incremental, instead of full rebuilds.
- Avoid `SELECT *` in models that feed dashboards — column pruning is a cost lever.
- Materialise what is read repeatedly; views over large joins are a credit sink.

## Decision 4 — Cost

- Credits per warehouse per day is the primary metric; alert on anomalies, not
  totals.
- Worst offenders: idle warehouses, full-refresh jobs, unpartitioned scans, and
  BI tools issuing queries per dashboard tile.
- Resource monitors with hard suspension for non-production accounts.
- `ACCOUNT_USAGE` views are the truth; build the report before the first bill
  review.

## Decision 5 — Sharing and governance

- Secure data sharing for consumers — no data copies, revocable, audited.
- Roles: functional roles for access, access roles for objects, one role per
  consumer class.
- Column-level masking and row access policies for PII, applied at the table.
- Object tagging for cost and classification; retention policies keyed off tags.

## Failure modes at scale

- Every dashboard has its own XL warehouse; concurrency is fine, the bill is not.
- Clustering key added to a table written constantly; write credits triple.
- Time travel at 90 days on 200 TB "in case someone asks".
- BI tool querying raw tables; every refresh scans the full history.
- Warehouse never suspends because a health-check query runs every 30 seconds.

## Verification receipts

1. Warehouse inventory: size, workload, auto-suspend, credits/day.
2. Query profile showing partition pruning for a representative query.
3. Storage report by table, with time-travel and fail-safe broken out.
4. Resource monitors configured for non-production.
5. Sharing setup tested with a consumer account and a revocation.
