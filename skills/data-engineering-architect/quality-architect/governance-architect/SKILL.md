---
name: governance-architect
description: Architect-level data governance — catalogue and ownership, classification and PII handling, access models and row/column policies, retention and deletion obligations, and the review cadence that keeps a catalogue true. Use when data must be found, classified, and lawfully retained.
license: MIT
compatibility: DataHub, Unity Catalog, Purview, Atlan, lakekeeper
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/quality-architect/governance-architect
  crusor-origin: original
  crusor-sources: "datahubproject.io/docs; learn.microsoft.com/purview; gdpr.eu; nist.gov/privacy-framework"
  crusor-triggers: "data governance, data catalogue, pii, data classification, retention policy, gdpr, data access policy, ownership, data steward"
  crusor-verified-on: "2026-10-30"
---

# Data Governance Architect

Governance is **metadata with consequences**. A catalogue nobody trusts and a policy
nobody enforces are documentation, not governance.

## When to use

- Multiple teams share data; PII, financial, or health data is involved.
- A regulator, auditor, or customer security review asks where data lives.
- Deletion or access requests must be answered accurately.

## When NOT to use

- One team, one warehouse, no sensitive data — start with ownership and classification
  only.

## Decision 1 — Catalogue

- One entry per table/view with: owner (team), description, grain, refresh cadence,
  classification, and quality status.
- Populate automatically from the warehouse, dbt artefacts, and BI tools; manual
  entry is stale on arrival.
- Search must work: a catalogue you cannot query is a spreadsheet in a nicer font.
- Deprecation state visible, so consumers stop building on doomed tables.

## Decision 2 — Ownership

- Every dataset has a named owning team and a contact channel; "data team" is not an
  owner.
- Steward role for semantics (definitions, quality expectations) distinct from the
  engineer who builds it.
- Unclaimed datasets are flagged and either adopted or deleted on a schedule.

## Decision 3 — Classification

| Class | Handling |
|---|---|
| public | no restriction |
| internal | authenticated access |
| confidential | need-to-know, logged |
| restricted (PII/PHI/PCI) | column policies, masking, audit, retention |

- Classify at ingestion; propagate downstream automatically (`lineage-architect`).
- PII detection both by rule (column names/patterns) and sampling; rules miss.
- Masking policies attach to the class, not to individual tables.

## Decision 4 — Access

- Role-based access at schema, with row filters and column masks at table level.
- Access requests through a workflow with approval and expiry; standing broad access
  is the exception, documented.
- Break-glass access logged and reviewed.
- Reviews quarterly: who has access to restricted data, and why.

## Decision 5 — Retention and deletion

- Retention per class and dataset, enforced by lifecycle automation — not by memory.
- Deletion must reach backups and derived tables within a stated window; use lineage
  to find them.
- Legal hold overrides retention; the mechanism is documented before it is needed.
- Evidence for audits: a deletion report per request.

## Failure modes at scale

- Catalogue with 5,000 tables, 60% unowned, last updated a year ago.
- PII in a "public" schema because classification required a form nobody filed.
- Retention policy in a PDF; data from 2014 still in the warehouse.
- Deletion request satisfied in the source table but not in the analytics copy.
- Everyone has read access to everything "to move fast"; the audit finding is severe.

## Verification receipts

1. Catalogue coverage and ownership percentage for production datasets.
2. Classification report with PII columns and their masking policy.
3. Access review output for restricted datasets.
4. Deletion drill: request executed across source, warehouse, and backups.
5. Retention automation verified on one expired dataset.
