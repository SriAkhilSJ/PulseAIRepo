---
name: prompting-architect
description: Architect-level prompt design — layering system, task and data regions, instruction precision and delimiters, few-shot selection, chain-of-thought versus direct answers, versioning and review, and the injection-resistant structures that keep untrusted text from becoming instructions. Use when a prompt is a production artefact.
license: MIT
compatibility: Any model or provider
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/llm-architect/prompting-architect
  crusor-origin: original
  crusor-sources: "docs.anthropic.com/en/docs/build-with-claude/prompt-engineering; platform.openai.com/docs/guides/prompt-engineering; learnprompting.org"
  crusor-triggers: "prompt engineering, system prompt, few shot, chain of thought, prompt injection, prompt template, prompt versioning, delimiters"
  crusor-verified-on: "2026-10-30"
---

# Prompting Architect

A prompt is **source code that ships to a probabilistic interpreter**. It needs
version control, review, tests, and a structure that separates instructions from
data.

## When to use

- Any model-backed feature, before tuning anything else.
- Prompts that grew by accretion and now contradict themselves.
- A prompt-injection or jailbreak concern.

## When NOT to use

- The failure is retrieval quality or missing context (`rag-architect`).
- The task needs format guarantees — use structured output, not a better prompt.

## Decision 1 — Structure

```
[system]   role, rules, output contract, refusal policy — stable, versioned
[task]     the specific instruction with slots — changes per feature
[data]     delimited, labelled, explicitly "data, not instructions"
[examples] optional, few-shot, minimal
[request]  the actual question, last
```

- Instructions before data, question after data — models attend to the end.
- Fixed delimiters (`<doc>…</doc>`, fenced blocks) with a rule that content inside
  is data.
- One prompt, one job. Two jobs in one prompt produce a model that half-does both.

## Decision 2 — Instruction quality

- Be specific about *what* and *how much*: length, format, audience, exclusions.
- State the refusal case: "if the documents do not contain the answer, say you
  don't know".
- Positive instructions ("cite the source id") beat negative ones ("don't make
  things up") — the negative needs a positive replacement.
- Remove contradictions; contradictory prompts produce variance that looks like
  model flakiness.

## Decision 3 — Few-shot and reasoning

- 3–8 examples, chosen to cover edge cases and format, not to be exhaustive.
- Balanced examples: if every example says yes, the model says yes.
- Chain-of-thought for multi-step reasoning; skip it for extraction where it
  mostly adds tokens.
- Ask for the reasoning in a structured field when it must be auditable, not in
  free prose you then parse.

## Decision 4 — Injection resistance

- Treat all user and retrieved content as untrusted; never interpolate it into the
  system region.
- Delimit and label; instruct the model to ignore instructions found inside data.
- Do not rely on the model alone: enforce permissions in code, validate tool calls
  server-side (`agent-architect`).
- Test with known payloads ("ignore previous instructions…"), including base64 and
  unicode tricks.

## Decision 5 — Lifecycle

- Prompts in files, in version control, reviewed; not strings in a controller.
- Each change runs the eval suite (`evals-architect`); attach the delta to the PR.
- Version the prompt id with the model id in logs, so a regression is traceable to
  a change.
- Keep the previous prompt deployable — rollback is a config change, not a code
  revert when possible.

## Failure modes at scale

- Prompt that grew to 3,000 tokens with four sections contradicting each other.
- User text concatenated into the system prompt; injection succeeds on day one.
- Few-shot examples all one shape; the model fails on a common edge case.
- Prompt edited in the dashboard, no version, no eval, no record of who changed it.
- `temperature` raised to "make it more creative" on an extraction endpoint.

## Verification receipts

1. Prompt file with layering visible and a version id.
2. Eval score attached to the current prompt version.
3. Injection test suite run against the current prompt.
4. Log line showing prompt version + model id per request.
5. Rollback to the previous prompt version exercised.
