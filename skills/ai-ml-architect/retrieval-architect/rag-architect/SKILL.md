---
name: rag-architect
description: Architect-level retrieval-augmented generation design — chunking and parsing strategy, embedding and index choice, hybrid search and reranking, citation and grounding contracts, freshness and re-indexing, and the retrieval evals that separate real grounding from plausible text. Use when answers must come from a private corpus.
license: MIT
compatibility: pgvector, Qdrant, Weaviate, OpenSearch, Pinecone
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/retrieval-architect/rag-architect
  crusor-origin: original
  crusor-sources: "arxiv.org/abs/2005.11401; github.com/pgvector/pgvector; docs.llamaindex.ai"
  crusor-triggers: "rag, retrieval, vector database, embedding, chunking, semantic search, reranking, hybrid search, knowledge base, citations, pgvector, hallucination, hallucinating, grounding, make things up, makes things up"
  crusor-verified-on: "2026-10-30"
---

# RAG Architect

Retrieval quality is **the ceiling on answer quality**. A perfect model over bad
chunks produces confident nonsense.

## When to use

- Answers must be grounded in a defined corpus (docs, tickets, contracts, code).
- The knowledge changes and cannot live in weights.
- Answers must cite sources for trust or audit.

## When NOT to use

- The corpus fits comfortably in a cached context window and changes rarely —
  paste it and skip the retrieval system.
- The question requires reasoning over the whole corpus at once (aggregation) —
  that is a query engine problem, not a similarity problem.

## Decision 1 — Pipeline stages, each measurable

```
ingest → parse → chunk → embed → index → retrieve → rerank → assemble → generate
                                    ↑                                   ↑
                            retrieval evals                     answer evals
```

Every stage has an owner and a metric. Most RAG failures are parse and chunk
failures wearing a model costume.

## Decision 2 — Parsing and chunking

| Corpus | Approach |
|---|---|
| PDFs | layout-aware parser, keep tables as tables |
| HTML docs | strip nav, keep heading hierarchy |
| code | function/class boundaries, keep signatures |
| tickets/chat | one thread, resolved state first |
| spreadsheets | row-group chunks with headers attached |

- Chunk by semantic boundary, 300–800 tokens, with 10–20% overlap.
- Carry metadata on every chunk: source, section, timestamp, tenant, permissions.
- Never embed a chunk you cannot cite back to an exact location.

## Decision 3 — Embedding and index

- One embedding model per index; changing it means a full re-index — plan the
  migration before you need it.
- Dimension and distance metric are architectural constants; document them.
- Vector store choice by operational fit: pgvector if you already run Postgres
  and the corpus is modest; a dedicated store when scale, filtering, or hybrid
  search demand it.
- Metadata filters are part of the query contract: tenant, permission, freshness,
  document type.

## Decision 4 — Retrieve well

- **Hybrid**: BM25/keyword + dense vectors, fused (RRF). Exact terms, IDs and
  names fail pure-vector search.
- Retrieve 20–50 candidates, rerank with a cross-encoder to the top 5–8.
- Query rewriting for conversational input; decompose multi-part questions.
- No results is a valid outcome: answer "I don't know" rather than filling the
  gap.

## Decision 5 — Grounding contract

- Every claim maps to a chunk id; render citations with source and location.
- Assembly: put the strongest chunks first, delimit them as data, and instruct
  the model to refuse when the context does not contain the answer.
- Permission filtering happens **before** retrieval results enter the prompt —
  never rely on the model to redact.

## Decision 6 — Freshness and re-indexing

- Ingestion is a pipeline with idempotent upserts keyed by content hash.
- Deletes propagate: a removed document must disappear from the index, or it will
  be cited forever.
- Re-embedding runs as a background migration into a new collection, then a swap.
- Track index lag; a stale index is a correctness bug with a delay.

## Failure modes at scale

- Chunks split mid-table; the model reads half a price list.
- Pure vector search missing an exact error code the user pasted.
- Citations generated from memory of the prompt rather than returned metadata.
- Tenant leakage through a missing metadata filter.
- Deleting a source document that keeps appearing in answers.

## Verification receipts

1. Retrieval eval: recall@k and MRR on a labelled question set.
2. Answer eval: groundedness and citation accuracy, judged against the corpus.
3. Chunk inspector screenshot for one hard document (tables, headings intact).
4. Permission test: a query from tenant B never returns tenant A chunks.
5. Delete test: removed document no longer retrievable, verified by query.
