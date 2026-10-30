---
name: agent-architect
description: Architect-level autonomous agent design — the loop and its termination, tool contracts and permission scope, memory and state, planning versus reacting, human approval gates, cost and step ceilings, and the containment that makes an agent safe to leave running. Use when a model will take multi-step actions with tools rather than answer once.
license: MIT
compatibility: Any tool-calling model; MCP servers; sandboxed runtimes
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/agent-architect/agent-architect
  crusor-origin: original
  crusor-sources: "docs.anthropic.com/en/docs/build-with-claude/tool-use; modelcontextprotocol.io; arxiv.org/abs/2308.11432"
  crusor-triggers: "agent, agentic, tool use, function calling, autonomy, multi step, mcp, orchestration, human in the loop, autonomous workflow"
  crusor-verified-on: "2026-10-30"
---

# Agent Architect

An agent is **a loop with permissions**. The architecture question is not what it
can do, but what it cannot do, what stops it, and who finds out.

## When to use

- The task needs several steps whose path is unknown in advance.
- Tools must be chosen at runtime.
- A workflow must run unattended with human oversight at chosen points.

## When NOT to use

- The path is known: write a workflow or a script. A deterministic pipeline is
  cheaper, faster, and testable.
- One model call suffices: that is `llm-app-architect`.
- The action is irreversible and high-stakes with no approval step — do not ship
  it as autonomous.

## Decision 1 — Loop and termination

- Explicit state machine, not a free-running while-loop: think → act → observe,
  with a counter.
- Terminate on: goal met, step limit, token/cost budget, wall-clock timeout,
  repeated identical action, or an unrecoverable tool error.
- Every loop needs a cheap "am I making progress" check; loops that spin are the
  dominant cost failure.
- Log the full trajectory (thought, action, observation) with ids for replay.

## Decision 2 — Tool contracts

| Contract element | Rule |
|---|---|
| description | states when to use and when not to |
| input schema | strict typed, validated before execution |
| output | bounded size, structured, errors as data |
| idempotency | safe to retry with the same key |
| blast radius | read / write / destructive, declared |

- Few, well-described tools beat many overlapping ones.
- Truncate and summarise observations; a 100 KB tool output destroys the context
  window and the budget.
- Tool errors return actionable text the agent can recover from, not stack traces.

## Decision 3 — Permissions

- Scoped credentials per tool, least privilege, short-lived — never the user's
  broad token in the agent's hands.
- Separate read tools from write tools; write tools gated by approval or by an
  explicit policy (`auto-approve below $50`).
- Destructive operations require confirmation with a summary of what will change.
- Sandbox code execution: container, no network unless declared, resource caps.
- Deny by default; allowlists for tools, domains, and paths.

## Decision 4 — Memory and state

- Short-term: the trajectory, trimmed or summarised as it grows.
- Long-term: an external store with explicit write rules; do not let the agent
  silently accumulate facts.
- Checkpoint state so a run can resume after failure without repeating effects.
- Deduplicate actions by key to survive retries.

## Decision 5 — Human in the loop

- Approval gates at the irreversible step: payment, deletion, external comms,
  production deploy.
- Show the diff, the cost, and the tool call being approved — not a vague "allow".
- Define escalation: what the agent does when uncertain (ask, stop, fall back).
- Every autonomous run has an owner and a kill switch.

## Decision 6 — Observability and cost

- Trace every step with tokens, latency, tool name, and cost.
- Budget per run and per tenant, hard-capped.
- Alert on step-limit hits, approval rejections, and repeated tool errors.
- Replay a failed run from its trajectory in a test harness — that is the agent's
  regression suite.

## Failure modes at scale

- A loop that retries a failing tool forever, billing per attempt.
- Broad credentials letting an agent touch unrelated systems.
- Context filled with raw tool output until the goal is forgotten.
- Approval fatigue: gates so frequent that reviewers click yes.
- Two agents in a loop with each other, amplifying.

## Verification receipts

1. Per-run budget caps enforced, verified by a deliberately looping task.
2. Tool inventory with declared blast radius and scoped credentials.
3. Approval gate exercised: irreversible action blocked without approval.
4. Kill switch tested mid-run; state left consistent.
5. Replay of one failed trajectory reproducing the failure in a test.
