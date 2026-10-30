---
name: anthropic-architect
description: Architect-level design on Claude's API — Messages as the primitive, system prompts and long-context use, tool use and its result loop, extended thinking and its cost, prompt caching economics, and the safety and refusal behaviour a product must handle rather than fight. Use when the product calls Claude.
license: MIT
compatibility: Anthropic API, Claude models, MCP
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/providers-architect/anthropic-architect
  crusor-origin: original
  crusor-sources: "docs.anthropic.com/en/api/messages; docs.anthropic.com/en/docs/build-with-claude/tool-use; docs.anthropic.com/en/docs/build-with-claude/prompt-caching"
  crusor-triggers: "anthropic, claude, messages api, extended thinking, prompt caching, claude tool use, long context, sonnet, opus"
  crusor-verified-on: "2026-10-30"
---

# Anthropic / Claude Architect

Claude's shape is **one Messages endpoint, explicit content blocks, and a strong
system-prompt contract**. Design around blocks and caching, not around one giant
string.

## When to use

- The product uses Claude, or needs long-context document work.
- Tool-heavy agents where a clean tool-result loop matters.
- Cost-sensitive long prompts that can use prompt caching.

## When NOT to use

- Vendor-neutral planning → `model-selection-architect`.
- Strict JSON-schema enforcement at the API level is a hard requirement — check the
  current support before committing.

## Decision 1 — Shape of the call

- `system` holds the stable contract; `messages` hold the turn. Do not stuff the
  system prompt into the first user turn.
- Content is a list of blocks: text, images, documents, tool_use, tool_result.
  Treat blocks as the data model, not strings you concatenate.
- `max_tokens` is required: set it to the real ceiling, not the model maximum.
- `stop_sequences` when you drive a format; the model still needs validation.

## Decision 2 — Tools

```
user turn → assistant returns tool_use block(s)
         → you execute → user turn with tool_result block(s)
         → assistant continues
```

- Tool results are user-role blocks keyed by `tool_use_id`; mismatched ids are a
  silent failure.
- Return errors as `is_error: true` results so the model can recover, not as
  exceptions.
- Bound the loop with a step counter and a token budget (`agent-architect`).
- Tool definitions are prompts: name, description, and schema quality decide
  reliability.

## Decision 3 — Extended thinking

- Use it for multi-step reasoning, planning, and hard debugging; skip it for
  extraction and classification.
- Thinking tokens are billed and slow the response; budget them explicitly.
- Do not parse reasoning as output; the answer is in the content blocks.
- For agents, thinking plus tools multiplies latency — measure p95 per step.

## Decision 4 — Caching

- Cache breakpoints on stable prefixes: system prompt, tool definitions, large
  documents. Order matters — everything before a breakpoint must be identical.
- Cache writes cost more, reads cost much less: it pays off only when the prefix is
  reused within the TTL.
- Do not cache per-user content; the point is shared, stable context.
- Measure cache hit rate; a 0% hit rate means your prefix is changing every call.

## Decision 5 — Long context and documents

- Put long documents before the question, with clear delimiters and an instruction
  to treat them as data.
- For very large corpora, retrieval beats pasting; long context is a tool, not an
  architecture.
- Summarise or chunk when reuse is limited — you pay for every token on every call.

## Decision 6 — Refusals and safety

- Handle refusals as a product path: explain, offer an alternative, escalate to a
  human — do not retry-loop a refusal.
- Do not attempt to prompt around safety behaviour; design the feature so the
  refusal is rare and legitimate.
- Log refusal rates by category; a spike means the prompt or the product changed.

## Failure modes at scale

- Cache breakpoint after a per-request timestamp; hit rate 0, bill 3×.
- `max_tokens` at model maximum for a one-line answer; higher cost and latency.
- Tool loop with no cap, exceeding the context window mid-task.
- Thinking enabled for a classification endpoint, p95 up 4×.
- Refusals surfaced as HTTP 500 to users.

## Verification receipts

1. Message shape documented: system, blocks, max_tokens, stop reasons.
2. Tool loop traced end to end with a failing tool and recovery.
3. Cache hit-rate dashboard with the prefix layout that produced it.
4. Latency and cost per endpoint, with and without thinking.
5. Refusal handling tested with a deliberately disallowed request.
