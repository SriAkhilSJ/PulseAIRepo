---
name: llm-app-architect
description: Architect-level LLM application design — prompt and context architecture, structured output contracts, tool calling, model routing across tiers, caching, streaming, and the fallback chain that keeps a product alive when a provider degrades. Use when building a product feature directly on top of a foundation model API.
license: MIT
compatibility: OpenAI, Anthropic, Gemini, open-weight models via vLLM/Ollama
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/llm-app-architect
  crusor-origin: original
  crusor-sources: "platform.openai.com/docs/guides; docs.anthropic.com/en/docs; ai.google.dev/gemini-api/docs"
  crusor-triggers: "prompt engineering, structured output, json mode, function calling, tool use, model routing, streaming, token budget, llm api, chatbot, assistant, copilot"
  crusor-verified-on: "2026-10-30"
---

# LLM App Architect

The application is **a contract around a probabilistic function**: input schema in,
validated output out, with cost, latency and failure all bounded by design.

## When to use

- A product feature calls a foundation model directly.
- Designing prompts, output formats, tool use, or model routing.
- An existing LLM feature is unreliable, slow, or expensive.

## When NOT to use

- The answer must be grounded in a private corpus → `rag-architect` first.
- Nothing measures correctness yet → `evals-architect` first.

## Decision 1 — Prompt architecture

| Layer | Contains | Changes |
|---|---|---|
| system | role, rules, output contract | rarely, versioned |
| task template | the instruction, slots | per feature |
| context | retrieved docs, user state | per request |
| history | turns, trimmed | per session |

- Prompts are **code**: in version control, reviewed, diffed, with the eval score
  attached to each change.
- Put invariants in the system prompt; put data in the context block, clearly
  delimited, and instruct the model to treat it as data, not instructions.
- Never interpolate untrusted text into the instruction region — that is prompt
  injection by construction.

## Decision 2 — Output contracts

- Prefer a schema the provider enforces (JSON mode / structured outputs) over
  "reply in JSON".
- Validate server-side against the schema (zod/pydantic); on failure, one repair
  attempt, then a typed error to the caller.
- Keep outputs small: ask for the field you need, not a paragraph you will parse.
- Every enum you accept has a defined behaviour for the value the model invents.

## Decision 3 — Model routing

- Cheap/fast tier for classification, extraction, routing, summarisation.
- Strong tier for reasoning, code, and anything user-visible where quality is
  contractual.
- Route by task class and, optionally, by a difficulty classifier — not by hope.
- Pin model versions in config; an unpinned `latest` is an untested dependency
  upgrade.

## Decision 4 — Context and tokens

- Budget tokens per request: system + context + history + output ≤ window.
- Trim history by recency and relevance, not by truncation mid-sentence.
- Long inputs: chunk, summarise hierarchically, or retrieve — do not paste.
- Cache what is stable (system prompt, large shared context) where the provider
  supports prompt caching; cache results by input hash for repeats.

## Decision 5 — Failure and cost control

- Timeouts per call, shorter than the caller's patience; retries with jitter on
  429/5xx only.
- Fallback chain: primary → secondary model → degraded deterministic path. Test
  it by forcing failures.
- Per-request and per-tenant token budgets; hard caps, not alerts after the fact.
- Stream where time-to-first-token matters; do not stream when the caller needs
  a validated object.

## Failure modes at scale

- Two hops chained, each 1.5 s p95, advertised as a 1.5 s feature.
- A prompt edit that fixed one example and broke forty others, shipped blind.
- Model returns valid JSON with semantically wrong field names.
- Provider outage surfaces as a raw exception in the UI.
- Context grows every turn until the window silently truncates the system prompt.

## Verification receipts

1. Prompt files versioned, with the eval delta for each change.
2. Schemas enforced and validated; repair path exercised.
3. Cost and p95 per request at projected volume, per model tier.
4. Fallback chain triggered in a test and observed by the caller.
5. Token budget enforced with a hard cap, verified by a deliberately oversized request.
