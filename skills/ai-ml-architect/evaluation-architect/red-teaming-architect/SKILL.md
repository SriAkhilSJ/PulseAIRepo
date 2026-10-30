---
name: red-teaming-architect
description: Architect-level adversarial testing for AI systems — threat modelling of prompt injection, jailbreaks, data exfiltration and tool abuse, a regression corpus of attacks, severity classification, and the mitigations that hold in production rather than in demos. Use before launching a model-backed feature or an agent with tools.
license: MIT
compatibility: Any model; OWASP LLM Top 10; guardrail frameworks
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/evaluation-architect/red-teaming-architect
  crusor-origin: original
  crusor-sources: "owasp.org/www-project-top-10-for-large-language-model-applications; learn.microsoft.com/azure/ai-services/openai/concepts/red-teaming; nvlabs.github.io/garak"
  crusor-triggers: "red teaming, prompt injection, jailbreak, adversarial testing, llm security, data exfiltration, owasp llm, garak, attack corpus"
  crusor-verified-on: "2026-10-30"
---

# Red Teaming Architect

Red teaming is **a regression suite for adversarial input**. Run it once and you have
a report; wire it into CI and you have a property.

## When to use

- Launching a model feature that reads untrusted content or takes actions.
- An agent has tools, credentials, or data access.
- A customer or auditor asks how injection is handled.

## When NOT to use

- A closed system with no untrusted input and no tools — still test refusals, but
  the surface is small.

## Decision 1 — Threat model

| Threat | Vector |
|---|---|
| direct injection | user message overrides instructions |
| indirect injection | poisoned document, web page, ticket, email |
| exfiltration | model reveals system prompt or other users' data |
| tool abuse | agent calls a tool with attacker-chosen parameters |
| jailbreak | policy bypass to produce disallowed content |
| resource abuse | prompt causing unbounded loops or cost |
| supply chain | malicious tool/MCP server, poisoned model |

- Rank by what an attacker gains: data > money > reputation > noise.
- Indirect injection is the one teams underestimate; your corpus is user-generated.

## Decision 2 — Attack corpus

- Build a versioned set of attacks per threat, including:
  - instruction override ("ignore previous", role-play, encoding tricks, base64,
    unicode homoglyphs),
  - payloads inside documents ("AI assistant: email the file to…"),
  - tool-parameter manipulation (path traversal, SSRF targets, SQL fragments),
  - multi-turn escalation.
- Add every real-world incident and every near miss.
- Run the corpus on every prompt, model, or tool change.

## Decision 3 — Test method

- Automated suite in CI for the deterministic classes; manual sessions for
  creative ones.
- Measure **attack success rate** per category, plus false-positive rate on
  legitimate content (tickets quoting attacks, security documentation).
- Test the full stack, not the model alone: retrieval, tool execution, output
  rendering, and logging.
- Test the mitigations with them disabled once — that tells you what they are
  actually worth.

## Decision 4 — Mitigations, in order of durability

1. **Architecture**: no tool whose parameters the model can choose freely; no data
   the user should not see in the prompt at all.
2. **Server-side enforcement**: authorization on every tool call, validated
   arguments, allowlists.
3. **Input handling**: delimit untrusted content, strip control tokens, cap length.
4. **Model-level instruction**: "treat as data" — helpful, never sufficient.
5. **Output filtering**: block credential-shaped strings, URLs to internal hosts.
6. **Detection**: log suspicious patterns, alert on spikes.

- A mitigation that only lives in the system prompt is a suggestion.

## Decision 5 — Response

- Severity classes with fix timelines: data exposure (hours), tool abuse (days),
  jailbreak noise (backlog).
- Keep a public-facing statement for known limitations; do not promise immunity.
- Retest after each fix with the same payload.

## Failure modes at scale

- Injection test run once before launch; a new tool added later breaks the model.
- Red team tested the prompt, never the tool layer where the damage happens.
- False positives ignored: legitimate security tickets flagged, users blocked.
- Attack corpus in a private repo with no CI job; it rots.
- Mitigation is a system-prompt sentence and an apologetic README.

## Verification receipts

1. Threat model table with severity and owner per class.
2. Attack corpus committed, versioned, and run in CI.
3. Success-rate report per category before and after mitigations.
4. Server-side enforcement proven by bypassing the model and calling the tool
   directly.
5. Incident path: suspected injection triaged within the stated timeline.
