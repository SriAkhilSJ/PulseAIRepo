---
name: gemini-architect
description: Architect-level design on Google's Gemini API — multimodal inputs as the default, long-context use, function calling, grounding with search, context caching, and the quota and safety-setting model that differs from OpenAI-style APIs. Use when the product calls Gemini or needs native multimodal and very long context.
license: MIT
compatibility: Gemini API, Vertex AI, Gemini models
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/providers-architect/gemini-architect
  crusor-origin: original
  crusor-sources: "ai.google.dev/gemini-api/docs; cloud.google.com/vertex-ai/generative-ai/docs; ai.google.dev/gemini-api/docs/caching"
  crusor-triggers: "gemini, google ai, vertex ai, multimodal llm, context caching, google model, grounding, gemini api"
  crusor-verified-on: "2026-10-30"
---

# Gemini Architect

Gemini's differentiator is **native multimodality and very long context**. Design
for what only it does well; otherwise the choice is a pricing question.

## When to use

- Native video, audio, image and PDF understanding in one call.
- Very long documents or codebases in a single context.
- Grounding answers in Google Search or an enterprise corpus.

## When NOT to use

- Data must stay in another cloud, or the org standardises elsewhere.
- Pure text extraction where a cheaper model clears the eval bar.

## Decision 1 — Surface

| Surface | Use |
|---|---|
| Gemini API (AI Studio keys) | prototyping, small products |
| Vertex AI | enterprise, VPC, IAM, quotas, data residency |
| Gemini on-device / Nano | offline or privacy-critical mobile features |

- Production on Vertex gives you IAM, audit logs, and org quotas; API keys alone
  are a prototyping path.
- Region choice decides data residency — pick before launch, not after review.

## Decision 2 — Multimodal inputs

- Send files by reference where the API supports uploads (Files API) instead of
  base64 in every request.
- Video and audio are tokenised by duration — cost scales with length, so sample
  frames/segments for long media.
- Prompt the modality explicitly: what to look at, what to ignore, what format to
  return.
- Validate that the modality actually improves the eval; image understanding is
  expensive and easy to over-trust.

## Decision 3 — Long context

- Long context is not free retrieval: cost and latency grow with input tokens, and
  "lost in the middle" effects still apply.
- Put the instruction after the document, with a delimiter contract.
- For repeat queries over the same large corpus, use context caching rather than
  re-sending; it changes the cost model entirely.
- Beyond a few documents, retrieval with citations is the better architecture
  (`rag-architect`).

## Decision 4 — Tools and grounding

- Function calling schemas are prompts: precise names and descriptions beat a long
  tool list.
- Grounding with Search returns citations — surface them, do not paraphrase them
  away.
- Enterprise grounding against your own index keeps data in your perimeter.
- Bound tool loops; a multimodal agent can burn quota fast.

## Decision 5 — Safety and quotas

- Safety settings are per-category thresholds; the default blocks some legitimate
  product content (medical, security, news). Calibrate and document, do not
  disable.
- Quotas are per project and per model; request increases before launch.
- Rate limits surface as 429 with retry metadata — backoff with jitter.
- Log safety-filter reasons by category to distinguish "blocked" from "model
  failed".

## Failure modes at scale

- Whole 2-hour video sent per request; bill and latency both unacceptable.
- API key in a mobile client.
- Safety thresholds at default, blocking security content the product exists to
  discuss.
- Long context used instead of retrieval; cost per query 40× the alternative.
- Quota increase requested on launch day.

## Verification receipts

1. Surface and region choice documented with residency rationale.
2. Multimodal eval vs text-only baseline on the same task.
3. Token and cost per request for the media lengths you actually accept.
4. Safety calibration table: category, threshold, justification.
5. Quota request filed and approved before launch.
