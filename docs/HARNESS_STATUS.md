# Harness v0.1 — Status & Handoff

**Date:** 2026-08-22 · **Scope:** execution lane of the Pulse Reliability Benchmark (PR #7)

## What this is (plain language)

The benchmark from PR #7 is a **grader** — it decides pass/fail from evidence. But
nothing generated evidence: there was no referee. This change builds the referee:

```
harness  →  driver (eyes)  →  recorder (memory)  →  evaluator (judge)  →  report card (scoreboard)
```

Three sets of eyes (drivers):

| Lane | What it watches | Cost | Runs where |
|---|---|---|---|
| `echo` | The engine's bridge protocol, driven by the deterministic echo test-runner | **Zero** (no API key) | Anywhere |
| `bridge` | The real engine over Bridge Protocol v2 (stdio) | Zero for workspace/cancel/context; needs a key for model tasks | Anywhere with the repo venv |
| `cdp` | The built PulseAI IDE over Chrome DevTools Protocol | Zero | A machine with the built IDE (your Windows box) |

## What was built

- `benchmarks/pulse_reliability_v1/harness/` — recorder, drivers (`base`, `bridge`, `cdp`),
  scenarios, orchestrator, report card, CLI (`python -m benchmarks.pulse_reliability_v1.harness`).
- `src/bridge/__main__.py` — **one test-seam addition**: the echo test-runner can now
  simulate an in-flight turn that honours a `cancel` (`PULSEAI_ECHO_DELAY_MS`). Default `0`
  = historical behaviour, byte-identical. Production path untouched. All 20 bridge tests pass.
- `src/tests/test_benchmark_harness.py` — 15 tests (recorder, protocol v2 client, cancel
  semantics, coverage model, CDP helpers, report card, CLI).
- `src/tests/test_benchmark_harness_cdp.py` — **5 CDP integration tests against a real
  mock CDP endpoint** (actual HTTP discovery + WebSocket Runtime.evaluate traffic),
  including a full end-to-end PBR-001 run graded **PASSED** on the cdp lane.
- **Combined gate: 139 passed** (99 benchmark + 15 harness + 5 CDP + 20 bridge).

## CDP lane: what is proven, what needs your machine

The built PulseAI IDE cannot exist in a fresh checkout (build artifacts are gitignored by
design), so the live app is exercised on the founder's machine. What IS proven here:

- `CdpDriver.connect()` — real HTTP `/json/version` + `/json/list` discovery, target
  pick (workspace-URL preference), WebSocket attach, `Runtime.enable`.
- `observe_dom()` — real `Runtime.evaluate` round-trips return correct
  enabled/visible/text/count snapshots into the recorder.
- `--launch` spawns the app command, waits for the endpoint, attaches, and terminates
  the process cleanly on shutdown.
- Unreachable endpoint → loud `DriverError` (never a silent pass).
- **Full PBR-001 on the cdp lane grades PASSED** (composer disabled + hint text +
  no prompt frames) against the mock — the exact task to run on your machine.

## Demo evidence (this machine, zero cost)

```
python -m benchmarks.pulse_reliability_v1.harness run \
    --task PBR-012 --driver echo --workspace /tmp/pbr-demo-ws \
    --python /tmp/bvenv/bin/python --echo-delay-ms 2500 \
    --cancel-after-start-ms 100 --run-id demo-pbr012-echo
```

Result (graded by the evaluator, not by the harness):
- `cancelled-protocol` **PASSED** — real protocol traffic: `turn_done` with `cancelled=true` after a live cancel request (completion in ~212 ms, before any token).
- `no-post-cancel-model-call` **PASSED** — zero `llm.request` after cancel.
- `cancelled-ui` / `no-worker-growth` **failed** — DOM and process evidence need the desktop lane. The harness **refuses to pretend** these passed.

Report card: `bench-results/report-card.md` (gitignored — results never live in git).

## Bugs the harness caught while being built

1. **Prompt frame missing `workspace`** — the bridge enforces a workspace on *every* prompt
   frame (P0 contract). The harness now sends it; a first draft would have produced
   "workspace required" errors on every real run.
2. **Batch alias bug** — `batch = self._lines; self._lines.clear()` destroyed the batch
   (list alias). Fixed to copy-then-clear in `wait_turn`/`wait_for_frame`.

## Handoff: what runs on YOUR machine (founder's Windows box)

Prerequisites on your machine:
- Full env + key configured in the repo's `.env` (gitignored — keys never committed).
- Built IDE at `desktop/vscode/.build/electron/PulseAI.exe`.
- The test venv needs `websockets` for the CDP lane: `pip install websockets`
  (the driver fails loudly with this hint if it is missing — never a silent pass).

```powershell
# Zero-cost desktop task (PBR-001: no folder => prompts blocked):
python -m benchmarks.pulse_reliability_v1.harness run `
    --task PBR-001 --driver cdp `
    --launch "desktop/vscode/.build/electron/PulseAI.exe --remote-debugging-port=9222" `
    --port 9222

# All zero-cost tasks, then the scoreboard:
python -m benchmarks.pulse_reliability_v1.harness report --results-dir bench-results
```

CDP live-window integration beyond DOM observation (frame/event capture, native
workspace open, process snapshot) is the next step and requires the live app —
that is the one piece that cannot be validated in this sandbox.

## Honest limits (v0.1)

- `bridge` lane on a machine without the repo venv fails with a clear error (not a pass).
- DOM checks pass only on the `cdp` lane; `process` checks need the host lane.
- Usage numbers are harness-reported until reconciled against engine `telemetry` frames.
- No real-model latency/cost rows exist yet — they need the bridge lane with a key.
  **Rule of three:** product claims require 3 consecutive green runs on the same lane.

## Next steps (in order)

1. **On your machine:** PBR-001/003 via `cdp` (DOM checks) — needs only the built IDE, no key.
2. **With a key:** PBR-005…010 on `bridge` lane → first real latency/cost baseline rows.
3. **Perf/cost gates:** add `perf`/`usage` check types with ceilings at 2–3× baseline +
   a cache-hit floor (see `docs/CTO_BENCHMARK_REVIEW_PR7.md`).
