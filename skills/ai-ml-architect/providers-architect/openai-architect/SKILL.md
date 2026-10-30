---
name: openai-architect
description: Architect-level design on OpenAI's API — model tiers and what each is for, Responses versus Chat Completions semantics, structured outputs and strict schemas, tool calling and its loop, batch and file APIs, and the rate-limit and organisation structure that decides production behaviour. Use when the product calls OpenAI.
license: MIT
compatibility: OpenAI API (Responses, Chat Completions, Batch, Realtime)
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/providers-architect/openai-architect
  crusor-origin: original
  crusor-sources: "platform.openai.com/docs/guides; platform.openai.com/docs/guides/structured-outputs; platform.openai.com/docs/guides/batch"
  crusor-triggers: "openai, gpt, chat completions, responses api, openai batch, openai rate limits, json schema mode, o3, gpt-5"
  crusor-verified-on: "2026-10-30"
---

# OpenAI Architect

OpenAI's surface is **a small set of primitives with strict-schema options**. Use
the strict path and the failure surface shrinks to cost and latency.

## When to use

- The product already standardises on OpenAI or needs its ecosystem.
- Structured extraction where schema enforcement matters.
- High-volume offline work suited to the batch API.

## When NOT to use

- Data residency or vendor policy forbids it → `open-weights-architect`.
- Model comparison across vendors → `model-selection-architect` first.

## Decision 1 — Endpoint

| Need | Endpoint |
|---|---|
| new server-side app | Responses API |
| legacy integration, many SDKs | Chat Completions |
| millions of offline requests | Batch API (cost, 24 h window) |
| live voice/streaming both ways | Realtime |
| embeddings | Embeddings API |

- Responses gives you server-side state and tool orchestration; Chat Completions
  is the compatibility path. Do not mix in one codebase without a reason.
- Batch is roughly half price for non-interactive work — the wrong choice only if
  you need the answer now.

## Decision 2 — Model tiering

- Cheap tier for routing, classification, extraction, summarisation.
- Reasoning tier for multi-step maths, code, and agentic loops — it is slower and
  bills more tokens, including reasoning tokens.
- Route by task class in config, pinned to a dated model id; never `latest`.
- Re-run the eval suite on every model change (`evals-architect`).

## Decision 3 — Structured output

- Use strict structured outputs with a JSON schema, not "reply in JSON".
- Schemas: required fields, `additionalProperties: false`, enums for closed sets.
- Optionality is expensive — prefer a `null`-able required field over a missing
  one.
- Validate server-side anyway; on failure, one repair call, then a typed error.

## Decision 4 — Limits and organisation

- Rate limits are per organisation/project and per model: separate projects per
  environment so a staging load test cannot starve production.
- Set per-project spend limits and alert thresholds; a runaway loop is billed.
- Retry 429/5xx with jittered backoff; respect `Retry-After`.
- Usage/cost reporting by project and by feature tag where available.

## Decision 5 — Data handling

- Confirm retention and training terms for the tier you use; zero-retention
  arrangements differ per endpoint.
- Redact PII before sending where the product requires it.
- Log prompts only under the same policy as user content; store hashes for
  correlation if full text is not allowed.

## Failure modes at scale

- Model id float to `latest`; behaviour changes under you on a Tuesday.
- Strict schema avoided, so 2% of responses fail parsing in production.
- One project shared by dev and prod; staging load test triggers 429s for users.
- Reasoning model used for a classification task; cost up 10×, latency 5×.
- Batch chosen for a user-facing feature that then "takes up to 24 h".

## Verification receipts

1. Endpoint choice per feature, with the reason recorded.
2. Eval score per pinned model id, with the regression threshold.
3. Schema validation test with a deliberately invalid model response.
4. Rate-limit behaviour demonstrated with an induced 429.
5. Cost report per project and feature for the last 30 days.
