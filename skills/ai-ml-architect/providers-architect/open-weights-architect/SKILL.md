---
name: open-weights-architect
description: Architect-level design with open-weight models — choosing a family and size, licence and redistribution constraints, the difference between base and instruct tuning, hosting on vLLM/Ollama, and the fine-tuning and eval work that makes an open model competitive for a narrow task. Use when data must not leave your boundary or per-token cost must collapse.
license: MIT
compatibility: Llama, Qwen, Mistral, DeepSeek, Gemma; vLLM, Ollama, llama.cpp
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/providers-architect/open-weights-architect
  crusor-origin: original
  crusor-sources: "huggingface.co/docs; docs.vllm.ai; github.com/ggml-org/llama.cpp; ollama.com/docs"
  crusor-triggers: "open weights, llama, qwen, mistral, self hosted llm, ollama, llama.cpp, model licence, local model, gptq, awq"
  crusor-verified-on: "2026-10-30"
---

# Open-Weights Architect

An open model is **a dependency you now operate**. The licence, the quantisation,
and the serving stack are all architecture decisions you own permanently.

## When to use

- Data cannot leave your infrastructure or jurisdiction.
- Volume makes per-token pricing untenable and utilisation is high.
- A narrow task where a fine-tuned small model beats a frontier prompt.

## When NOT to use

- Low or spiky volume — an idle GPU costs more than the API.
- The task needs frontier reasoning and your evals show open models trailing.

## Decision 1 — Family and licence

| Licence shape | Implication |
|---|---|
| permissive (Apache/MIT) | commercial use, redistribution, least review |
| community (custom terms) | usage caps, naming/attribution clauses, legal review |
| research-only | unusable for production |

- Check the licence **before** the eval, not after a month of tuning.
- Note the acceptable-use clauses; some forbid security, medical, or surveillance
  use cases your product may serve.
- Record the exact model revision (hash) you ship — "Llama 3" is not a version.

## Decision 2 — Size and quantisation

| Quantisation | Effect |
|---|---|
| FP16/BF16 | reference quality, most memory |
| FP8 | near-reference, ~half memory |
| 4-bit (AWQ/GPTQ) | 2–4× cheaper, measurable quality loss |
| GGUF q4/q5 | laptop/CPU serving, further loss |

- Always re-run the eval suite after quantising; the loss is task-dependent.
- Choose the smallest model that clears the threshold — quality per GPU-hour is the
  metric that matters.

## Decision 3 — Serving

- vLLM/TGI for production throughput: continuous batching, paged KV cache, prefix
  caching.
- llama.cpp/Ollama for local development, desktop apps, and CPU-only environments.
- Keep one serving stack in production; two doubles the operational surface.
- Model load time is minutes — keep warm replicas and drain before replacing
  (`inference-serving-architect`).
- Pin the tokenizer and chat template with the model; a mismatched template silently
  degrades quality.

## Decision 4 — Adaptation

- Prompt and retrieval first; fine-tuning only for format, tone, and narrow domain
  behaviour.
- LoRA/QLoRA for cheap iteration; merge for serving simplicity when done.
- Your data licence must permit training use — check before the first run.
- Hold out an eval set that never appears in training; contamination is the default
  failure.

## Decision 5 — Operations

- GPU inventory, driver/CUDA versions, and the exact container image are part of the
  deployment artefact.
- Model artefacts stored in your registry with a checksum; no runtime downloads
  from the internet in production.
- Safety: open models ship less alignment — add output filtering and refusal
  behaviour yourself (`guardrails-architect`).
- Upgrade path: new model → eval → shadow → canary → fleet.

## Failure modes at scale

- Community licence with a 700 M monthly-user clause discovered at legal review.
- 4-bit quantisation shipped without evals; 8% accuracy drop in production.
- Chat template copy-pasted from a different revision; outputs subtly worse.
- One GPU, no warm replica; every deploy is a two-minute outage.
- Fine-tune trained on eval data; scores excellent, product unusable.

## Verification receipts

1. Licence review recorded with the clauses that matter.
2. Eval comparison: base vs quantised vs fine-tuned, on the same set.
3. Throughput and cost per 1M tokens on your hardware.
4. Model revision hash pinned in the deployment manifest.
5. Upgrade path exercised on a canary replica.
