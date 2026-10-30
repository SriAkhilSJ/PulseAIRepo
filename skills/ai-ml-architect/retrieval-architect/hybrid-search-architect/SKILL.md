---
name: hybrid-search-architect
description: Architect-level hybrid retrieval — when keyword search beats vectors, fusing BM25 with dense results (RRF and weighted), reranking with cross-encoders, query rewriting and decomposition, and the evaluation that shows each stage earning its latency. Use when semantic search alone misses exact terms or identifiers.
license: MIT
compatibility: OpenSearch/Elasticsearch, Qdrant, Weaviate, pgvector + tsvector
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/retrieval-architect/hybrid-search-architect
  crusor-origin: original
  crusor-sources: "opensearch.org/docs/latest/search-plugins; weaviate.io/developers/weaviate/search/hybrid; qdrant.tech/documentation/concepts/hybrid-queries"
  crusor-triggers: "hybrid search, bm25, keyword search, reranking, cross encoder, reciprocal rank fusion, query rewriting, search relevance, misses exact, exact match search, search misses, identifier search"
  crusor-verified-on: "2026-10-30"
---

# Hybrid Search Architect

Dense search finds **meaning**; keyword search finds **strings**. Real queries need
both, and a reranker decides which result actually answers.

## When to use

- Users paste identifiers, error codes, product SKUs, or names.
- Semantic search returns "related" documents that miss the exact clause.
- Multi-language or jargon-heavy corpora.

## When NOT to use

- Purely conversational queries over a small corpus where dense alone clears the
  eval.
- No labelled queries yet — build 50 before adding stages.

## Decision 1 — Signal mix

| Query type | Best first stage |
|---|---|
| natural question | dense |
| exact code/ID/name | keyword/BM25 |
| mixed (most real queries) | both, fused |
| long document as query | dense + decomposition |

- Run both retrievers, then fuse; do not pick one by intuition.
- Keep the lexical index fresh — stale keyword indexes cause "no results" for new
  content.

## Decision 2 — Fusion

- RRF (reciprocal rank fusion) is the robust default: rank-based, no score
  calibration needed across engines.
- Weighted score fusion needs normalised scores; normalisation shifts with corpus
  size and silently degrades.
- Retrieve deep (k=50–100 per retriever) before fusing; a shallow candidate pool
  cannot be fixed by fusing.
- Deduplicate by document/chunk id before reranking.

## Decision 3 — Reranking

- Cross-encoder rerank of top 30–50 to top 5–8 is the highest-value stage after
  chunking.
- Rerankers are latency-heavy: batch, cap candidates, and consider a smaller model
  for the first pass.
- Score thresholds beat fixed top-k for "no good answer" detection.
- Measure the reranker's contribution: hit-rate before and after, on the same
  candidates.

## Decision 4 — Query understanding

- Rewrite conversational queries into standalone ones (carry pronouns forward).
- Decompose multi-part questions into sub-queries, retrieve separately, then
  synthesise.
- Expand acronyms and synonyms where the domain is known; do not let an LLM rewrite
  silently drop constraints.
- Preserve filters through rewriting: a date range must survive the rewrite.

## Decision 5 — Evaluation and operations

- Metrics per stage: recall@50 (retrieval), nDCG@8 (rerank), groundedness (answer).
- Keep a labelled query set with expected documents; grow it from failures.
- Latency budget per stage; if fusion adds 200 ms and 1% relevance, say no.
- Log the query, filters, and selected ids for offline analysis.

## Failure modes at scale

- BM25 index updated weekly; new documents invisible for days.
- Fusion weights tuned on 20 queries, overfitting to noise.
- Reranker applied to 500 candidates; p95 latency doubles for no gain.
- Query rewrite dropping "in 2024", answers from the wrong year.
- No "no answer" path; the top result is always returned regardless of score.

## Verification receipts

1. Per-stage eval table: recall, nDCG, groundedness.
2. Latency breakdown per stage at p50/p95.
3. Exact-identifier queries returning the right document.
4. Threshold behaviour: an unanswerable query returns "no answer".
5. Fusion/reranker configuration recorded with the eval that justified it.
