---
name: fine-tuning-architect
description: Architect-level fine-tuning design — when tuning beats prompting or retrieval, dataset construction and deduplication, LoRA versus full tuning, hyperparameters that matter, overfitting and catastrophic forgetting, and the eval and rollback story a tuned model needs. Use when a model must reliably produce a format, tone, or narrow behaviour.
license: MIT
compatibility: OpenAI/Anthropic tuning, LoRA/QLoRA, Axolotl, Unsloth
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/training-architect/fine-tuning-architect
  crusor-origin: original
  crusor-sources: "platform.openai.com/docs/guides/fine-tuning; huggingface.co/docs/peft; arxiv.org/abs/2106.09685"
  crusor-triggers: "fine tuning, finetune, lora, qlora, peft, training data, overfitting, catastrophic forgetting, custom model, sft"
  crusor-verified-on: "2026-10-30"
---

# Fine-Tuning Architect

Fine-tuning buys **behaviour, not knowledge**. If you are teaching facts, you want
retrieval; if you are teaching a format or a house style, you are in the right book.

## When to use

- Output format or tone must be consistent at high volume.
- A narrow classification/extraction task where a small tuned model beats prompting.
- Latency or cost demands a smaller model with task-specific behaviour.

## When NOT to use

- The model does not know your facts → retrieval.
- The prompt already passes evals — tuning adds a maintenance burden for nothing.
- Fewer than a few hundred good examples.

## Decision 1 — Method

| Method | Fit |
|---|---|
| prompting + few-shot | baseline, always try first |
| RAG | knowledge grounding |
| LoRA / QLoRA | most production tuning, cheap iteration |
| full fine-tune | large datasets, deep behaviour change, own hardware |
| distillation | shrink a large model's behaviour into a small one |

- Establish the prompt baseline and record its score; tuning without a baseline
  cannot be shown to help.

## Decision 2 — Dataset

- 500–5,000 high-quality examples beat 100k noisy ones.
- Every example: input, ideal output, and the reason it is ideal (for review).
- Deduplicate near-identical examples; duplicates teach memorisation.
- Balance across categories; imbalance becomes the model's default behaviour.
- Hold out an eval set that never appears in training, and check for leakage
  (same document, paraphrased).
- Include refusal/abstain examples if the product needs them.

## Decision 3 — Hyperparameters that matter

| Parameter | Effect |
|---|---|
| learning rate | too high = forgetting, too low = no learning |
| epochs | 1–3 typical; more = memorisation |
| LoRA rank/alpha | capacity; higher is not better |
| batch size | stability; scale LR with it |
| sequence length | truncated examples teach truncated behaviour |

- Train on the real prompt format including system prompt and delimiters; a
  mismatch at inference is the most common silent regression.

## Decision 4 — Evaluation and risks

- Evaluate tuned vs baseline on: your task eval, a general capability sample
  (regression), and refusal behaviour.
- Watch catastrophic forgetting: a tuned model that is great at the task and worse
  at everything else is usually a bad trade.
- Test on adversarial and edge inputs, not just in-distribution.
- Version the model, dataset, and hyperparameters together; a model without its
  dataset id is not reproducible.

## Decision 5 — Lifecycle

- Retraining triggers: new data volume, quality drift, format changes.
- Deployment: shadow → canary → full, with eval gates (`evals-architect`).
- Rollback to the previous tuned model and to the base prompt path.
- Cost model: training runs plus the serving cost of the tuned model.

## Failure modes at scale

- Trained on production logs including the bug being fixed.
- Eval set contaminated by training data; scores perfect, product unchanged.
- Tuned for JSON format when structured outputs would have solved it for free.
- Prompt changed after training; the tuned model is now off-distribution.
- Base model deprecated by the provider; retraining all adapters from scratch.

## Verification receipts

1. Prompt baseline score recorded before tuning.
2. Dataset card: size, sources, dedup, licence, splits.
3. Eval comparison: tuned vs baseline, task and general capability.
4. Inference prompt matches training format, verified by diff.
5. Rollback to the base model path exercised.
