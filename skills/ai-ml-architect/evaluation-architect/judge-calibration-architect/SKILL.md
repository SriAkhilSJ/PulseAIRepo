---
name: judge-calibration-architect
description: Architect-level LLM-as-judge design — rubric construction, pairwise versus absolute scoring, agreement measurement against human labels, position and verbosity bias controls, sampling and cost, and the drift monitoring that keeps a judge trustworthy over time. Use when automated grading decides whether a model change ships.
license: MIT
compatibility: Any judge model; any eval harness
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/evaluation-architect/judge-calibration-architect
  crusor-origin: original
  crusor-sources: "arxiv.org/abs/2306.05685; arxiv.org/abs/2305.17926; platform.openai.com/docs/guides/evaluation"
  crusor-triggers: "llm as judge, judge model, rubric scoring, pairwise evaluation, judge bias, human agreement, grading rubric, evaluator model"
  crusor-verified-on: "2026-10-30"
---

# Judge Calibration Architect

An unvalidated judge is **a random number generator with a confident tone**. Before
you trust it to gate releases, measure how often it agrees with a human.

## When to use

- Automated grading of open-ended output (helpfulness, tone, groundedness).
- Comparing two model or prompt variants at volume.
- Human review is too slow or too expensive for every case.

## When NOT to use

- Deterministic criteria exist (schema, exact match, unit tests) — use those.
- The stakes require human sign-off — the judge becomes a triage filter, not the
  decision.

## Decision 1 — Mode

| Mode | Use | Cost |
|---|---|---|
| absolute score (1–5) | trend tracking, bucketing | 1 call |
| rubric checklist | partial credit, auditability | 1 call |
| pairwise A vs B | comparing variants | 1 call per pair |
| pointwise with rationale | debugging why | 1 call |

- Pairwise is more reliable than absolute for "which is better" decisions.
- Rubric checklists with per-criterion verdicts are the easiest to audit and debug.
- Always request structured output with a reason (`structured-output-architect`).

## Decision 2 — Rubric design

- Criteria are observable behaviours, not adjectives: "cites a source id for each
  factual claim" beats "is accurate".
- 3–6 criteria; more and the judge starts averaging.
- Provide 1–2 anchor examples per score level.
- Explicit "insufficient information" option — forced choice manufactures noise.

## Decision 3 — Bias controls

| Bias | Control |
|---|---|
| position | randomise A/B order, run both orders and average |
| verbosity | length-normalise or instruct to ignore length |
| self-preference | do not use the model under test as judge |
| style | judge blind to model identity |
| anchoring | score each item independently, no batching context leakage |

- Where a rubric criterion can be checked programmatically, do that instead.

## Decision 4 — Validation

- Label 100–200 examples by humans; compare judge verdicts to human verdicts.
- Report agreement (raw and Cohen's kappa) per criterion, not only overall.
- Target: agreement high enough that judge failures do not dominate your false
  positives. If kappa is low, the rubric is ambiguous — fix it before scaling.
- Re-validate when the judge model changes or the prompt is edited.

## Decision 5 — Operations

- Judge version pinned and recorded with every eval run.
- Judge cost included in the eval budget; sample when the suite grows.
- Drift monitor: human spot-checks weekly; agreement trend tracked.
- Disagreement queue feeds rubric improvements and new golden cases.

## Failure modes at scale

- Judge agrees with humans 62% of the time, used as a release gate.
- Judge prompt says "rate quality 1–10", no rubric; scores clustered at 8.
- The model under test also being the judge; new model always wins.
- Position bias: variant B wins 70% of the time regardless of content.
- Judge silently changed model version; scores jump 15% with no product change.

## Verification receipts

1. Rubric with criteria, anchors, and an "insufficient information" path.
2. Agreement report against human labels, per criterion.
3. Bias test: swapped-order runs produce consistent winners.
4. Judge version recorded in every eval result.
5. Weekly human spot-check process with the current agreement trend.
