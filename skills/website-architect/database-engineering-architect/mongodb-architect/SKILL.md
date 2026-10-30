---
name: mongodb-architect
description: Architect-level MongoDB guidance — document modelling by access pattern, embed-versus-reference decisions, index and aggregation strategy, schema validation, and the unbounded-document traps that make Mongo slow or expensive. Use when designing or reviewing a MongoDB data model.
license: MIT
compatibility: MongoDB 6/7+; any driver or ODM
metadata:
  crusor-domain: website-architect
  crusor-path: database-engineering-architect/mongodb-architect
  crusor-origin: original
  crusor-sources: "mongodb.com/docs/manual; mongodb.com/docs/manual/data-modeling"
  crusor-triggers: "mongodb, mongo, documents, aggregation pipeline, embed, references, nosql, mongoose"
  crusor-verified-on: "2026-10-30"
---

# MongoDB Architect

MongoDB is **not "SQL without joins"**. It is a model where the document boundary
*is* the atomic unit — so the schema follows the query, not the entity.

## When to use

- Aggregates are read and written as a unit (order + lines, profile + settings).
- Shape varies by tenant or evolves fast, with query patterns known.
- Document-per-entity access dominates; joins are rare.

## When NOT to use

- Multi-entity reporting, ad-hoc joins, strong relational integrity.
- Highly relational data or money/inventory requiring cross-document
  transactions at volume.

## Decision 1 — Model by access pattern

| Relationship | Choose |
|---|---|
| read together, bounded size | embed |
| referenced by many, unbounded | reference |
| many-to-many with attributes | reference + lookup collection |
| unbounded growth (events, logs) | separate collection, time-bucketed |

- Never embed an array that can grow without limit (16 MB document cap and
  in-place update costs).
- Duplicate data is a **decision with a sync owner**, not an accident.
- Each collection is designed for the queries it serves; a second query shape
  may warrant a second collection (CQRS-style).

## Decision 2 — Indexes

- Index for the actual query: equality fields, then sort field, then range.
- Compound index prefix rules apply the same as relational.
- `explain("executionStats")`: watch `totalDocsExamined` vs `nReturned`.
- TTL indexes for expiring data; partial indexes for hot subsets.
- Text search: `$text` for simple needs, Atlas Search for real relevance.

## Decision 3 — Writes and consistency

- Single-document writes are atomic; multi-document transactions exist but are
  a design smell at high volume — restructure instead.
- Write concern: acknowledge majority for durability-critical writes.
- Read concern: `local` for speed, `majority` for correctness-sensitive reads.
- Optimistic concurrency with a version field for contended updates.

## Decision 4 — Validation and evolution

- `$jsonSchema` validation on collections where shape matters.
- Migrations are scripts run as deploys: backfill, dual-read, switch, clean up.
- Field renames are dual-write migrations, never in-place rewrites of a large
  collection.

## Decision 5 — Aggregation discipline

- `$match` first, then `$lookup` — pipelines that start with lookups scan
  everything.
- `$lookup` on unindexed foreign fields is a collection scan per document.
- `allowDiskUse` hides a design problem; keep the pipeline in memory.
- Materialise expensive aggregates into a read collection, refreshed on write.

## Failure modes at scale

- Embedded arrays growing unbounded until documents hit the size cap.
- `$lookup` joins turning a 3 ms query into 900 ms.
- No compound index for the main list query → collection scans under load.
- Transactions used per-request to emulate a relational schema.
- No validation → five shapes of the same document in one collection.

## Verification receipts

1. Model documented: embed vs reference per relationship, with size bounds.
2. `explain("executionStats")` for the top queries, index used.
3. Validation schema present on shape-critical collections.
4. Unbounded-array audit: every array has a cap or an archive path.
5. Write/read concern chosen per collection, documented.
