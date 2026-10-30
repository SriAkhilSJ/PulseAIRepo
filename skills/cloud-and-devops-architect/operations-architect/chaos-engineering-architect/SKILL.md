---
name: chaos-engineering-architect
description: Architect-level resilience experimentation — hypothesis-driven fault injection, blast-radius limits and abort conditions, what to break first (instances, AZs, dependencies, latency), the game-day format, and the fixes that must come out of every experiment. Use when reliability claims need evidence rather than confidence.
license: MIT
compatibility: Chaos Monkey, Gremlin, Litmus, AWS FIS, Toxiproxy
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/operations-architect/chaos-engineering-architect
  crusor-origin: original
  crusor-sources: "principlesofchaos.org; aws.amazon.com/fis; litmuschaos.io/docs; netflix.github.io/chaosmonkey"
  crusor-triggers: "chaos engineering, fault injection, game day, chaos monkey, litmus, blast radius, resilience testing, failure injection, abort condition"
  crusor-verified-on: "2026-10-30"
---

# Chaos Engineering Architect

Chaos engineering is **an experiment with a hypothesis, a blast radius, and a
stop button** — not random destruction in production.

## When to use

- Reliability is claimed (SLOs, multi-AZ, failover) but untested.
- Before a launch, a peak event, or a region migration.
- After an incident, to prove the fix holds.

## When NOT to use

- No observability: you cannot observe the effect, so you will not learn anything.
- No rollback path or no on-call coverage.
- The system is already unstable — fix it first.

## Decision 1 — The experiment

```
steady state (SLI baseline)
  → hypothesis ("losing one AZ keeps checkout error rate < 1%")
  → injection (scoped, time-boxed)
  → observation (SLIs, alerts, traces)
  → abort if blast radius exceeded
  → finding + fix + repeat
```

- Steady state defined numerically before injecting anything.
- Hypothesis states the invariant, not the mechanism.
- Every experiment has an owner, a window, and a communication channel.

## Decision 2 — Blast radius

| Environment | Allowed |
|---|---|
| dev | anything, including data loss |
| staging | same topology as prod, full injections |
| prod, canary | one instance or one small % of traffic |
| prod, broad | only with executive sign-off and abort automation |

- Start with the smallest scope that can falsify the hypothesis.
- Abort conditions are automated: SLI breach, error budget burn, or manual stop.
- Kill switch tested before the experiment, not during.
- Never inject into an experiment you cannot stop within seconds.

## Decision 3 — What to break

| Fault | Proves |
|---|---|
| kill an instance | autoscaling and health checks |
| lose an AZ | failover, quorum, capacity |
| dependency latency +2 s | timeouts, circuit breakers |
| dependency error 50% | fallbacks, retry storms |
| DNS failure | caching, hardcoded IPs |
| credential expiry | rotation and refresh |
| database failover | connection handling |
| disk full | logging and cleanup behaviour |

- Dependency faults find more real bugs than instance kills.
- Retry-storm experiments are mandatory if you have retries at multiple layers.

## Decision 4 — Game days

- A scripted session with roles: facilitator, injector, observer, scribe.
- Duration bounded (30–90 min), with a clear "stop everything" protocol.
- Observers watch dashboards and alerts, not the injector's screen.
- Notes captured live: time of injection, symptom onset, actions, detection time.
- Findings become tickets with owners and due dates, tracked to closure.

## Decision 5 — After

- Measure time-to-detect and time-to-recover; those are the outputs.
- Every finding produces a code, config, or alert change — not a document.
- If nothing breaks, the experiment was either too weak or the system is genuinely
  resilient; distinguish with a stronger fault.
- Automated continuous chaos in non-prod; scheduled experiments in prod.

## Failure modes at scale

- Chaos run in production first, no abort, full outage.
- "We killed a pod and it came back" called resilience testing.
- Findings documented, nothing fixed, same failure next quarter.
- Injections during a release window, confusing two variables.
- Blast radius scoped by namespace but the shared database was in it.

## Verification receipts

1. Experiment template with hypothesis, scope, abort conditions.
2. Steady-state baseline captured before injection.
3. Kill switch exercised; injection stopped within the stated time.
4. Detection and recovery times recorded per experiment.
5. Findings list with owners, fixes merged, and a re-run proving the fix.
