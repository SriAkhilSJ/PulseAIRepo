---
name: reverse-etl-architect
description: Architect-level reverse ETL design — syncing modelled data back into operational tools, idempotent upserts and record matching, field ownership between warehouse and SaaS, sync frequency and rate limits, and the drift that makes CRM data disagree with the warehouse. Use when analytics output must change behaviour inside operational systems.
license: MIT
compatibility: Census, Hightouch, custom sync jobs, Salesforce/HubSpot APIs
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/delivery-architect/reverse-etl-architect
  crusor-origin: original
  crusor-sources: "docs.getcensus.com; hightouch.com/docs; developer.salesforce.com/docs"
  crusor-triggers: "reverse etl, census, hightouch, sync to salesforce, hubspot sync, operational analytics, field mapping, crm sync, salesforce, crm, sync back, push to crm"
  crusor-verified-on: "2026-10-30"
---

# Reverse ETL Architect

Reverse ETL turns **analysis into action by writing to systems people use daily**.
It also makes the warehouse a writer — which needs ownership rules.

## When to use

- Scores, segments, or flags must appear in a CRM, support tool, or ad platform.
- Sales/CS teams act on model output inside their own tools.
- Manual export-and-import is the current process.

## When NOT to use

- The operational system is the source of truth for that field.
- A read-only integration (embedded dashboard) satisfies the need.

## Decision 1 — Field ownership

| Field | Owner |
|---|---|
| lifecycle stage computed by analytics | warehouse |
| deal stage set by sales | CRM |
| lead score | warehouse |
| contact email | CRM (or the system of record) |

- Write a field map that names the owner of every synced field. Two writers to one
  field produce silent flip-flopping.
- Never sync a field the operational team also edits unless you have a merge rule.

## Decision 2 — Record matching

- Match on a stable external id stored in both systems; email/name matching creates
  duplicates at scale.
- Define create-versus-update behaviour explicitly: some syncs should never create.
- Handle archived/deleted records: a deleted CRM record must not be resurrected by a
  nightly sync.
- Test with messy real data: duplicates, missing ids, unicode names.

## Decision 3 — Sync mechanics

- Idempotent upserts keyed by the external id; re-running a sync must be safe.
- Incremental by `updated_at` in the warehouse model, with a lookback window.
- Respect API rate limits and batch sizes; backoff on 429.
- Sync frequency matched to the decision cadence — a lead score refreshed hourly is
  usually wasted API calls.

## Decision 4 — Observability

- Per-sync metrics: records attempted, succeeded, failed, skipped (with reasons).
- Alert on failure streaks and on unexpected drop in record counts to zero.
- Log the field values written for a sample, for dispute resolution ("the CRM says
  X").
- Reconcile weekly: count of synced records versus the source model.

## Decision 5 — Governance

- PII written outward needs the same classification as inward (`governance-architect`).
- Access to the sync tool is privileged: it can write to production systems.
- Change management: schema changes in the destination break syncs silently — monitor
  field-level errors.

## Failure modes at scale

- Email-based matching; 4,000 duplicate contacts created in a week.
- Sales edits a field the sync overwrites nightly; trust in the data collapses.
- Sync fails silently on a renamed Salesforce field; a quarter of scores missing.
- Deleted CRM records recreated by the "create if missing" setting.
- Warehouse model changed column names; 30% of records skipped with no alert.

## Verification receipts

1. Field ownership map signed off by both teams.
2. Matching strategy with duplicate-rate measured on real data.
3. Idempotency test: same sync run twice, no duplicate destination records.
4. Sync dashboard with success/failure/skip reasons.
5. Reconciliation report between model and destination counts.
