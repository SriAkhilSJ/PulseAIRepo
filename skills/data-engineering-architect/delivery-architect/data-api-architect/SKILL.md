---
name: data-api-architect
description: Architect-level design of data-serving APIs — query patterns and pre-aggregation, caching and freshness, pagination and export endpoints, row-level authorisation, and the cost controls that stop a dashboard API from scanning a warehouse on every request. Use when applications or partners consume analytical data.
license: MIT
compatibility: Any warehouse; GraphQL/REST; Cube, Hasura, custom services
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/delivery-architect/data-api-architect
  crusor-origin: original
  crusor-sources: "cube.dev/docs; hasura.io/docs; cloud.google.com/bigquery/docs/best-practices-costs"
  crusor-triggers: "data api, analytics api, export endpoint, query caching, pagination, row level security, partner data feed, serving analytics, expose analytics, embedded dashboard, partner feed"
  crusor-verified-on: "2026-10-30"
---

# Data API Architect

A data API is **a warehouse query behind an HTTP contract**. Without pre-aggregation
and caching, one dashboard refresh becomes a scan you pay for.

## When to use

- Applications, partners, or customers consume analytical data.
- A dashboard product needs an API for embedding.
- Reports must be exported programmatically.

## When NOT to use

- Internal analysts can query the warehouse directly.
- The data is transactional and belongs in a service API.

## Decision 1 — Query shape

| Access pattern | Design |
|---|---|
| fixed dashboards | pre-aggregated tables or materialised views |
| parameterised slices | curated dimensions, mandatory filters |
| ad-hoc SQL from users | do not expose; offer a fixed query surface |
| large exports | asynchronous job + signed URL |
| single record lookup | serving store, not the warehouse |

- The API should expose metrics and dimensions, not "run this SQL".
- Enforce required filters (date range, tenant) at the API boundary, not in docs.

## Decision 2 — Caching and freshness

- Cache per (metric, dimensions, filters) with a TTL matched to the data cadence.
- Return `generated_at` and data freshness in every response — consumers must know
  how stale it is.
- Invalidate on model rebuild rather than waiting for TTL where possible.
- Warm the cache for top dashboards after a refresh; cold cache at 09:00 is a latency
  cliff.

## Decision 3 — Cost controls

- Per-tenant query budgets and rate limits.
- Reject unbounded date ranges; cap result rows.
- Prefer pre-aggregated marts over live joins on raw events.
- Monitor bytes scanned per endpoint; a single endpoint dominating cost is a design
  smell.

## Decision 4 — Authorisation

- Row-level filters derived from the caller's identity, applied server-side in the
  generated query — never trusted from parameters.
- Column visibility per role: PII hidden unless explicitly granted.
- Tenant isolation tested as a first-class case.
- Audit log per request: who, what slice, how many rows.

## Decision 5 — Pagination and exports

- Keyset pagination for large result sets; offset pagination degrades at scale.
- Exports as async jobs with a status endpoint and a signed, expiring URL.
- Cap export size and rate; an unbounded export is a scan plus an egress bill.
- Provide stable column names and a versioned response contract.

## Failure modes at scale

- API hits the warehouse on every page load; latency 4 s and cost unbounded.
- Row-level filter taken from a request parameter; one tenant reads another's data.
- Offset pagination on 5M rows; late pages time out.
- Exports run synchronously; the gateway times out and users retry, doubling load.
- No freshness metadata; consumers assume real-time.

## Verification receipts

1. Endpoint inventory with the query shape and required filters.
2. Cache design with TTLs and hit-rate measurement.
3. Row-level authorisation test across two tenants.
4. Export job exercised end to end with an expiring URL.
5. Cost per 1,000 requests and the bytes-scanned report per endpoint.
