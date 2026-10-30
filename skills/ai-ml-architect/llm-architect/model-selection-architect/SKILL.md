---
name: model-selection-architect
description: Architect-level model choice — turning product requirements into constraints (quality floor, latency, cost, context, data boundary), benchmarking candidates on your own eval set, the difference between capability and fit, and the routing strategy that uses more than one model deliberately. Use when choosing between models.
license: MIT
compatibility: Any provider; any open-weight family
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/llm-architect/model-selection-architect
  crusor-origin: original
  crusor-sources: "artificialanalysis.ai; lmarena.ai; huggingface.co/open-llm-leaderboard"
  crusor-triggers: "model selection, which model, benchmark, leaderboard, model comparison, routing models, model tier, capability eval"
  crusor-verified-on: "2026-10-30"
---

# Model Selection Architect

Model choice is **a constraint-satisfaction problem, not a leaderboard lookup**.
Public benchmarks measure tasks that are not yours.

## When to use

- Starting a feature that needs a model.
- Costs or latency require a smaller model.
- A new model release claims to be better.

## When NOT to use

- You have no eval set yet — build one first (`evals-architect`).
- The task is deterministic and does not need a model.

## Decision 1 — Constraints first

| Constraint | Question |
|---|---|
| quality floor | what score must it beat on our eval? |
| latency | p95 budget for the user-visible action |
| cost | maximum per request / per month |
| context | how much input must fit |
| modality | text only, or image/audio/video |
| data boundary | may data leave our infrastructure? |
| licence | does redistribution or use match our product? |

Write these down before looking at any model. Otherwise you will choose by vibes
and rationalise afterwards.

## Decision 2 — Benchmark on your set

- 50–200 real cases from your product, stratified by task type.
- Include the ugly ones: long inputs, ambiguous asks, refused topics.
- Report per-category scores plus cost and p95 latency — three numbers per
  candidate.
- Leaderboard scores are a filter for "worth testing", never a decision.
- Re-run the comparison quarterly; the frontier moves.

## Decision 3 — Capability versus fit

| Pattern | Real cause |
|---|---|
| great on benchmarks, poor on ours | distribution mismatch |
| good answers, unusable format | needs structured output |
| good quality, too slow | wrong tier |
| good quality, too costly | over-provisioned model |
| fine at 100 examples, breaks at 10k | context or retrieval limits |

- A smaller model plus better retrieval often beats a larger model plus bad
  context.
- Fine-tuning buys format and consistency, rarely knowledge.

## Decision 4 — Multi-model routing

- Cheap tier for classification, extraction, and routing decisions.
- Strong tier for reasoning and user-visible final answers.
- Route by task class in config; optionally by a difficulty classifier, but
  evaluate the classifier itself.
- Fallback model per tier with the same output contract; test the fallback path.
- Never route on price alone: a wrong cheap answer costs more than the tokens saved.

## Decision 5 — Lock-in and drift

- Abstract the provider behind an internal interface; keep the adapter thin.
- Pin model versions; treat upgrades as changes with eval gates.
- Track provider deprecation notices; an unannounced sunset is an outage.
- Keep an exit path tested at least once: one feature running on the secondary
  provider.

## Failure modes at scale

- Model chosen from a leaderboard, eval set built afterwards to match.
- Cost per request measured, cost per successful outcome never measured.
- Upgrade to a new model with no eval; quality drops in one category only.
- Two providers used opportunistically per feature; nobody owns either contract.
- Fallback model exists in config, has never been called, and is broken.

## Verification receipts

1. Constraint table with numbers, agreed before evaluation.
2. Candidate comparison: score, p95, cost per request, per category.
3. Decision recorded with the trade-off accepted.
4. Fallback path exercised by forcing a primary failure.
5. Provider abstraction with one feature successfully switched.
