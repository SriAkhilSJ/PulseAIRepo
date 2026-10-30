---
name: api-ingestion-architect
description: Architect-level ingestion from third-party APIs — rate limits and quota budgets, pagination and incremental cursors, backoff and resumability, schema drift in external payloads, and the replayable raw landing zone that makes a flaky source survivable. Use when data comes from an HTTP API you do not control.
license: MIT
compatibility: Any SaaS API; Airbyte, Fivetran, custom connectors
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/ingestion-architect/api-ingestion-architect
  crusor-origin: original
  crusor-sources: "stripe.com/docs/rate-limits; developers.salesforce.com; airbyte.com/docs"
  crusor-triggers: "api ingestion, rate limit, pagination, cursor, incremental sync, connector, saas data, rest sync, backoff"
  crusor-verified-on: "2026-10-30"
---

# API Ingestion Architect

Every external API is **a shared resource with a quota, a schema you do not own, and
outages you cannot page anyone about**. Design for partial failure from the start.

## When to use

- Pulling data from SaaS platforms, payment providers, CRMs, ad networks.
- Building or operating a connector.
- Syncs that fail, duplicate, or miss records.

## When NOT to use

- The source offers CDC or bulk export — use that instead.
- One-off extraction into a spreadsheet.

## Decision 1 — Sync model

| Model | Use |
|---|---|
| full refresh | small endpoints, unstable incremental keys |
| incremental by cursor (`updated_since`) | the default |
| paginated cursor with page token | large listings |
| webhook push + reconcile | fresh, low-latency, still needs a poll |
| bulk export API | high volume, cheaper per record |

- Persist the cursor durably with the loaded data; a cursor in memory loses progress
  on restart.
- Overlap the cursor by a safety margin (clock skew, eventual consistency) and
  deduplicate on the natural key.
- Webhooks are an optimisation, never the only mechanism — always reconcile.

## Decision 2 — Quotas

- Know the limits per endpoint: requests/second, daily quota, concurrent requests.
- Budget the quota across streams; one heavy backfill must not starve live syncs.
- Backoff on 429/5xx with jitter and respect `Retry-After`.
- Nightly full refresh against a rate-limited API is a design error, not a schedule.

## Decision 3 — Landing zone

- Land raw payloads (or a faithful projection) append-only with ingestion timestamp
  and request metadata — you will need to replay after a parsing fix.
- Then normalise in a separate step; parsing bugs must not require re-fetching.
- Record the cursor/watermark alongside each batch.
- Retain enough history to rebuild the current state.

## Decision 4 — Schema drift

- External payloads add fields without notice; parsing must tolerate unknown fields.
- Track field presence over time; a field disappearing is an incident signal.
- Type changes (string to number, null to object) break strict parsers — coerce
  defensively and log.
- Version your normalised schema and migrate explicitly.

## Decision 5 — Failure handling

- Resumability: restart from the last committed cursor, not from the beginning.
- Poison records: quarantine, continue, and report — never block the whole sync.
- Idempotency: dedupe on natural key + updated_at, so a replay does not duplicate.
- Alerting: freshness per stream, failure streak, and quota consumption.

## Failure modes at scale

- Cursor stored in memory; every restart re-syncs a year of data and burns the quota.
- Full refresh nightly on a 100k-row API with a 10k/day quota.
- Parser drops unknown fields; a new field is silently lost for months.
- One 500 response aborts the run; the stream is stale for a week.
- Webhook-only ingestion; missed events never reconciled.

## Verification receipts

1. Sync model per stream, with cursor storage location.
2. Quota budget allocation across streams, with measured consumption.
3. Replay test: raw zone re-parsed to produce identical normalised output.
4. Schema-drift test: payload with an extra field and a changed type.
5. Freshness alert per stream, exercised with an induced failure.
