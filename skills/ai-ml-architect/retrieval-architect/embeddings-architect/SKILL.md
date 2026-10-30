---
name: embeddings-architect
description: Architect-level embedding design — model choice and dimensionality, domain fit versus general benchmarks, normalisation and distance metrics, multilingual and code embeddings, versioning and re-embedding migrations, and the cost model of embedding a corpus repeatedly. Use when vectors must represent your content.
license: MIT
compatibility: OpenAI, Voyage, Cohere, BGE/E5, sentence-transformers
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/retrieval-architect/embeddings-architect
  crusor-origin: original
  crusor-sources: "platform.openai.com/docs/guides/embeddings; huggingface.co/spaces/mteb/leaderboard; sbert.net"
  crusor-triggers: "embeddings, embedding model, vector dimensions, cosine similarity, mteb, sentence transformers, multilingual embeddings, re-embed"
  crusor-verified-on: "2026-10-30"
---

# Embeddings Architect

An embedding is **a lossy projection tuned for a distribution**. Choosing one is a
retrieval-quality decision, and changing one is a migration.

## When to use

- Building semantic search, clustering, deduplication, or RAG retrieval.
- Retrieval quality is poor and chunking is already sane.
- Adding a new language or a code corpus.

## When NOT to use

- Exact-match search over identifiers — use keyword/BM25.
- Fewer than a few thousand items where reranking over raw text is feasible.

## Decision 1 — Model choice

| Need | Choice |
|---|---|
| general English, managed | a current provider embedding model |
| multilingual | models trained on parallel corpora; verify per language |
| code | code-aware embeddings; test on symbol search |
| fully local / private | open sentence-transformer family |
| low latency, high volume | smaller dimension model + reranking |

- Benchmark on **your** queries and documents: retrieval evals, not MTEB rank.
- Bigger dimensions are not better; they cost memory and search time linearly.

## Decision 2 — Mechanics

- Normalise vectors and fix one distance metric (cosine is the safe default) —
  mixing metrics silently degrades results.
- Store the model id and version with every vector; mixed vectors in one index are a
  correctness bug.
- Truncate inputs to the model's max tokens deliberately; silent truncation loses
  the end of long documents.
- Batch requests; embedding calls are cheap but latency-bound when serialised.

## Decision 3 — Domains that break

| Content | Watch for |
|---|---|
| legal/medical jargon | general models miss the terminology; test and consider a fine-tuned model |
| short queries vs long docs | asymmetric models or query prefixes |
| tables and numbers | embeddings ignore structure; keep metadata filters |
| code | identifiers vs semantics; combine with keyword |
| non-English | check per language, not on average |

## Decision 4 — Versioning and migration

- Treat the embedding model as a schema version: `index_v2_<model>`.
- Re-embedding a corpus costs money and time; estimate before committing (tokens ×
  corpus size).
- Dual-write and compare during migration: query both indexes on a sample, choose
  by eval, then swap.
- Never mix old and new vectors in one collection to "save a re-index".

## Decision 5 — Cost

- Embedding is cheap per token but the corpus × re-runs add up; store the source
  text so you can re-embed without re-ingesting.
- Cache query embeddings for repeated queries.
- Deduplicate near-identical documents before embedding.

## Failure modes at scale

- Model upgraded in place; half the index is v1, half v2, recall collapses.
- Metric changed from cosine to dot product without re-normalising.
- Long documents truncated at 512 tokens; the answer-bearing section never embedded.
- Multilingual launch with an English-only model; non-English recall near zero.
- Re-embedding a 40M-document corpus in a weekend window that did not exist.

## Verification receipts

1. Embedding model, dimension, metric, and normalisation recorded.
2. Retrieval eval (recall@k, MRR) on a labelled query set per language.
3. Truncation analysis: percentage of documents cut at the token limit.
4. Migration plan with cost and dual-read comparison.
5. Query-embedding cache hit rate.
