---
name: lineage-architect
description: Architect-level data lineage — table and column lineage capture, impact analysis before schema changes, provenance for audits, lineage-driven debugging when a number is wrong, and the tooling (OpenLineage, dbt artefacts, catalog integrations) that makes it automatic rather than documented. Use when you must answer "where did this come from" and "what breaks if I change it".
license: MIT
compatibility: OpenLineage, Marquez, dbt artefacts, DataHub, Unity Catalog
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/quality-architect/lineage-architect
  crusor-origin: original
  crusor-sources: "openlineage.io/docs; datahubproject.io/docs; docs.getdbt.com/docs/collaborate/explore-projects"
  crusor-triggers: "data lineage, impact analysis, column lineage, openlineage, datahub, provenance, upstream downstream, dependency graph"
  crusor-verified-on: "2026-10-30"
---

# Lineage Architect

Lineage is **the map you need when something is wrong**. If it is hand-maintained, it
is wrong; capture it from the tools that already know.

## When to use

- Schema changes need impact analysis before merge.
- An audit asks where a figure came from.
- Debugging why a dashboard number changed.

## When NOT to use

- A single pipeline with no consumers beyond one report.
- As a documentation project — lineage must be emitted by tools, not written by hand.

## Decision 1 — Capture

| Source | Emits |
|---|---|
| dbt | model and column lineage, exposures |
| orchestration (Airflow/Dagster) | task and dataset edges |
| Spark/Flink jobs | OpenLineage events |
| warehouse query logs | table-level read/write |
| BI tools | dashboard → table edges |

- Prefer automatic emission (OpenLineage, native integrations) over YAML you must
  maintain.
- Column-level where available; table-level is the minimum viable.
- Capture **runtime** lineage, not just declared dependencies — dynamic SQL and
  `SELECT *` hide edges.

## Decision 2 — Use it

- Pre-merge check: list downstream consumers of the changed table; block if any are
  unowned.
- Debugging: walk upstream from the broken number to the first divergence.
- Incident response: which dashboards and exports are affected, and by how much.
- Deprecation: no lineage downstream means safe to delete (after a wait).

## Decision 3 — Quality of the graph

- Orphans: tables with consumers nobody recorded; treat as risk.
- Cycles: impossible in a healthy DAG; usually a stale declaration.
- Untracked sources: files, APIs, spreadsheets feeding the warehouse by hand.
- Keep a freshness timestamp per node; stale edges are worse than missing ones.

## Decision 4 — Governance tie-in

- Ownership metadata on nodes (team, contact) so lineage produces an escalation path.
- Classification tags (PII, financial) inherited downstream — a column-level tag
  follows its derivations.
- Retention and deletion requests use lineage to find every copy.

## Failure modes at scale

- Wiki diagram six months stale; nobody trusts it, so nobody uses it.
- `SELECT *` in models; column lineage breaks exactly where it matters.
- Impact analysis done by grep; a rename breaks a dashboard three days later.
- PII column copied into an unmasked table; the tag did not propagate.
- Lineage tool installed, not connected to BI; only half the graph exists.

## Verification receipts

1. Lineage captured from at least dbt and orchestration, with a graph export.
2. Impact analysis run for a real schema change, before merge.
3. One debugging session using upstream walk-through, documented.
4. Untracked-source list, with a plan for each.
5. Ownership and classification metadata visible on a sample of nodes.
