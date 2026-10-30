---
name: structured-output-architect
description: Architect-level design of model output contracts — schema-first modelling, provider-enforced JSON versus prompted JSON, validation and repair loops, streaming partial objects, tool-call arguments as structured output, and the failure taxonomy that turns malformed responses into typed errors. Use when a program must consume what a model returns.
license: MIT
compatibility: OpenAI strict schemas, Anthropic tool schemas, Gemini responseSchema, Pydantic/zod
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/llm-architect/structured-output-architect
  crusor-origin: original
  crusor-sources: "platform.openai.com/docs/guides/structured-outputs; docs.anthropic.com/en/docs/build-with-claude/tool-use; ai.google.dev/gemini-api/docs/structured-output"
  crusor-triggers: "structured output, json schema, json mode, response schema, pydantic, zod, parsing llm output, repair loop, function schema"
  crusor-verified-on: "2026-10-30"
---

# Structured Output Architect

Structured output is **an interface contract with a stochastic implementation**.
Treat it like any untrusted input boundary: enforce, validate, and fail in a typed
way.

## When to use

- A program consumes model output (extraction, classification, routing, tool args).
- Existing parsing is regex over prose.
- You need streaming with partial objects.

## When NOT to use

- The output is prose for a human — then the contract is length and tone, not
  schema.

## Decision 1 — Schema first

| Rule | Why |
|---|---|
| required fields, `additionalProperties: false` | optionality invites omission |
| enums for closed sets | free strings drift |
| nullable required fields over optional | "missing" and "null" differ |
| small and flat where possible | deep nesting increases error rate |
| no free-text blobs inside structure | they defeat the point |

- Derive the schema from your domain types (zod/Pydantic) so one source is truth
  for contract and validation.
- Numeric constraints (min/max, integer) are part of the schema, not prompt prose.

## Decision 2 — Enforcement level

| Approach | Guarantee |
|---|---|
| provider-enforced schema | valid JSON shape, not semantic truth |
| tool-call arguments | same, with the tool contract |
| prompted JSON | best effort; parse failures expected |
| free text + regex | fragile; avoid |

- Prefer provider enforcement; validate against the same schema server-side anyway.
- Enforcement guarantees shape, never correctness: a valid object can hold the
  wrong id.

## Decision 3 — Validation and repair

```
model output → schema validation → pass: proceed
                                 → fail: one repair attempt with the error message
                                        → fail again: typed error to caller
```

- Repair prompts include the validation error and the original output; do not
  re-ask blindly.
- Exactly one repair attempt — loops amplify cost and mask a schema that is too
  complex.
- Distinct error types: `ModelFormatError`, `SchemaViolation`, `SemanticMiss` —
  metrics per type.

## Decision 4 — Streaming

- Stream tokens for UX, but only emit structured events when the object completes,
  or stream a line-delimited record per item.
- Partial JSON parsing needs a tolerant parser; do not render incomplete objects as
  if final.
- If the UI needs progressive output, prefer an array of small objects over one
  large object.

## Decision 5 — Semantics beyond shape

- Validate business rules after parsing: dates in range, ids exist, totals reconcile.
- Cross-field checks (start < end, sum matches lines) catch what schema cannot.
- For extraction, require the source span for each field; a field without a span is
  not auditable.

## Failure modes at scale

- Regex parsing of prose; a formatting change silently zeroes a metric.
- Schema with nested optionals; 15% of responses missing the key field.
- Repair loop retrying five times; latency triples, cost quadruples.
- Valid JSON with an id from another tenant, accepted because it parsed.
- Streaming partial JSON rendered as final in the UI, confusing users.

## Verification receipts

1. Schema committed, shared by prompt, validator, and types.
2. Malformed-response test: typed error surfaced, no crash.
3. Repair path exercised and bounded to one attempt.
4. Business-rule validation tests after parsing.
5. Format-error rate monitored per model and prompt version.
