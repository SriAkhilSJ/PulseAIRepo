---
name: autoscaling-architect
description: Architect-level elasticity design — the metric that actually predicts load, target-tracking versus step scaling, warm-up and cooldown, cluster autoscaling and bin-packing, scale-to-zero trade-offs, and the load-shedding that must exist when scaling cannot keep up. Use when capacity must follow demand.
license: MIT
compatibility: Any cloud; ASG, Karpenter, HPA/KEDA, Cloud Run, ECS
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/compute-architect/autoscaling-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/autoscaling; kubernetes.io/docs/concepts/workloads/autoscaling; keda.sh/docs"
  crusor-triggers: "autoscaling, scaling policy, hpa, keda, cluster autoscaler, karpenter, target tracking, scale to zero, load shedding, capacity"
  crusor-verified-on: "2026-10-30"
---

# Autoscaling Architect

Autoscaling is **a control loop with delay**. Design it around the delay, or the
system oscillates between too little and too much.

## When to use

- Traffic varies by more than ~3× between quiet and busy.
- Batch or queue-driven work whose arrival is bursty.
- Costs must fall during idle periods.

## When NOT to use

- Steady load where a fixed fleet is cheaper and simpler.
- When the bottleneck is a database that cannot scale with the app.

## Decision 1 — Scaling signal

| Signal | Use when |
|---|---|
| CPU utilisation | compute-bound workers |
| request count / RPS | stateless HTTP |
| queue depth or age | async workers (the best signal) |
| latency (p95) | user-facing SLOs |
| scheduled | known diurnal patterns |
| predictive | mature, seasonal products |

- Scale on the signal that **leads** the load you are protecting. Request count
  leads CPU; queue depth leads worker saturation.
- Never scale on memory for a leaking-but-stable process; fix the leak.

## Decision 2 — Policy shape

- Target tracking for the common case (keep RPS-per-instance at a target).
- Step scaling for sharp cliffs with different step sizes.
- Scheduled scaling for predictable peaks — cheaper than reacting late.
- Min replicas > 0 for latency-critical services; scale-to-zero for internal tools.
- Cooldown/warm-up long enough for real boot time: a 90 s boot with a 60 s
  cooldown guarantees thrash.

## Decision 3 — The delay budget

```
detect (1–3 samples) + decide + provision + boot + warm + register = time to help
```

- If time to help exceeds the spike duration, scaling will never arrive — use
  headroom, pre-scaling, or queueing instead.
- Warm pools, pre-baked images, and lazy-loaded apps shorten boot; measure, do not
  assume.
- Keep a floor of capacity sized to absorb the fastest known spike.

## Decision 4 — Cluster autoscaling

- Node autoscaling is slower than pod autoscaling: pods pending for minutes is
  normal, not a bug.
- Bin-packing: request sizes decide utilisation. Over-requesting guarantees waste
  and unschedulable pods.
- Karpenter-style provisioners beat fixed node groups on cost and speed; consolidation
  saves money but can evict mid-job — set disruption budgets.
- Cluster scale-down respects PDBs; without them, a consolidation event can drop a
  service.

## Decision 5 — When scaling is not enough

- Load shedding: reject early with 429 and `Retry-After` before queueing
  indefinitely.
- Queue-based buffering with backpressure to the producer.
- Graceful degradation of non-critical paths (recommendations, analytics calls).
- Capacity reservations for known events (launches, sales, batch windows).

## Decision 6 — Verification

- Load test with a ramp that reproduces the real spike shape; watch time to help.
- Chaos test: kill 30% of capacity and confirm recovery within the SLO.
- Track cost per request at different scales; autoscaling should reduce it.
- Alarm on "at max capacity for > N minutes" — the silent pre-outage signal.

## Failure modes at scale

- Scaling on CPU with a memory-bound service; nothing ever scales.
- Cool-down shorter than boot time, permanent oscillation.
- Max replicas set to 4 "to save money"; the limit is discovered in an outage.
- Database connection pool fixed while app instances scale 10×.
- Scale-down consolidation evicting a long job, silently losing work.

## Verification receipts

1. Scaling signal table per service with the threshold and rationale.
2. Ramp load test: time to help measured against the spike duration.
3. Max-capacity alarm configured and tested.
4. Scale-down event with PDBs shown protecting in-flight work.
5. Cost per 1k requests at low and high scale.
