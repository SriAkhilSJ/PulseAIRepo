---
name: data-engineering-architect
description: Entry point for data platform architecture — source-to-consumer topology, batch versus streaming, lake versus warehouse versus lakehouse, where ownership and contracts sit, and the freshness/cost/quality envelope every pipeline must declare. Use when planning a data platform, a warehouse, an ETL/ELT estate, or a streaming pipeline.
license: MIT
compatibility: dbt, Airflow, Dagster, Spark, Flink, Snowflake, BigQuery, Iceberg
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect
  crusor-origin: original
  crusor-sources: "docs.getdbt.com; iceberg.apache.org; flink.apache.org/docs; databricks.com/glossary/data-lakehouse"
  crusor-triggers: "data pipeline, etl, elt, data warehouse, data lake, lakehouse, streaming, ingestion, analytics, data platform, data model"
  crusor-verified-on: "2026-10-30"
---

# Data Engineering Architect

Data systems fail differently from request/response systems: **nobody gets a 500
when a number is wrong**. The architecture's job is to make correctness, freshness
and lineage visible before a dashboard lies to an executive.

## The shelf

Seven shelves, 28 books.

| Shelf | Books |
|---|---|
| `ingestion-architect/` | `batch-pipeline` · `cdc` · `api-ingestion` · `file-ingestion` |
| `event-streams-architect/` | `streaming` · `kafka` · `flink` · `event-schema` |
| `storage-architect/` | `warehouse` · `snowflake` · `bigquery` · `databricks` · `iceberg` · `spark` · `duckdb` |
| `transform-architect/` | `analytics-engineering` · `dbt` · `semantic-layer` · `sql-modelling` |
| `scheduling-architect/` | `orchestration` · `airflow` · `dagster` |
| `quality-architect/` | `data-quality` · `lineage` · `governance` · `data-observability` |
| `delivery-architect/` | `reverse-etl` · `data-api` |

Read the crown, then the one or two books the plan actually needs.

## When to use

- Planning ingestion from operational systems to analytics.
- Choosing batch versus streaming, or a warehouse versus a lake.
- A dashboard, ML feature, or report is disputed or slow.

## When NOT to use

- The question is OLTP schema design → `website-architect/database-*`.
- It is one ad-hoc query — write the query.
- The real problem is that nobody defined the metric → fix definition first.

## Decision 1 — Map the flow

```
sources → ingestion → raw/bronze → cleaned/silver → modelled/gold → consumers
```

- Every hop has an **owner, a contract, and a freshness target**.
- Raw is immutable and replayable; everything downstream is derivable from it.
  If raw cannot be replayed, you cannot fix a bug — you can only apologise.
- Land raw as close to source as possible, with load timestamp and source id.
- Consumers are named: dashboards, ML features, reverse-ETL, APIs. Unnamed
  consumers are how gold tables grow for nobody.

## Decision 2 — Batch or streaming

| Signal | Batch |
|---|---|
| freshness measured in hours | yes |
| complex joins across many sources | yes |
| cost-sensitive, large volumes | yes |
| freshness in seconds/minutes | streaming |

| Signal | Streaming |
|---|---|
| operational reaction to events | yes |
| continuous aggregates, alerting | yes |
| a queue/CDC source already exists | yes |

- Most "real-time" requirements are five-minute batch. Ask what decision changes
  within the minute.
- Streaming adds state, ordering, and operational burden — pay it only for a
  named action.

## Decision 3 — Storage shape

- **Warehouse** — structured, governed, fast for BI; best when consumers are
  SQL.
- **Lake** — cheap, flexible, open formats; needs discipline or it becomes a
  swamp.
- **Lakehouse** (Iceberg/Delta/Hudi) — table semantics over object storage;
  choose when both ML and SQL read the same data.
- Files in object storage with no table format are not a platform; they are a
  folder.

## Decision 4 — The envelope

Declare numerically, per dataset:

- **freshness** — how stale before it is wrong (not "as fast as possible");
- **volume and growth** — monthly GB/rows, and what breaks first;
- **quality** — the tests that must pass before publish;
- **cost** — storage + compute per month, and what drives it;
- **latency to consumer** — end to end including the BI query.

## Decision 5 — Ownership and contracts

- Producers own the schema they emit; consumers register what they read.
- A breaking schema change is a versioned event, not a silent rename.
- PII is classified at ingestion; masking and retention follow it downstream.
- One canonical definition per business metric, owned by a named person.

## Failure modes at scale

- A gold table nobody can rebuild because raw was overwritten in place.
- Two dashboards, two definitions of "active user", both defended.
- Everything scheduled at midnight; the cluster melts and SLAs miss.
- Real-time pipeline whose only consumer is a dashboard refreshed hourly.
- Cost discovered when finance asks why storage grew 4× in a quarter.

## Verification receipts

1. Flow diagram with owners and freshness targets per hop.
2. Raw layer proven replayable: rebuild one gold table from raw.
3. Envelope table with freshness, volume, cost, and quality per dataset.
4. PII classification list with the masking rules applied downstream.
5. Metric definitions register with a named owner for each.
