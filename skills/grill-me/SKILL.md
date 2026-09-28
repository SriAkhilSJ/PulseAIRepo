---
name: grill-me
description: "Stress-test a plan with structured adversarial questioning."
version: 1.1.0
author: Hermes Agent (adapted from mattpocock/skills + obra), ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [planning, review, requirements, alignment, adversarial, interview]
    related_skills: [subagent-driven-development, requesting-code-review]
---

**Triggers:** grill, stress test my plan, stress-test, interview my plan, challenge my plan, poke holes, question my plan, before we build, plan review

# Grill Me

Stress-tests a plan through structured adversarial questioning **before any code is written**. Model the plan as a **design tree** — every decision branches into the decisions hanging off it — and interview the user in rounds until every branch is resolved and nothing is silently assumed. Pairs naturally with Crusor's **Plan mode** (plan first, grill it, then execute).

## When to Use

- User says "grill me", "stress test this idea", "interview my plan"
- Before complex work: auth flows, schema changes, migrations, payments, API contracts
- A plan has unresolved decisions or seems vague
- Before decomposing into subagents (`subagent-driven-development`)

Do NOT use for reviewing existing code (use `requesting-code-review`) or simple one-off tasks.

## Core Mechanic: Frontier Rounds

The **frontier** is every decision whose prerequisites are already settled — the questions you can ask NOW without guessing answers you haven't heard. Work in **rounds**: ask the whole current frontier in one message, numbered, each with your recommended answer. Then wait.

A question whose answer depends on another question still open belongs to a LATER round — never ask it early.

```
❓ Q1 — Token storage: cookie or localStorage?
➡️ Recommendation: httpOnly cookie — XSS-resistant, we already have the middleware.

❓ Q2 — Session revocation strategy: denylist or rotate-on-use?
➡️ Recommendation: rotate-on-use; no new state, matches the existing refresh flow.
```

Each answer reshapes the tree: settled decisions push the frontier outward and unblock dependents. Recompute and ask the next round.

**Facts are your job; decisions are the user's.** When a question needs a fact from the environment, find it yourself with `search_files` / `read_file` / `run_terminal` — or delegate heavy exploration via `delegate_to_subagent`. Never ask the user anything you could look up. Don't block the whole interview on one exploration; only its downstream questions wait.

## Question Coverage

**Understanding** — the real goal and boundaries: actual objective? what's explicitly IN and OUT of scope? constraints (time, tech, budget)? who are the users?

**Technical decisions** — for each architectural choice: "Why this and not X?" "What happens if Y fails?" "Worst case?" "How do we roll back?" Cross-reference the existing codebase; if the project already has a pattern, call it out.

**Edge cases** — "What if the user does Z?" "What if volume is 100x?" "Security implications?"

## Synthesis (when the frontier is empty)

1. Summarize ALL decisions in bullet points
2. List anything left open, and what is explicitly OUT of scope
3. Ask: "Aligned? Should I start implementing, or adjust anything?"

Do not act on the plan until the user confirms shared understanding.

## Pitfalls

1. **Out-of-dependency-order questions** — a question depending on an unanswered one is a guess wearing a question mark.
2. **Skipping the codebase** — look facts up in code; don't ask the user.
3. **Accepting "I don't know"** — offer options, explain trade-offs, recommend one.
4. **Writing code during interrogation** — alignment only; code after the explicit green light.
5. **Being too agreeable** — your job is finding problems. If everything looks fine, look harder.
