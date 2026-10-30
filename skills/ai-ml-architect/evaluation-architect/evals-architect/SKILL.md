---
name: evals-architect
description: Architect-level evaluation design for AI systems — golden sets and their maintenance, deterministic checks versus model-as-judge, regression gates in CI, online signals, and the failure taxonomy that tells you which change broke quality. Use before shipping any model-backed feature and whenever quality is debated.
license: MIT
compatibility: Any provider; pytest + promptfoo/braintrust style harnesses
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/evaluation-architect/evals-architect
  crusor-origin: original
  crusor-sources: "arxiv.org/abs/2306.05685; platform.openai.com/docs/guides/evaluation; hamel.dev"
  crusor-triggers: "eval, evaluation, golden set, model as judge, llm judge, regression testing, benchmark, accuracy, quality gate, hallucination, regression gate"
  crusor-verified-on: "2026-10-30"
---

# Evals Architect

Without evals, every AI decision is **an opinion with a deploy button**. Evals
turn quality into a number that can regress, and therefore into something a test
suite can protect.

## When to use

- Before shipping any model-backed feature.
- A prompt, model, retrieval, or fine-tune change is proposed.
- Users report quality issues and nobody can reproduce them.

## When NOT to use

- Deterministic code with a normal test suite — that is just testing.
- You have no users and no idea of the job yet — write the job statement first.

## Decision 1 — The eval set

- 50–200 cases to start, drawn from real traffic and known failures.
- Every case: input, expected output or a rubric, and the metadata needed to
  reproduce it.
- Include the boring cases, the hard cases, and the known-bad ones.
- Stratify by category so a score can tell you *where* you regressed, not just
  that you did.
- Version the set; growing it is a change with its own review.

## Decision 2 — Grading method

| Check | Use for |
|---|---|
| exact / schema match | structured extraction, routing, enums |
| unit assertions | numbers, IDs, citations present |
| rubric by judge model | open-ended prose, helpfulness, tone |
| human review | calibrating the judge, disputes, high-stakes samples |

- Prefer deterministic checks; use a judge only where nothing else fits.
- Judge prompts need their own validation: score a set of human-labelled examples
  and report agreement before trusting the judge.
- Judges should return structured verdicts with a reason, not a bare score.
- Watch for judge bias: position, verbosity, and self-preference — randomise
  order and swap candidates.

## Decision 3 — Metrics that mean something

- Report per category, plus the aggregate; a single number hides the damage.
- Pass rate with a confidence interval, not a bare percentage on 20 cases.
- Track cost and latency alongside quality — a "better" model that triples p95 is
  a product decision.
- Hallucination/groundedness is measured against sources, not against vibes.

## Decision 4 — Gates in CI

- Any prompt, model, retrieval config, or fine-tune change runs the eval suite.
- Fail the build on regression beyond a stated threshold per category.
- Store results per commit; a quality trend line beats a single green check.
- Keep a cheap smoke eval for PRs and the full suite for merges/nightly.

## Decision 5 — Online signals

- Thumbs, copy, edit-rate, retry-rate, escalation-to-human — the behaviours that
  mean the answer was not good enough.
- Sample and label production traffic continuously; that is where the next eval
  cases come from.
- Alert on drift in output distribution — length, refusal rate, format failures.
- A/B tests need an eval-backed hypothesis, not just a vibe shift.

## Failure modes at scale

- Evals written by the model author, judging the model author's prompt.
- A suite that only contains the examples the feature was built on.
- Judge scoring 90% while human review says 60%.
- Regression found by users a week after merge.
- The eval set frozen at launch; the product drifted, the tests did not.

## Verification receipts

1. Eval set committed with cases, rubrics, and a version.
2. Judge validated against human labels with reported agreement.
3. CI gate demonstrated: a deliberately worse prompt fails the build.
4. Baseline scores per category, with the threshold for regression.
5. Online signal dashboard with one alert routed to the owning team.
