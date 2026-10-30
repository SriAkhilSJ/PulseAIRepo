---
name: ai-ml-architect
description: Entry point for AI/ML system architecture — choosing between prompting, retrieval, fine-tuning and training; deciding where the model boundary sits; costing and gating inference; and the evaluation discipline that must exist before any of it ships. Use when planning an LLM product, a RAG system, an agent, a model serving stack, or an ML platform.
license: MIT
compatibility: Any provider or self-hosted stack
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect
  crusor-origin: original
  crusor-sources: "platform.openai.com/docs; docs.anthropic.com; huggingface.co/docs; arxiv.org/abs/2005.11401"
  crusor-triggers: "llm, rag, fine tune, embedding, prompt, agent, inference, model serving, mlops, eval, vector database, training"
  crusor-verified-on: "2026-10-30"
---

# AI/ML Architect

The model is **a dependency with non-determinism, latency variance, a price per
token, and a quality contract you must measure**. Everything in this domain
follows from treating it that way.

## The shelf

| Question | Book |
|---|---|
| where does the model boundary sit, what is the cost and quality envelope? | this file |
| prompting, context, structured output, tools, fallbacks | `llm-app-architect` |
| retrieval quality, chunking, embeddings, vector store | `rag-architect` |
| how do we know it works? golden sets, judges, regression gates | `evals-architect` |
| latency, throughput, GPUs, batching, self-host vs API | `inference-serving-architect` |
| training pipelines, feature stores, registries, monitoring drift | `mlops-architect` |
| multi-step autonomy, tools, memory, guardrails, cost control | `agent-architect` |

Read the crown, then the one or two books the plan actually needs. Do not read
the whole shelf to avoid a decision.

## When to use

- Any plan that puts a model in the request path of a product.
- Choosing between API, self-host, fine-tune, or classic ML.
- An existing AI feature that is expensive, slow, or unmeasurable.

## When NOT to use

- Deterministic logic solves it: rules, SQL, a regex, a lookup table.
- The task is "add a chatbot" with no defined job to be done.
- Nobody can state what a correct answer looks like — that is an eval problem
  first (`evals-architect`), not an architecture problem.

## Decision 1 — Is a model the right tool

| Signal | Better answer |
|---|---|
| exact, auditable rule | deterministic code |
| classification over known labels | classic ML or a small model |
| free-form text transformation | LLM |
| answer must cite a fixed corpus | retrieval, not memory |
| high-volume, narrow format | fine-tune or smaller model |
| truly open-ended reasoning | large model, with evals |

Non-determinism is a product decision: anything user-visible must have a stated
tolerance for variance and a human path when confidence is low.

## Decision 2 — Where the boundary sits

- **Prompt-only** — fastest to ship, no training, weakest on format stability.
- **Retrieval** — grounds answers in your data; adds a retrieval system to own.
- **Fine-tune** — buys format and tone, not knowledge; needs a dataset and an
  eval set, plus retraining as a lifecycle.
- **Train from scratch** — rarely justified outside a domain with proprietary
  data and volume.
- Escalate in that order. Each step adds a system you must operate.

## Decision 3 — The envelope

Every design doc states, numerically:

- quality: eval score on the golden set, and the floor below which it is a
  regression;
- latency: p50/p95 end to end, including every model call in a chain;
- cost: per request, per user, per month at projected volume;
- failure: what the user sees when the provider is down or rate-limits.

A chain of five model calls multiplies all four. Count the hops.

## Decision 4 — Data and privacy

- What leaves your boundary, to whom, under which retention terms.
- PII in prompts is a data-flow decision, not a prompt-engineering one.
- Tenant isolation: do not mix documents across tenants in one index.
- Logging prompts is logging user content — apply the same retention rules.

## Decision 5 — Build order

1. Define the job and the golden set.
2. Baseline: best prompt on the largest model. Measure.
3. Add retrieval or a smaller model only where the baseline fails.
4. Add evals to CI before adding features.
5. Optimise cost and latency against a measured baseline, never by guessing.

## Failure modes at scale

- Shipping without an eval set: quality debates settled by vibes.
- Fine-tuning to teach facts that retrieval should supply.
- Prompt chains whose cost and p95 were never summed.
- One provider, no fallback, no timeout, no budget cap.
- "It works" demonstrated with three cherry-picked examples.

## Verification receipts

1. Job statement plus a golden set with expected outputs.
2. Baseline eval score, and the regression floor.
3. Cost and latency model per request at projected volume.
4. Data-flow diagram: what leaves the boundary and under what terms.
5. Fallback behaviour verified by simulating a provider outage.
