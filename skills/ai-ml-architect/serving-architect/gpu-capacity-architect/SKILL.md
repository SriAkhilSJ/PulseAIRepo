---
name: gpu-capacity-architect
description: Architect-level GPU capacity planning — VRAM arithmetic for weights and KV cache, instance selection and cost per token, utilisation targets versus latency SLOs, multi-model sharing, queueing and admission, and the reservation strategy that keeps training and serving from fighting. Use when GPUs are the scarce resource.
license: MIT
compatibility: Any GPU cloud; vLLM, Triton, KServe, Ray Serve
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/serving-architect/gpu-capacity-architect
  crusor-origin: original
  crusor-sources: "docs.vllm.ai/en/latest/performance; docs.nvidia.com/datacenter; cloud.google.com/compute/docs/gpus"
  crusor-triggers: "gpu capacity, vram, gpu utilisation, kv cache, gpu cost, a100, h100, multi model serving, gpu queue, reserved capacity, gpu memory, out of memory on gpu"
  crusor-verified-on: "2026-10-30"
---

# GPU Capacity Architect

GPU capacity is **arithmetic plus scheduling**. Most "we need more GPUs" requests are
a batching or sizing problem.

## When to use

- Sizing a serving fleet or a training budget.
- GPU utilisation claims without measurement.
- Sharing a GPU pool between training and serving teams.

## When NOT to use

- API-only workloads — capacity is the provider's problem (`token-economics-architect`).
- CPU inference of small models (ONNX, quantised) may be cheaper.

## Decision 1 — VRAM arithmetic

```
weights  ≈ params × bytes_per_param   (fp16 = 2 B, fp8 = 1 B, 4-bit ≈ 0.5 B)
kv cache ≈ 2 × layers × heads × head_dim × seq_len × batch × bytes
overhead ≈ 10–20% (activations, fragmentation)
```

- KV cache, not weights, limits concurrency: a 70B model at long context fits far
  fewer concurrent sequences than the weight size suggests.
- Long-context requests consume cache proportional to their length — one 100k-token
  request can starve the batch.
- Reserve headroom; 95% VRAM usage is a crash waiting for the next burst.

## Decision 2 — Instance selection

| Constraint | Choice |
|---|---|
| latency-critical, small model | single high-clock GPU |
| throughput, large model | multi-GPU node with NVLink |
| cost-sensitive batch | spot/preemptible with checkpointing |
| bursty serving | smaller instances autoscaled |
| many small models | shared serving runtime with multiplexing |

- Compare on **cost per 1M output tokens at your target latency**, not on hourly
  price.
- Cross-node tensor parallelism has network cost; keep it intra-node where possible.

## Decision 3 — Utilisation and latency

- Utilisation and latency trade off directly: higher batch = better throughput,
  worse TTFT.
- Set the SLO first (TTFT p95, tokens/s), then maximise batch within it.
- Target 60–80% sustained utilisation for serving; 100% means no headroom and
  queueing collapse under spikes.
- Autoscale on queue depth and TTFT, never on GPU utilisation (it is already high).

## Decision 4 — Scheduling and sharing

- Separate pools (or time-sliced reservations) for training and serving; a training
  job that grabs the serving node is an incident.
- Queue long jobs with priorities; preempt training, never serving.
- Admission control: cap max sequence length and concurrent requests per tenant.
- Multi-model serving (MPS/MIG/multiplexing) for many small models; not for large
  latency-sensitive ones.

## Decision 5 — Cost governance

- Reserved/committed capacity for the steady baseline; spot for training and batch.
- Track GPU-hours by team and project; idle GPUs are the largest single waste.
- Auto-shutdown non-production GPU instances; time-box notebooks.
- Review monthly: cost per token, utilisation, and rejected requests.

## Failure modes at scale

- Fleet sized on weights only; OOM at concurrency, not at load.
- 100% GPU utilisation and a growing queue: no headroom, latency cliff.
- Training job scheduled on the serving node during peak.
- Spot instances for latency-critical serving; preemption is an outage.
- Idle dev GPUs costing more than production.

## Verification receipts

1. VRAM calculation for the deployed model and context length.
2. Load test: TTFT and tokens/s versus concurrency, with the knee identified.
3. Utilisation and queue-depth dashboards with autoscaling configured.
4. Cost per 1M tokens per pool, with reserved vs on-demand comparison.
5. Scheduling policy demonstrating training preemption without serving impact.
