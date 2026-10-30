---
name: inference-serving-architect
description: Architect-level model serving design — API versus self-host economics, GPU capacity and utilisation, batching and scheduling, latency budgets with time-to-first-token, quantisation and model size trade-offs, and the autoscaling and draining behaviour that keeps a serving fleet honest. Use when models must serve production traffic at a stated latency and cost.
license: MIT
compatibility: vLLM, TGI, TensorRT-LLM, Triton, SageMaker, Bedrock, Vertex
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/inference-serving-architect
  crusor-origin: original
  crusor-sources: "docs.vllm.ai; huggingface.co/docs/text-generation-inference; docs.nvidia.com/tensorrt-llm"
  crusor-triggers: "inference, model serving, gpu, vllm, throughput, batching, quantization, latency, time to first token, autoscaling, self host, gpu bill, gpu cost, token cost"
  crusor-verified-on: "2026-10-30"
---

# Inference Serving Architect

Serving is **a queueing problem with expensive servers**. Utilisation, batching
and latency are three views of the same decision.

## When to use

- Serving self-hosted models, or deciding whether to.
- Latency or cost of an API-based feature must come down.
- Building a shared inference platform for multiple products.

## When NOT to use

- Low, spiky volume where a provider API is cheaper than an idle GPU.
- The bottleneck is retrieval or prompt design, not the model runtime.

## Decision 1 — API or self-host

| Factor | Favours API | Favours self-host |
|---|---|---|
| volume | low, spiky | sustained, predictable |
| data | public or vendor-approved | must not leave the boundary |
| models | frontier, changing | open-weight, pinned |
| team | no ML infra staff | has serving expertise |
| cost | per-token is fine | high utilisation amortises GPUs |

Break-even is arithmetic: monthly tokens ÷ throughput per GPU versus GPU price.
Under ~30% sustained utilisation, self-hosting usually loses.

## Decision 2 — Sizing the model

- Parameters set quality ceiling; quantisation (FP8/INT8/AWQ) buys speed and
  memory at a small quality cost — measure it on your eval set, do not assume.
- KV cache, not weights, is what runs out first under concurrency: context length
  × concurrent requests is the real memory budget.
- Prefer the smallest model that clears the eval threshold; scale up only on
  measured failure.

## Decision 3 — Latency budget

- Decompose: queue wait + prefill (TTFT) + decode (tokens/s) + network.
- TTFT matters for streaming UX; total time matters for tool calls and pipelines.
- Output tokens dominate decode time — constrain length, then measure again.
- Set SLOs at p95 with a stated concurrency, since latency is a function of load.

## Decision 4 — Throughput mechanics

- Continuous batching is the baseline; static batching wastes the GPU.
- Paged attention / KV-cache management determines how many concurrent sequences
  fit.
- Prefix caching helps when many requests share a system prompt.
- Replicas behind a queue-aware router beat round-robin: send to the least-loaded
  instance, and shed load rather than blow past the SLO.
- Autoscale on queue depth and TTFT, not CPU/GPU utilisation — utilisation is
  already high.

## Decision 5 — Operations

- Warm pools to absorb cold starts; a cold GPU takes minutes to become useful.
- Draining: stop accepting, finish in-flight sequences, then terminate.
- Rollouts by canary with eval-gated promotion; keep the previous model resident
  for instant rollback.
- Multi-tenant isolation: per-tenant quotas and max sequence limits, or one tenant
  monopolises the batch.
- Metering per request for chargeback and capacity planning.

## Failure modes at scale

- GPU fleet at 20% utilisation because the model was oversized.
- p95 collapse when a long-context request enters the batch.
- Autoscaler reacting to CPU while the queue grows.
- Quantised model shipped without re-running evals.
- One tenant's 100k-token prompts starving everyone else.

## Verification receipts

1. Load test at projected concurrency: TTFT, tokens/s, p95, queue depth.
2. Cost per 1M output tokens, self-host versus API at current utilisation.
3. Quantisation eval delta against the full-precision baseline.
4. Canary rollout and rollback rehearsed with a resident previous model.
5. Per-tenant quota enforced and demonstrated under a burst.
