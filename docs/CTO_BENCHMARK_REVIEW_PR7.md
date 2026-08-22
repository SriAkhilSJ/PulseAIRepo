# CTO Review — PR #7 `benchmark/reliability-v1-runner`

**Date:** 2026-08-22 · **Reviewer:** Office of the CTO (acting) · **Scope:** the latest merged commit — the Pulse Reliability Benchmark v1 (contract, evaluator, fixtures, runner)

> Rule I applied everywhere: **claims are verified by running the artifact, not by reading its README.**

---

## 1. Verified facts (I ran these)

| Claim | Verdict |
|---|---|
| "99 benchmark tests pass" | ✅ **99/99 passed in 14.7 s** on this machine (`test_benchmark_{contract,evaluator,fixtures,runner}.py`) |
| Evaluator is deterministic and evaluator-owned | ✅ Strict run-record schema (`extra="forbid"`, frozen), no I/O at import, same input ⇒ same result |
| Hard failures override every outcome | ✅ workspace escape, secret disclosure, unapproved network, orphaned processes, false success claims, duplicate mutation after replay, checkpoint-restore failure, concurrent-user-edit overwrite |
| Baseline classification (new / pre-existing / environmental) | ✅ implemented and unit-tested |
| Network policy is sane for real runs | ✅ model tasks use `allowlist` (harness declares `allowed_network_destinations`); zero-budget tasks use `deny` / `localhost-only` |

## 2. The hard truth: it measures reliability, not your four axes

Your goal: **Latency · Performance · Durability · Cheap (fewer API calls).**
This suite's `RunRecord` *captures* the numbers for all four — and then **enforces only one**.

| Your axis | Enforced? | What exists today |
|---|---|---|
| **Durability** | ✅ **Strong** | PBR-011 (no orphaned processes), PBR-012 (cancel mid-context), hard-failure list (replay dup, checkpoint restore, concurrent-edit overwrite) |
| **Performance** | ◐ Partial | PBR-004 bounds context (`files_considered`, `bytes_read`), PBR-005 ranks the gold paths — but **no wall-clock or throughput gate** |
| **Latency** | ❌ Recorded, never gated | `startup_ms`, `first_token_ms`, `completion_ms` captured and printed — **zero checks assert a bound** |
| **Cheap (fewer API calls)** | ❌ Recorded, never gated | `model_calls`, `tool_calls`, input/output/**cache** tokens, `estimated_cost_usd` captured and printed — **zero checks assert a ceiling or a cache-hit floor** |

Consequence: today this suite can prove *"Pulse does not lie, leak, escape scope, or orphan processes."*
It **cannot** prove *"Pulse is fast and cheap"* — which are your two headline differentiators. Nobody may yet say "low latency" or "cheap API calls" on the strength of this commit.

## 3. Second gap: no execution lane, so zero runs exist

The 99 green tests prove the **grader** is honest. They prove **nothing about the product**.
The README defers "execution (desktop CDP harness)" to a separate lane. CTO decision: **pull the harness into this repo** (as `benchmarks/pulse_reliability_v1/harness/`), because trust is built by runs, not by architecture diagrams.

Good news: **PBR-001..004, 011, 012 need no API key** (read-only / process tasks, `deny` or `localhost-only`). The first real run costs zero rupees.

## 4. Third gap: usage numbers are harness self-reported

`model_calls` / tokens / cost come from the harness's word. For cost claims, usage must be **reconciled against the bridge `telemetry` frames** (which already carry token counts): evaluator-side check that per-turn telemetry sums == the run totals. The harness must not be able to flatter itself.

## 5. How I'd close the gaps (the trust flywheel)

1. **Now, zero budget — harness lane in-repo.** Launch the fork IDE with `--remote-debugging-port`, drive PBR-001..003 / 011 / 012, capture frames/events/DOM/process/network into `RunRecord`. Gate: harness unit tests + 3 real desktop runs green. → **first real evidence rows exist.**
2. **When a key arrives — baseline run.** One pass of PBR-005..010 (model tasks) establishes observed medians for latency/cost.
3. **Add `perf` and `usage` check types** with task-specific ceilings at **2–3× the baseline median**, tightened per milestone; plus a **cache-hit floor** (`cache_tokens / (cache_tokens + input_tokens) ≥ X%`) — that single check encodes the "prompt caching is sacred" law that was your #1 cost lever. From then on, a PR that makes Pulse slower or pricier **fails the suite**.
4. **Cadence & dashboard.** Runs pinned to a commit; result JSONs stored outside git; one page: task × outcome × 4-axis sparklines. After **3 consecutive green suite runs**, the company may claim "reliability v1". After latency/cost gates pass 3×, it may claim "fast and cheap."

## 6. Verdict

PR #7 is the strongest quality artifact in this repo — correct, deterministic, paranoid in exactly the right places (false-success detection, replay/checkpoint durability, workspace-escape). **Merge approved (already landed).** But it is the **grader**, not the **promise**. The next two moves — the in-repo CDP harness and the perf/cost gates — are what convert "a trustworthy grader" into **trustworthy product claims**.

> One-line rule going forward: **belief is not evidence. This repo already paid that tuition once (Test-2: "believe PASS" vs verified). The benchmark exists so we never pay it again.**
