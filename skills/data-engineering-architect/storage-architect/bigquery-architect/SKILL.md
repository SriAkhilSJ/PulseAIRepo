---
name: bigquery-architect
description: Architect-level BigQuery design — datasets and project layout, partitioning and clustering that actually prune, slots versus on-demand pricing, materialised views and BI Engine, streaming inserts versus the Storage Write API, and the query patterns that quietly scan terabytes. Use when the warehouse is BigQuery.
license: MIT
compatibility: Google BigQuery
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/storage-architect/bigquery-architect
  crusor-origin: original
  crusor-sources: "cloud.google.com/bigquery/docs/partitioned-tables; cloud.google.com/bigquery/docs/clustered-tables; cloud.google.com/bigquery/pricing"
  crusor-triggers: "bigquery, bq slots, partitioned table, clustering bigquery, on demand pricing, storage write api, bi engine, google warehouse"
  crusor-verified-on: "2026-10-30"
---

# BigQuery Architect

BigQuery charges **per byte scanned** on-demand, or per slot-hour with capacity.
Both models make table design the primary cost control.

## When to use

- The analytical store is BigQuery.
- Query costs are surprising or unpredictable.
- Choosing between on-demand and slot reservations.

## When NOT to use

- Cross-cloud analytical design → `warehouse-architect`.
- Transactional workloads — BigQuery is not an OLTP store.

## Decision 1 — Layout

```
organisation
  project per environment / business domain
    dataset per layer: raw_<source>, silver, gold_marts
      tables partitioned by date, clustered by high-selectivity column
```

- Datasets are the access-control and location boundary; choose region once
  (multi-region costs more, is not always needed).
- Separate billing projects for ad-hoc analysis so exploratory spend is visible.
- Table naming: `<layer>_<domain>_<entity>`; undocumented tables become landfill.

## Decision 2 — Physical design

| Technique | Effect |
|---|---|
| partition by DATE/TIMESTAMP column | prunes whole days |
| partition by ingestion time | useful only if you filter on it |
| clustering (up to 4 cols) | prunes within partitions |
| `require_partition_filter` | blocks accidental full scans |
| column types (no wide STRING blobs) | scans are columnar |

- Set `require_partition_filter = true` on large tables — the cheapest guardrail
  available.
- Clustering order matters: most selective first.
- Nested/repeated fields reduce joins but can hide scan cost; measure.

## Decision 3 — Pricing model

- On-demand: simple, per-TB scanned, good for spiky or small workloads.
- Slots (autoscaling reservations): better for predictable, high-volume BI.
- Break-even is roughly total scanned TB/day versus slot cost; compute it with real
  numbers rather than intuition.
- Reservations are per project/region; unused committed slots are still billed.

## Decision 4 — Serving patterns

- Materialised views for repeated aggregations; refresh cost is real.
- BI Engine for dashboard-heavy concurrency.
- Streaming inserts are for small volumes; Storage Write API for high throughput
  with exactly-once semantics.
- Scheduled queries for transforms; dbt or Dataform for managed pipelines.

## Decision 5 — Cost control

- `INFORMATION_SCHEMA.JOBS` by user, project, and bytes billed — review weekly.
- Guardrails: custom quotas, per-query byte limits, and partitioned table
  requirements.
- Kill patterns: `SELECT *` on wide tables, cross joins, unpartitioned
  self-joins, and dashboards scanning raw events.
- Cache hits are free; identical queries within 24 h reuse results — design
  dashboards to hit the cache.

## Failure modes at scale

- No partition filter required; one dashboard scans two years of events hourly.
- Clustering on a low-cardinality column; no pruning benefit.
- On-demand pricing with 200 dashboards refreshing every five minutes.
- Streaming inserts for event data at scale; quota limits and duplicate rows.
- Ad-hoc exploration billed to the production project, invisible in reports.

## Verification receipts

1. Dataset/project layout with locations and access roles.
2. Bytes-scanned report for the top 20 queries, with fixes identified.
3. Partition filter enforced on the largest tables, proven by a failed query.
4. Pricing model decision with the break-even calculation.
5. Cost alerting on daily scan volume per project.
