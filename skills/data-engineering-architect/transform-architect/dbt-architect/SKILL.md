---
name: dbt-architect
description: Architect-level dbt project design — project and package structure, sources and staging conventions, incremental models and their keys, tests and contracts, exposures and lineage, CI with state comparison, and the selector strategy for large projects. Use when transformations run in dbt.
license: MIT
compatibility: dbt Core/Cloud, SQLMesh; Snowflake/BigQuery/Databricks/Postgres
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/transform-architect/dbt-architect
  crusor-origin: original
  crusor-sources: "docs.getdbt.com/docs/build/incremental-models; docs.getdbt.com/docs/collaborate/state; docs.getdbt.com/best-practices"
  crusor-triggers: "dbt, dbt project, incremental model, dbt test, dbt sources, dbt exposures, slim ci, dbt selectors, packages.yml"
  crusor-verified-on: "2026-10-30"
---

# dbt Architect

dbt is **a compiler and a DAG for SQL**. The project structure decides whether that
DAG is understandable at 300 models.

## When to use

- SQL transformations run on a warehouse.
- A dbt project has grown past the point of comprehension.
- Setting up CI and environments for transformations.

## When NOT to use

- Transformations need Python/heavy compute — use a Spark/notebook pipeline.
- A handful of queries with one consumer.

## Decision 1 — Structure

```
models/
  staging/<source>/stg_<source>__<entity>.sql     rename, cast, dedupe only
  intermediate/     int_<domain>__<verb>.sql       joins, business logic
  marts/<domain>/   fct_/dim_/rpt_<entity>.sql     consumed, documented, tested
  sources.yml       one per source system, freshness configured
  exposures.yml     dashboards/ML/APIs that read marts
```

- Staging models are 1:1 with source tables; no joins.
- Intermediate models keep marts thin and readable; mark private.
- Marts are contracts: documented, tested, owned.

## Decision 2 — Materialisation

| Model | Materialisation |
|---|---|
| staging | view |
| intermediate | ephemeral (or view if reused widely) |
| dimension | table |
| large fact | incremental with `unique_key` + `merge` |
| small mart | table |

- Incremental requires a unique key, a `is_incremental()` filter, and a late-data
  strategy; without all three it accumulates duplicates.
- Full refresh is a tool, not a schedule — make it possible, not routine.
- Snapshots for slowly changing dimensions, with a defined `updated_at`.

## Decision 3 — Tests and contracts

- Sources: freshness + `not_null`/`unique` on keys.
- Marts: uniqueness, relationships, accepted values, and at least one business rule.
- Model contracts (`contract: enforced: true`) for marts consumed outside the
  project.
- Tests are code: review them, and delete ones that can never fail.

## Decision 4 — CI and environments

- Dev/prod targets in separate schemas or databases; never test in prod.
- Slim CI: `state:modified+` against the production manifest — only build what
  changed.
- `dbt build` in CI (models + tests), plus linting (sqlfluff) and docs generation.
- Artefacts (manifest, run results) persisted for lineage and state comparison.

## Decision 5 — Scale

- Selectors and tags for domains (`+tag:finance`) so runs are bounded.
- Packages pinned by version; a floating package is an untested dependency upgrade.
- Model count discipline: deprecate aggressively, expose lineage via exposures.
- Keep run times within the orchestration window; a 3-hour nightly build is a design
  constraint, not a badge.

## Failure modes at scale

- Every mart re-implements casts because staging was skipped.
- Incremental model with no unique key; duplicates grow silently.
- 400 models, one tag, full build on every PR.
- Tests written once at launch and never updated after schema changes.
- Package upgraded on a Friday; a macro change breaks 40 models.

## Verification receipts

1. Layer conventions documented and enforced with lint rules.
2. `dbt build` green in CI with slim selection demonstrated.
3. Incremental model tested twice on the same window — no duplicates.
4. Source freshness configured with an alert.
5. Lineage graph showing exposures for the top marts.
