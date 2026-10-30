---
name: sql-modelling-architect
description: Architect-level analytical SQL modelling — grain and grain declarations, star versus wide-table trade-offs, slowly changing dimensions, deduplication patterns, and the join and window patterns that stay correct as data grows. Use when deciding how analytical tables should be shaped.
license: MIT
compatibility: Any SQL warehouse
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/transform-architect/sql-modelling-architect
  crusor-origin: original
  crusor-sources: "docs.getdbt.com/docs/build; kimballgroup.com; cloud.google.com/bigquery/docs/best-practices-performance-patterns"
  crusor-triggers: "sql modelling, star schema, grain, slowly changing dimension, deduplication, window function, join fanout, wide table"
  crusor-verified-on: "2026-10-30"
---

# SQL Modelling Architect

Analytical models fail in two ways: **the grain is unstated**, or the join fans out.
Both produce numbers that look plausible and are wrong.

## When to use

- Designing fact and dimension tables.
- A metric changes when a new join is added.
- History (SCD) must be preserved.

## When NOT to use

- Simple aggregations over one table — write the query.
- Operational schema design (OLTP) — that is a different discipline.

## Decision 1 — Grain first

- Write the grain in the model name and the header comment: `one row per order line`.
- Test it: `count(*) = count(distinct key)` as a dbt test, always.
- Every metric must state which grain it is valid at; summing across mixed grains is
  how revenue doubles.

## Decision 2 — Shape

| Shape | Use |
|---|---|
| star (facts + conformed dims) | stable BI, many metrics, cross-domain slicing |
| wide/OBT | one mart, one consumer, fast queries |
| normalized vault | auditability, many sources, regulated |
| one big table per dashboard | cheap now, unmaintainable at 20 dashboards |

- Wide tables are legitimate for a bounded mart; they become debt when every mart is
  a different wide table over the same facts.

## Decision 3 — History

| SCD type | Behaviour |
|---|---|
| 1 | overwrite, no history |
| 2 | valid_from/valid_to + current flag |
| 3 | previous value column |
| snapshot fact | periodic state capture |

- Choose per attribute: a customer's address needs history, their boolean flag may
  not.
- SCD2 joins must be time-bounded (`event_ts between valid_from and valid_to`) or you
  fan out.
- Late-arriving data in SCD2 needs a defined policy: backfill versions or accept a
  cutoff.

## Decision 4 — Joins and windows

- Fan-out check: join on the key at the **left** table's grain; aggregate before the
  join where possible.
- Dedupe deterministically: `row_number() over (partition by key order by updated_at
  desc) = 1`, never `distinct` on a wide row.
- Window functions need an explicit frame when order matters; default frames hide
  bugs.
- Pre-aggregate before joining to a dimension to avoid multiplying measures.

## Decision 5 — Testing

- Uniqueness and not-null on every key.
- Relationship tests against dimensions.
- Reconciliation: fact totals equal the source total for the same window.
- Grain test on every fact; a fact without a grain test is undocumented.

## Failure modes at scale

- New join added for one dashboard; revenue doubles across the mart.
- SCD2 joined without time bounds; row multiplication in every report.
- Deduplication via `distinct` on 40 columns; expensive and unstable.
- Grain unstated; two teams aggregate the same fact differently.
- Window frame omitted; results depend on row order.

## Verification receipts

1. Grain documented per fact and dimension, with a passing grain test.
2. SCD type chosen per attribute, with the time-bounded join demonstrated.
3. Reconciliation report against source totals for one period.
4. Fan-out test before and after a join change.
5. Deduplication query reviewed and its key documented.
