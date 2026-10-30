---
name: semantic-layer-architect
description: Architect-level semantic layer design — metric definitions as code, entities and dimensions, consistency across BI and APIs, caching and query routing, and the governance that keeps one number meaning one thing. Use when several tools must report the same metrics.
license: MIT
compatibility: dbt Semantic Layer/MetricFlow, Cube, LookML, AtScale
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/transform-architect/semantic-layer-architect
  crusor-origin: original
  crusor-sources: "docs.getdbt.com/docs/build/semantic-models; cube.dev/docs; cloud.google.com/looker/docs/lookml-project-files"
  crusor-triggers: "semantic layer, metric definition, metrics layer, lookml, cube, consistent metrics, single source of truth, metric governance"
  crusor-verified-on: "2026-10-30"
---

# Semantic Layer Architect

A semantic layer answers **"what does this number mean"** once, in code. Without
one, every tool invents its own arithmetic and the arguments are unwinnable.

## When to use

- More than one BI tool, API, or team asks the same business question.
- Metric definitions live in dashboards and spreadsheets.
- Self-serve analytics needs guardrails, not raw tables.

## When NOT to use

- One analyst, one dashboard, no consumers.
- The metrics are genuinely exploratory and unstable.

## Decision 1 — Model

| Element | Meaning |
|---|---|
| entity | the grain (order, customer, session) |
| dimension | how you slice (country, plan, channel) |
| measure | additive quantity (revenue, quantity) |
| metric | calculation over measures (AOV = revenue ÷ orders) |
| filter/segment | scoped metric (revenue, paid plan only) |

- Define metrics on entities, not on tables, so they survive schema refactors.
- One metric, one definition, one owner; derived metrics must reference the base.
- Time dimensions are first-class: fiscal calendars, time zones, and snapshot
  semantics are where definitions silently diverge.

## Decision 2 — Where it lives

- In the transformation project (dbt Semantic Layer) so it is versioned with models.
- Exposed to BI via the layer's connector, not by exporting SQL per tool.
- API consumers query the layer (GraphQL/REST) to avoid re-implementing logic.
- Caching at the layer for repeated identical queries; invalidate on model rebuild.

## Decision 3 — Governance

- Metric owner named; changes reviewed like code and announced.
- Deprecation: mark, announce, provide the replacement, then remove.
- Certification: a "certified" tag means tested against source of truth.
- Track usage; a metric with zero queries is a candidate for removal.

## Decision 4 — Consistency checks

- Reconcile layer output against raw SQL for the top 10 metrics, monthly.
- Test that filters/segments compose correctly (no double counting).
- Watch non-additive metrics (distinct counts, ratios) across grains — averaging an
  average is the classic error.
- Time zone and currency conversions belong in the layer, not in each dashboard.

## Failure modes at scale

- Three definitions of "active user", all certified, in different tools.
- Metric defined per dashboard; a filter change silently changes the number.
- Semantic layer built but BI still queries raw tables directly.
- Distinct-count metrics summed across days, double counting users.
- No owner; a metric definition changes and nobody can say why the number moved.

## Verification receipts

1. Metric catalogue: name, definition, grain, owner, certification.
2. Reconciliation report versus raw SQL for the top metrics.
3. BI and API both reading the layer, demonstrated with the same query.
4. Non-additive metric test across grains.
5. Deprecation record for one retired metric.
