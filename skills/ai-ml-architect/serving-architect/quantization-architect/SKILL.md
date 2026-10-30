---
name: quantization-architect
description: Architect-level model compression decisions — precision formats (FP16/BF16/FP8/INT8/4-bit), which quantisation method fits which hardware, where quality actually degrades, calibration data, and the eval protocol that decides whether a compressed model may ship. Use when memory or latency must come down.
license: MIT
compatibility: GPTQ, AWQ, bitsandbytes, TensorRT-LLM, GGUF, ONNX Runtime
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/serving-architect/quantization-architect
  crusor-origin: original
  crusor-sources: "arxiv.org/abs/2210.17323; arxiv.org/abs/2306.00978; docs.nvidia.com/tensorrt-llm"
  crusor-triggers: "quantization, int8, fp8, 4 bit, gptq, awq, gguf, model compression, distillation, pruning, smaller model"
  crusor-verified-on: "2026-10-30"
---

# Quantisation Architect

Quantisation is **a memory-for-quality trade with a measurable exchange rate**.
Choose the rate on your evals, never on a blog post.

## When to use

- The model does not fit, or fits with no room for concurrency.
- Latency or cost per token must fall on fixed hardware.
- Deploying to edge, mobile, or CPU-only environments.

## When NOT to use

- A smaller base model already clears the eval bar — that is simpler than
  compressing a large one.
- Quality is already borderline; compression makes it worse, not cheaper.

## Decision 1 — Format

| Format | Where it fits |
|---|---|
| BF16 | training default, best quality |
| FP16 | inference on older GPUs |
| FP8 | modern GPUs (H100-class), minimal loss |
| INT8 (SmoothQuant/LLM.int8) | broad support, small loss |
| 4-bit (AWQ/GPTQ) | memory-bound serving, measurable loss |
| GGUF q4/q5 | CPU/laptop/edge |

- Weight-only 4-bit saves memory but can slow token generation on some kernels;
  measure throughput, not just size.
- KV-cache quantisation compounds the savings and the risk — evaluate separately.

## Decision 2 — Method

- Post-training quantisation (PTQ) first: no retraining, fast, usually enough.
- Calibration data must be **representative of production inputs** — random text
  calibrates badly and hides failures.
- Quantisation-aware training (QAT) when PTQ loses too much and you own training.
- Do not quantise the output/embedding heads carelessly; those are sensitive.

## Decision 3 — Where quality degrades

| Capability | Typical sensitivity |
|---|---|
| format adherence / JSON | high — breaks silently |
| arithmetic and counting | high |
| long-context retrieval in prompt | medium |
| general prose | low |
| classification with clear features | low |

- Test the capabilities your product depends on, at production context lengths.
- Format compliance regressions are the most common and least visible failure.

## Decision 4 — Evaluation protocol

1. Baseline (BF16) on the full eval set: task score, format-validity rate, p95
   latency, tokens/s.
2. Quantised candidate on the same set, same prompts, same decoding parameters.
3. Accept only if the delta is inside the stated tolerance; otherwise try 8-bit or
   a smaller model.
4. Re-test at production context length and with real batching.

## Decision 5 — Deployment

- Ship quantised artefacts with the method, calibration dataset id, and eval report
  attached to the model version.
- Keep the unquantised model available for rollback and for debugging quality
  issues.
- Pin the serving runtime version; kernel support for a format changes between
  releases.
- Measure end-to-end: lower memory with higher latency is a net loss.

## Failure modes at scale

- 4-bit shipped on a JSON-heavy endpoint; 6% of responses stop parsing.
- Calibration with the eval set; scores look great, production differs.
- Quantised weights with a runtime lacking the optimised kernel; slower than FP16.
- KV cache quantised silently by a config default.
- No unquantised baseline retained; a quality complaint cannot be investigated.

## Verification receipts

1. Format and method chosen, with the quality/memory exchange rate measured.
2. Eval table: task score, format validity, latency, throughput — baseline versus
   quantised.
3. Calibration dataset description and size.
4. Runtime and kernel versions pinned with the artefact.
5. Rollback to BF16 exercised.
