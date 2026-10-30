---
name: warehouse-architect
description: Architect-level analytical storage design — warehouse versus lake versus lakehouse, dimensional and wide-table modelling, grain and keys, partitioning and clustering, medallion layering, and the governance that keeps a warehouse from becoming a swamp. Use when designing where analytical data lives and how it is modelled.
license: MIT
compatibility: Snowflake, BigQuery, Redshift, Databricks, Iceberg/Delta, DuckDB
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/storage-architect/warehouse-architect
  crusor-origin: original
  crusor-sources: "docs.snowflake.com; cloud.google.com/bigquery/docs; iceberg.apache.org; databricks.com/discover/lakehouse"
  crusor-triggers: "data warehouse, data lake, lakehouse, star schema, dimensional model, snowflake, bigquery, iceberg, partitioning, medallion, analytical model"
  crusor-verified-on: "2026-10-30"
---

# Warehouse Architect

Analytical storage is **a product with consumers**, not a bucket. The design
questions are grain, ownership, and what a query costs.

## When to use

- Choosing warehouse/lake/lakehouse for analytics, BI, or ML features.
- A warehouse is slow, expensive, or full of near-duplicate tables.
- Defining layers (raw/silver/gold) and modelling conventions.

## When NOT to use

- OLTP schema design for an application → `website-architect/database-*`.
- A single team's one-off analysis — a notebook and a temporary table.

## Decision 1 — Warehouse, lake, or lakehouse

| Need | Choice |
|---|---|
| SQL BI, governed, moderate volume | warehouse |
| cheap bulk storage, many formats, ML | lake with table format |
| BI and ML on the same data | lakehouse (Iceberg/Delta) |
| local analysis, <100 GB | DuckDB or a warehouse free tier |

- Storage and compute separation is now table stakes; choose on ecosystem and
  governance, not on the brochure.
- Open table formats buy you exit rights — worth real money at scale.

## Decision 2 — Layers

```
raw/bronze   append-only, source-shaped, immutable
silver       cleaned, typed, deduplicated, conformed keys
gold         modelled, metric-ready, one row per grain
```

- Silver is where business keys are conformed — the highest-leverage layer and the
  one teams skip.
- Gold tables have a declared grain and an owner. If nobody owns it, it dies
  slowly and expensively.
- Do not let consumers read raw. That is how two teams compute two truths.

## Decision 3 — Modelling

- **Dimensional (star)** — facts at a declared grain, conformed dimensions;
  best for BI and stable metrics.
- **Wide/OBT** — one big denormalised table per mart; fast to build, cheap to
  query, expensive to change.
- **Data Vault** — auditable hubs/links/satellites; heavy, justified by regulation
  and many sources.
- State the grain in the table name or docs (`fact_order_line`, not `orders_data`).

## Decision 4 — Physical layout

- Partition on the dominant filter (usually date); cluster/sort on the next most
  selective.
- Small partitions create overhead; huge partitions defeat pruning.
- Pre-aggregate where BI re-computes the same rollup thousands of times.
- Materialised views/streams for recurring transforms; watch refresh cost.
- Sort and compact small files — the most common silent cost in lakehouses.

## Decision 5 — Governance

- Schemas per domain, not per person; naming conventions enforced by CI.
- PII tagged at the column level; masking policies follow the tag.
- Retention per table, automated, not remembered.
- Cost attribution by warehouse/role + query tags, reviewed monthly.
- Deprecation is a process: mark, announce, freeze, drop.

## Failure modes at scale

- Three tables named `users`, `users_v2`, `users_final`, all queried.
- Gold tables with no grain: joins that fan out silently and inflate revenue.
- Partitioning by ingestion date while everyone filters on event date.
- Storage cost grows from copies of copies, each labelled a "backup".
- Nobody knows which dashboard depends on which table, so nothing is removable.

## Verification receipts

1. Layer diagram with owners and allowed readers per layer.
2. Grain documented for every gold table; fan-out test on a join.
3. Query plan showing partition pruning on a typical BI query.
4. Cost report by warehouse/role for the last month.
5. Deprecation list with consumers mapped and dates agreed.
