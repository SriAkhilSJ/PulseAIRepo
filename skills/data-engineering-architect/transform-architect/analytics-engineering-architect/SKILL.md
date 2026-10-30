---
name: analytics-engineering-architect
description: Architect-level analytics engineering — dbt project structure, staging and mart conventions, metric definitions and the semantic layer, incremental models, testing and documentation as code, and the review process that keeps SQL maintainable. Use when analysts and engineers share a SQL transformation layer.
license: MIT
compatibility: dbt Core/Cloud, SQLMesh, LookML, Cube, MetricFlow
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/transform-architect/analytics-engineering-architect
  crusor-origin: original
  crusor-sources: "docs.getdbt.com; docs.getdbt.com/docs/build/semantic-models; cube.dev/docs; sqlmesh.readthedocs.io"
  crusor-triggers: "dbt, analytics engineering, semantic layer, metrics, sql models, staging models, lookml, metric definition, data mart, transformed model, disagree, revenue number, metric drift"
  crusor-verified-on: "2026-10-30"
---

# Analytics Engineering Architect

The transformation layer is **software with consumers**. It needs modules, tests,
reviews, and one definition per metric — or it becomes a folder of queries with
tense relationships.

## When to use

- Analysts and engineers share SQL transformations.
- Building or untangling a dbt project.
- Two dashboards disagree on a number.

## When NOT to use

- One-off analysis in a notebook.
- Pipeline extraction and loading → `batch-pipeline-architect`.

## Decision 1 — Project structure

```
models/
  staging/     stg_<source>__<entity>     one per source table, renamed & typed
  intermediate/ int_<entity>__<verb>      joins and business logic, not exposed
  marts/       fct_/dim_/obt_<domain>     consumed by BI, owned by a domain
```

- Staging does **only** rename, cast, deduplicate. No joins, no business logic.
- Intermediate models keep marts readable; they are private by default.
- Marts are the public API: named, documented, tested, and owned.
- One source definition per source table; freshness checked at the source.

## Decision 2 — Materialisation

| Model | Materialisation |
|---|---|
| staging | view |
| intermediate | ephemeral or view |
| dimension | table |
| fact (large, incremental) | incremental with a merge key |
| mart for BI | table or view depending on query cost |

- Views are free to build and expensive to query; tables are the reverse.
- Incremental only with a correct unique key and a late-data strategy.
- Iceberg/Delta dynamic tables where the warehouse supports them — less bespoke
  incremental logic.

## Decision 3 — Metrics

- A metric is defined once: name, description, formula, grain, filters, owner.
- Encode it in the semantic layer (MetricFlow/Cube/LookML), not in 12 dashboards.
- Define the entity graph so a metric can be sliced consistently across facts.
- Changing a metric is a versioned event with an announcement, not a quiet edit.
- Track metric lineage to source tables; a metric that cannot explain itself is a
  rumour.

## Decision 4 — Testing and docs as code

- Every mart: uniqueness and not-null on its key, relationships to dimensions,
  accepted values for enums, and a freshness check.
- Document every model with purpose, grain, and owner — generated docs, not a wiki.
- Exposures declare dashboards and downstream consumers; that powers impact
  analysis.
- CI: `dbt build` on a sample schema + linting + contract tests before merge.

## Decision 5 — Review and ownership

- SQL gets code review like any code: readability, joins that can fan out,
  filters that silently drop rows.
- Domain ownership: each mart has a named team responsible for its correctness.
- Deprecation: mark, announce with a date, then remove. Never delete a used model
  on a Friday.
- Cost review: which models are rebuilt hourly and read twice a day?

## Failure modes at scale

- 400 models with no staging layer; every mart re-implements the same casts.
- Three definitions of revenue, all "official", in three tools.
- Incremental model with no unique key, slowly accumulating duplicates.
- Docs generated once at launch, stale within a month.
- A mart deleted by a cleanup pass; four dashboards break the next morning.

## Verification receipts

1. Layer conventions documented and enforced in CI/lint.
2. Metric definitions register with one owner each; no duplicates.
3. `dbt build` green on a CI sample including tests and contracts.
4. Fan-out test: fact-to-dimension joins produce no row multiplication.
5. Deprecation log with consumers mapped via exposures.
