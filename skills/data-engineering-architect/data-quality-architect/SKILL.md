---
name: data-quality-architect
description: Architect-level data quality and contract design — producer-consumer contracts, the test taxonomy from schema to distribution, freshness and volume checks, anomaly detection, incident response for bad data, and the lineage needed to contain the blast radius. Use when data must be trusted by someone making decisions.
license: MIT
compatibility: dbt tests, Great Expectations, Soda, Monte Carlo, OpenLineage
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/data-quality-architect
  crusor-origin: original
  crusor-sources: "docs.getdbt.com/docs/build/tests; greatexpectations.io/docs; openlineage.io/docs"
  crusor-triggers: "data quality, data contract, data test, freshness, schema drift, anomaly detection, data incident, lineage, validity check, null spike, duplicate, duplicates, disagree"
  crusor-verified-on: "2026-10-30"
---

# Data Quality Architect

Bad data is **an outage with a delayed detection**. Quality is a pipeline property
with owners, tests, and an incident process — not a cleanup sprint.

## When to use

- Anyone makes decisions or sends money based on the data.
- Designing producer/consumer boundaries across teams.
- A metric has been wrong and nobody knows since when.

## When NOT to use

- Exploratory analysis on scratch data.
- The issue is one bad SQL query — fix the query.

## Decision 1 — Contracts

A data contract is a versioned artefact the producer commits to:

| Element | Example |
|---|---|
| schema | columns, types, nullability, units |
| key | primary key, uniqueness guarantee |
| cadence | emitted every 15 min, by :05 |
| semantics | what "active" means |
| breaking change | version bump + deprecation window |
| owner | team + channel |

- Contracts live in the repo and are enforced in CI on both sides.
- Consumers declare what they read; that is the dependency graph that lets you
  warn people before a change lands.

## Decision 2 — The test taxonomy

| Layer | Tests |
|---|---|
| schema | columns present, types stable, no silent casts |
| keys | uniqueness, non-null, referential integrity |
| ranges | non-negative, within bounds, accepted enum values |
| volume | row count within expected band vs last 7 runs |
| freshness | max(loaded_at) within SLA |
| distribution | null rate, mean/percentiles, category share |
| reconciliation | sums match source for the same window |

- Test the **silver/gold boundary** hardest: that is where semantics change.
- A test that never fails in six months is either brilliant or vacuous — audit it.

## Decision 3 — Where checks run

- **In the pipeline (blocking)** — key, schema, freshness. Fail the run; do not
  publish bad data.
- **After publish (alerting)** — distribution and anomaly checks that need history.
- **At consumption (query-time)** — cheap guards in the semantic layer for critical
  metrics.
- Blocking checks protect consumers; alerting checks catch drift. You need both.

## Decision 4 — Anomaly detection

- Baseline per table per seasonality (weekday/weekend); static thresholds create
  alert fatigue on growth.
- Alert on **business impact**: revenue table variance matters more than a
  marketing table's row count.
- Route alerts to the owning team with the failing test, the affected table, and
  the downstream consumers.
- Tune aggressively: an alert nobody acts on trains the team to ignore all alerts.

## Decision 5 — Incidents

- Bad data is an incident: severity, owner, comms channel, and a timeline.
- Contain first: mark the table as quarantined, notify consumers, stop publishing.
- Determine the window of corruption — that is the difference between a fix and a
  rebuild.
- Rebuild from raw, verify with reconciliation against source, then republish.
- Post-incident: a test that would have caught it, added before closing.

## Decision 6 — Lineage

- Column-level lineage where available; table-level minimum.
- Before a schema change, answer: which dashboards, models, and exports break?
- Lineage also gives you the blast radius during an incident and the deprecation
  list during cleanup.

## Failure modes at scale

- Tests that only check `not null` and call the data "validated".
- Freshness alert at 08:00 for a 06:00 SLA.
- A producer renames a column; 30 dashboards silently show zero.
- Hundreds of anomaly alerts a week; the channel is muted.
- The corruption window unknown, so everything since quarter-end is rebuilt.

## Verification receipts

1. Contract file per source, enforced in CI, with an owner and channel.
2. Test coverage matrix per gold table (schema, key, volume, freshness).
3. A deliberately broken column blocked before publish.
4. Anomaly alert exercised and routed to a human in under the SLA.
5. One incident post-mortem with the test it produced.
