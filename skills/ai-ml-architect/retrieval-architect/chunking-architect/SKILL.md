---
name: chunking-architect
description: Architect-level ingestion and chunking design — document parsing per format, chunk boundaries and size, overlap, parent-child and hierarchical chunking, metadata that survives to the answer, and the table and code cases that break naive splitters. Use when retrieval quality depends on how documents were cut up.
license: MIT
compatibility: Any stack; layout-aware parsers, dbt-style pipelines
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/retrieval-architect/chunking-architect
  crusor-origin: original
  crusor-sources: "unstructured.io/docs; llamaindex.ai/llama-index; docs.llamaindex.ai"
  crusor-triggers: "chunking, document parsing, chunk size, overlap, parent document, rag ingestion, table extraction, layout parser, garbled, pdf extraction, chunks, chunk quality"
  crusor-verified-on: "2026-10-30"
---

# Chunking Architect

Chunking is **the retrieval system's data model**. No model recovers an answer that
was split across two chunks and never retrieved together.

## When to use

- Ingesting PDFs, HTML, tickets, code, or spreadsheets for retrieval.
- Retrieval returns plausible-but-wrong passages.
- Tables, headers, or code blocks come back mangled.

## When NOT to use

- The corpus is already structured records (use SQL filtering).
- Documents fit whole in context and there are few of them.

## Decision 1 — Parse before you chunk

| Format | Requirement |
|---|---|
| PDF | layout-aware parser; keep reading order, tables, headings |
| HTML | strip nav/boilerplate, preserve heading hierarchy |
| DOCX/MD | headings and lists survive as structure |
| spreadsheets | header row repeated with each row group |
| code | split at function/class boundaries, keep signatures |
| tickets/chat | whole thread, resolved state first |

- Bad parsing is the leading cause of bad RAG; inspect parsed text before tuning
  chunk size.
- Store the parse artefact (and parser version) so re-chunking does not re-parse.

## Decision 2 — Boundaries and size

| Parameter | Typical |
|---|---|
| chunk size | 300–800 tokens |
| overlap | 10–20% |
| max chunk | never exceed the embedding model's limit |
| min chunk | drop or merge below ~50 tokens |

- Prefer semantic boundaries (headings, sections, functions) over fixed windows; use
  fixed windows only inside long prose.
- Overlap exists to protect boundary-spanning answers, not to double the index.
- Measure: percentage of chunks that start mid-sentence is a parsing signal.

## Decision 3 — Structure that helps retrieval

- **Parent-child**: embed small chunks, retrieve the parent section for the model.
  This is usually the biggest single quality win.
- **Hierarchical summaries**: a chunk index with document/section summaries for
  routing queries to the right area.
- **Context headers**: prepend "Document › Section" to each chunk so the embedding
  carries its location.
- **Sliding windows** for dense reference material where the answer may straddle a
  boundary.

## Decision 4 — Metadata

- Every chunk carries: source id, URL/path, section, page/lines, timestamp,
  permissions, language, parser version.
- Citations render from metadata, never from the model's recollection.
- Permission metadata is filtered before retrieval, not after generation.
- Keep the raw text pointer so you can re-render a snippet without re-fetching.

## Decision 5 — Special cases

- Tables: keep the header with the chunk; a row without its header is meaningless.
- Code: keep imports/signature with the body; language tag in metadata.
- Legal/medical: clause or section boundaries matter more than token counts.
- Multi-column PDFs: parser must produce correct reading order or answers will be
  scrambled.

## Failure modes at scale

- Fixed 512-token windows over a PDF with 6-column tables; nothing retrievable.
- Chunk equals a whole 40-page document; embeddings average everything to noise.
- Overlap of 50%; index doubles and duplicates dominate the top-k.
- Citations generated from the prompt, pointing at the wrong page.
- Re-chunking requires re-parsing 200k documents because the parse was not stored.

## Verification receipts

1. Parsed-text sample per format, inspected by a human.
2. Chunk statistics: size distribution, overlap, mid-sentence starts.
3. Retrieval eval comparing at least two chunking strategies.
4. Citation accuracy checked against source pages.
5. Re-chunk run executed from stored parse artefacts.
