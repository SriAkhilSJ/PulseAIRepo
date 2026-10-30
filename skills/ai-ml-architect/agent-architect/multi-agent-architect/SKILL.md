---
name: multi-agent-architect
description: Architect-level multi-agent design — when several agents beat one, supervisor versus peer topologies, message contracts and shared state, handoff conditions, cost and latency multiplication, and the failure modes of agents amplifying each other's errors. Use when one agent is not enough and you must justify more.
license: MIT
compatibility: LangGraph, CrewAI, AutoGen, custom orchestrators
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/agent-architect/multi-agent-architect
  crusor-origin: original
  crusor-sources: "langchain-ai.github.io/langgraph; microsoft.github.io/autogen; arxiv.org/abs/2308.08155"
  crusor-triggers: "multi agent, agent orchestration, supervisor agent, handoff, crewai, langgraph, agent swarm, agent collaboration, planner agent"
  crusor-verified-on: "2026-10-30"
---

# Multi-Agent Architect

Multiple agents are **a distributed system of unreliable components**. Each added
agent multiplies cost, latency, and the ways the whole thing can fail.

## When to use

- Distinct skills with genuinely different tools or prompts (research vs code vs
  review).
- A supervisor that must decompose and verify work.
- Parallelisable subtasks where wall-clock time matters.

## When NOT to use

- A single agent with good tools and a clear prompt solves it — most of the time it
  does.
- The task has a known sequence: write a workflow, not a conversation.
- Cost or latency budgets are tight.

## Decision 1 — Justify the count

| Reason | Valid |
|---|---|
| separate tool permissions | yes |
| separate context windows to avoid dilution | yes |
| parallel exploration | yes |
| "more agents = smarter" | no |
| reviewer as a distinct critic | yes, if it has an eval |

- Start with one agent; split only when a specific failure is traceable to overloaded
  context or tool confusion.
- Two agents that pass messages in a loop are an expensive way to build a for-loop.

## Decision 2 — Topology

| Topology | Shape |
|---|---|
| supervisor | one planner delegates to specialists, collects results |
| pipeline | fixed stages, each an agent |
| peer/debate | agents critique each other, judge decides |
| blackboard | agents read/write a shared store |

- Supervisor is the default: one decision-maker, bounded delegation.
- Peer topologies need a termination rule and a judge, or they argue forever.

## Decision 3 — Contracts

- Define the message schema between agents: task, inputs, expected output, budget.
- Each handoff includes: what is done, what is expected, what "finished" means.
- Shared state (files, DB, blackboard) with an explicit write policy — concurrent
  writes corrupt.
- No agent inherits another's credentials; permissions are per-agent and minimal.

## Decision 4 — Budgets and termination

- Global budget: total tokens, wall clock, and step count for the whole run.
- Per-agent budget so one specialist cannot consume everything.
- Termination: goal met, supervisor decides, budget exhausted, or repeated
  failure — all four implemented.
- Detect livelock: agents re-delegating the same task with slightly different words.

## Decision 5 — Errors amplify

- A wrong fact from agent A is treated as ground truth by B and C. Add verification
  at handoff for anything factual.
- Include the source or evidence with each result, not just a conclusion.
- Reviewer agents must be able to say "unknown" and to fail the run.
- Log the full trace per agent; debugging a multi-agent failure without traces is
  guesswork.

## Decision 6 — Observability

- One trace spanning agents with parent/child spans; per-agent token and cost.
- Metrics: handoffs per run, retries, escalations, human interventions, success rate
  per topology.
- Replay a failed run from the trace as a regression test.

## Failure modes at scale

- Twelve agents, 40 steps, $6 per task, quality equal to one good agent.
- Agents caught in a delegation loop until the budget cap fires.
- Peer debate with no judge; the run never terminates.
- Specialist agents share one broad credential; the blast radius is the estate.
- A hallucinated fact propagated through three agents without verification.

## Verification receipts

1. Justification table: each agent exists for a named failure it solves.
2. Topology diagram with handoff schemas.
3. Budget caps enforced in a deliberately runaway test.
4. Trace of one complete run with per-agent cost and latency.
5. Comparison against a single-agent baseline on the same eval set.
