---
name: vector-store-architect
description: Architect-level vector database design — index type and recall/latency trade-offs, filtering and tenancy, metadata schema, sharding and replication, updates and deletes, and the operational difference between pgvector, Qdrant, Weaviate, and managed services. Use when vectors need a home beyond a prototype.
license: MIT
compatibility: pgvector, Qdrant, Weaviate, Milvus, Pinecone, OpenSearch
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/retrieval-architect/vector-store-architect
  crusor-origin: original
  crusor-sources: "github.com/pgvector/pgvector; qdrant.tech/documentation; weaviate.io/developers/weaviate; docs.pinecone.io"
  crusor-triggers: "vector database, pgvector, qdrant, weaviate, pinecone, hnsw, ivf, ann index, similarity search, vector index, vector search, irrelevant results, retrieval quality"
  crusor-verified-on: "2026-10-30"
---

# Vector Store Architect

A vector store is **an index with a consistency model**. Most failures are not
recall problems — they are filtering, tenancy, and delete semantics.

## When to use

- More than a few hundred thousand vectors, or strict latency targets.
- Metadata filtering combined with similarity search.
- Multi-tenant retrieval with isolation requirements.

## When NOT to use

- Small corpus where Postgres with pgvector is already deployed and sufficient.
- Pure keyword search — that is a text index.

## Decision 1 — Engine

| Engine | Fit |
|---|---|
| pgvector | already on Postgres, moderate scale, transactional consistency |
| Qdrant | filtering-heavy, self-hosted, strong payload model |
| Weaviate | hybrid search and modules out of the box |
| Milvus | very large scale, dedicated ops |
| Pinecone | managed, low ops, higher cost at scale |
| OpenSearch/Elasticsearch | existing search platform, hybrid needs |

- Introducing a new datastore means a new backup, auth, and monitoring story. Pay
  it only for a real capability gap.
- Estimate: vectors × dimensions × 4 bytes × (1 + index overhead) — then compare to
  available RAM.

## Decision 2 — Index

| Index | Trade-off |
|---|---|
| flat/exact | perfect recall, slow at scale |
| HNSW | fast queries, memory-hungry, high build cost |
| IVF-PQ | memory efficient, recall loss, tuning required |
| disk-based (DiskANN) | large corpora with acceptable latency |

- Always measure recall@k against exact search on a sample; "it feels fast" is not
  recall.
- Tune `m`/`ef_construction`/`nprobe` against latency budget, then freeze the
  parameters with the index version.
- Rebuilding an index is an operational event: plan capacity and a maintenance
  window.

## Decision 3 — Schema and filtering

- Metadata carries: tenant, document id, section, timestamps, permissions,
  embedding model version.
- Filter **inside** the vector search (pre-filter), not after retrieval — post-filter
  silently returns fewer than k results.
- Pre-filtering with high-selectivity filters can be slow on HNSW; check the
  engine's guidance.
- Store the text or a pointer to it; you will need to re-embed and to show snippets.

## Decision 4 — Tenancy

| Model | Isolation |
|---|---|
| one collection, tenant in payload | weakest, filter must be enforced everywhere |
| collection per tenant | stronger, many collections to manage |
| namespace/partition per tenant | balance, engine-dependent |
| database/cluster per tenant | strongest, most expensive |

- Enforce the tenant filter in the data-access layer, never by trusting the caller's
  query.
- Test cross-tenant leakage as a first-class test case.

## Decision 5 — Writes and deletes

- Upsert by content hash + document id; deletion by document id must remove all its
  chunks.
- Deletes are often deferred/async — verify the vector is actually gone before
  claiming deletion.
- Versioning: keep the embedding model id on each vector to make migration and
  audit possible.
- Snapshot/backup strategy: a rebuilt index from source text is preferable to
  backing up vectors, if ingestion is fast.

## Failure modes at scale

- Post-filter dropping results: "top 5" often returns 2.
- One collection, tenant filter forgotten in a new code path; data leaks.
- HNSW index in RAM exceeding the node size; OOM under load.
- Deleted documents still returned weeks later because deletes were queued.
- Recall degraded after an index rebuild with default parameters.

## Verification receipts

1. Engine choice with the capability that justified a new datastore.
2. Recall@k measured against exact search on a sample.
3. Filter selectivity test: filtered queries still return k results.
4. Cross-tenant test proving isolation.
5. Delete verification: document removed from every chunk and result.
