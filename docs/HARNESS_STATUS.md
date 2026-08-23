# Harness v0.1 — Status & Handoff

**Date:** 2026-08-22 · **Scope:** execution lane of the Pulse Reliability Benchmark (PR #7)

## Keyless milestone — COMPLETE (2026-08-22)

Everything that can be proven **without an API key** is done and green:

- **Combined gate: 142 tests passed** (99 benchmark + 18 harness + 7 CDP + 20 bridge).
- Keyless demo runs (sandbox): PBR-001 **PASSED** on the cdp lane (mock), PBR-003 2/3,
  PBR-012 2/4 — every gap explicitly labelled, never faked.
- `run-all` command: one command runs the keyless plan (PBR-012 echo + PBR-001/003 cdp)
  and renders the report card. Run dirs + card live under `bench-results/` (gitignored).
- `scripts/run_keyless_cdp.bat` — one-click keyless desktop run on Windows.
- Mock runs are marked `mock` in result JSONs and shown as `cdp (mock)` in the report
  card, with an explicit honesty note — mock evidence can never masquerade as product
  evidence.
- Report card now lists **"Not yet run"** tasks with the reason (provider key vs live
  engine/desktop lane).

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
# ONE command: all keyless tasks (PBR-012 echo + PBR-001/003 cdp) + report card
python -m benchmarks.pulse_reliability_v1.harness run-all `
    --workspace C:\path\to\a\test\workspace `
    --launch "desktop\vscode\.build\electron\PulseAI.exe --remote-debugging-port=9222" `
    --port 9222 --connect-timeout 45

# ...or the one-click script (same thing):
scripts\run_keyless_cdp.bat C:\path\to\a\test\workspace

# Scoreboard only:
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

---

# Harness v0.2 — Lane-aware grading (2026-08-22, arena session)

## What changed

The evaluator is now **lane-aware**. `evaluate_task`/`evaluate_suite` accept
`covered_check_ids`; a check whose evidence class the run's lane cannot
produce (DOM/process need the cdp/desktop lanes) grades **`not_run`** — never
`failed_new` — and the outcome is computed over coverable checks only. A run
where nothing is coverable can never pass.

Why: under v0.1 semantics every echo/bridge-lane run was permanently
`failed_functional` even when ALL coverable checks passed (PBR-012 echo: 2/2
coverable green, DOM/process uncoverable → red). A scoreboard that is always
red off the desktop lane trains everyone to ignore red. `not_run` is still an
explicit label — never a fake pass — and the report card shows it
(`2/4 (2 not run on lane)`).

Evidence: PBR-012 echo run `arena-pbr012-echo-2` → **passed**, 2/2 coverable,
2 not_run; zero model calls. Pre-fix run dirs preserved under
`bench-archive-pre-lane-aware/` (outside the results dir; gitignored).

## Security incident (same session)

A live Sarvam `CUSTOM_API_KEY` was pasted into `README.md` and **pushed to
GitHub** in `a7587563`. It is public. Actions taken:

- Key removed from README (commit `54c2ccbb`); real key now lives only in the
  gitignored `.env`.
- **The key must be rotated at the Sarvam dashboard** — scrubbing the file
  does not un-leak it from git history.
- Until rotation, assume anyone can drain the remaining credits.

## Verification

- Combined gate re-run in a fresh sandbox venv: **169 passed** (99 benchmark +
  21 harness/cdp incl. 3 new lane-aware tests + bridge suite), 0 failed.
- New regression tests: uncoverable → `not_run` + outcome from coverable set;
  `not_run` never masks a real coverable failure; all-not_run never passes.
- Sarvam API probe from this sandbox: **blocked by egress policy** (SSL
  connect reset) — run the probe on the founder machine instead:
  `curl -sS -w "\nHTTP %{http_code} | total %{time_total}s\n" \
    https://api.sarvam.ai/v1/chat/completions \
    -H "Authorization: Bearer $CUSTOM_API_KEY" -H "Content-Type: application/json" \
    -d '{"model":"sarvam-105b-conversations","messages":[{"role":"user","content":"Reply with exactly: OK"}],"max_tokens":8,"temperature":0}'`
  (~30 tokens; the only sanctioned credit spend before the paid runs below.)

## Credit budget (30 credits) — spend plan

| # | Run | Est. cost | Buys |
|---|---|---|---|
| 0 | Reachability probe (above) | <0.1 | Key validity + provider latency floor |
| 1 | **PBR-002** bridge lane, tiny fixture workspace | ~1 | First real end-to-end row: workspace routing + `llm.request` boundary + first-token latency |
| 2 | **PBR-012** bridge lane (real engine, cancel during context prep) | ~0.5 | Cancel semantics on the REAL engine, not echo |
| 3 | **PBR-004** bridge lane, 20k-entry fixture | ~2 | Context-bounding receipt on a big tree |
| 4 | Hold remaining ~26 until 1–3 are green ×3 (rule of three) | — | Never spend on a red lane |

Rules: no re-runs on failure without a written root cause; every paid run
gets its result dir + card row; PBR-005…010 wait until the founder approves
spending beyond the plan.

---

# Full-suite test receipt (2026-08-22, arena session 2)

## Numbers

- Full selection (`src/tests` minus `test_session_engines.py`), fresh sandbox
  venv, Python 3.11: **882 passed, 37 failed, 3 skipped**.
- All 37 failures trace to ONE environmental root: tiktoken BPE files
  (`cl100k_base`/`o200k_base` from openaipublic.blob.core.windows.net) cannot
  download in this sandbox (egress blocked → SSL EOF). On a connected machine
  these pass — the 2026-08-14 receipt (615 green) is the reference; the suite
  has grown since.

## Real bugs found & fixed this session (were hidden by the above noise)

1. **Stale desktop path pins** — `test_workbench_capabilities.py` pointed at
   the deleted `desktop/src/...` overlay layout; 4 capability-boundary pins
   had silently not run since the overlay moved into `desktop/vscode/`.
   Fixed to the canonical fork path; 5/5 pass.
2. **Windows hang-defense tests never exercised the Windows path** —
   `_terminate` gates tree-kill on `os.name == "nt"`, so on Linux the two
   `_taskkill_tree` assertions failed and the fallback test passed for the
   wrong reason. Tests now simulate `os.name = "nt"`; 18/18 pass.
3. **`pillow` undeclared** — `src/tools/visual_quality.py` imports PIL but it
   was only present transitively (via sentence-transformers). Declared in
   pyproject + uv.lock (already locked at 12.3.0; no resolution change).

## PBR-012 upgraded to the real engine (zero credits)

`arena-pbr012-bridge-1` — **passed** on the bridge lane (real engine over
stdio): cancel honoured during context prep, `turn_done cancelled=true`,
zero `llm.request` events. Sarvam egress is blocked in this sandbox, so no
model call was even possible — evidence obtained at literally zero credits.
Remaining for PBR-012: DOM/process checks on the desktop lane (your machine).

---

# Durability receipt + guarded paid-runner (2026-08-22, arena session 3)

## Provider-unreachable durability test (PBR-002, bridge lane, sandbox)

Sandbox egress to api.sarvam.ai is firewalled, so a PBR-002 attempt here CANNOT
reach the provider — a free, real test of "what happens when the provider dies
mid-task". Result (`arena-pbr002-bridge-blocked`, archived):

- Failed fast and clean in ~35 s — no hang, no watchdog kill needed.
- All checks graded `failed_environmental` → `failed_harness`: the evaluator
  blames the ENVIRONMENT, never silently the product.
- **0 model calls, 0 tokens, $0.0000** — a failing run cannot burn credits.
- **Zero orphan processes** after shutdown (bridge child reaped).
- Run preserved in `bench-archive-pre-lane-aware/` as durability evidence.

## scripts/run_paid_pbr002_guarded.ps1 (founder machine)

The first paid row, guarded exactly as the founder asked (30 s checks, kill on
fail/stall):

1. Preflight: venv + `.env` key present; exact PBR-002 fixture written
   (byte-validated against fixtures.json).
2. Credit gate: ONE 8-token probe (~0.1 credit). Probe fails → benchmark never
   starts, zero benchmark credits at risk.
3. PBR-002 on the real engine as a separate process; watchdog checks every
   30 s: stall (120 s no output) → `taskkill /T /F`; hard cap 10 min → kill.
4. Prints graded checks + usage; exits with the benchmark's code.

Usage:
`powershell -ExecutionPolicy Bypass -File scripts\run_paid_pbr002_guarded.ps1 -Workspace C:\pbr002-ws`

---

# Observability wiring fix (2026-08-23, arena session 4 — from founder run founder-pbr002-1)

## What the founder's first paid run proved

- Probe: HTTP 200 in 0.81 s (new key healthy). PBR-002 turn pipeline works
  end-to-end (turn_started → token → turn_done, first token 37.7 s — includes
  ~19 s engine warm-up; the latency column now has a REAL baseline).
- Two checks failed for one root cause: **Bridge Protocol v2 never emitted
  `workspace.bound` or `llm.request`**, and the harness driver never recorded
  frames as RunEvents — event checks could only ever see zero events (and
  `no-post-cancel-model-call` was a vacuous pass). Real observability gap,
  found by the benchmark doing its job. Cost of the discovery: ~1.5 credits.

## Fix (this session, zero credits)

1. **Engine** (`src/llm/factory.py`): `RetryLLMProxy` emits an `llm.request`
   event-bus event per ACTUAL provider attempt (after the cancel gate — a
   cancelled turn never records a send it did not make), payload = model,
   attempt, bounded honest message heads (first message 3000 chars so the
   repo-map/workspace proof is visible).
2. **Bridge** (`src/bridge/`): forwards `llm.request`; every
   workspace-bearing frame emits `workspace.bound` with
   `workspace == hops == engine_root == bound root` (after the direct reply,
   so existing clients/tests are unaffected). Protocol v2 manifest + generated
   TS types updated; replay allowlist includes both.
3. **Driver** (`harness/drivers/bridge.py`): event-like frames become
   RunEvents (`workspace.bound`, `llm.request`, `runtime_degraded`,
   `tool_call_*`, `telemetry`) — event checks are no longer structurally
   vacuous; telemetry frames feed usage as a DELTA of cumulative engine
   totals (the four-axes cost column was permanently 0 before);
   `_collect` stops on any stop-type frame (async frames can trail replies).

## Verification

- 177 passed across bridge + benchmark selections (new tests: bridge emits
  workspace.bound with exact hops; llm.request projection; proxy emission +
  bounded heads; driver event recording + usage deltas).
- Live echo-lane PBR-012 run `obs-pbr012-echo`: passed AND the run record now
  contains real `workspace.bound` events — the event pipeline is proven.
- Known environmental failure unchanged: `test_guard_trims_at_auto_limit`
  needs the tiktoken BPE download (blocked in sandbox; passes online).

## Next (founder machine)

Pull latest `arena/01a02a5c-pulseairepo`, then re-run the SAME guarded
command (~1 credit): PBR-002 should now grade 3/3 with a real cost row.

---

# FIRST GREEN PAID ROW — PBR-002 (2026-08-23, founder run founder-pbr002-2)

## Result

**PASSED 3/3 on the bridge lane (real engine, real provider)** at commit
`dcd90b2f`: workspace-hops (all hops equal fixture root), proof-reaches-boundary
(workspace_proof.py visible in the llm.request), turn-completes.

**First real usage row: 7 model calls · 30,747 in / 507 out tokens · $0.0313.**
Probe 0.65 s. Total credits consumed to date: ~3 of 100.

Fix→re-run loop validated end to end: run 1 exposed the observability gap
(~1.5 cr), fix landed zero-credit, run 2 green (~1.5 cr).

## Next efficiency question (evidence, not vibes)

A one-question turn on a 3-file workspace made **7 provider calls** with
**~4.4k input tokens per call**. Candidates: planner call, main agent call(s),
aux/janitor calls (SUMMARIZER_LLM=aux, D38 post-turn review), reflection.
Before spending on the rule-of-three, run the free analyzer on the founder
machine:

    python scripts/analyze_llm_requests.py bench-results\founder-pbr002-2

It prints one line per recorded request (offset, model, attempt, message
heads' first lines) — enough to attribute each call to a subsystem and decide
which calls to kill, gate, or cheapen. Zero credits; local file only.

---

# Call attribution — the 7–11 call mystery, solved free (2026-08-23, session 5)

Founder runs: PBR-002 run A = 7 calls / 30,747 in / $0.0313; re-run = 11 calls /
47,690 in / $0.0485. Same task, same commit → **55% cost swing**. Before
spending anything, the calls were attributed with a LOCAL stub provider lane
(`scripts/stub_provider_server.py` — OpenAI-compatible fixed-response server on
127.0.0.1:8765; the real engine runs a complete turn against it; every
subsystem call is visible in llm.request frames; zero credits, zero key,
explicitly NOT product evidence).

## Baseline anatomy of ONE trivial turn (stub lane, deterministic)

| # | Caller | Payload | Verdict |
|---|---|---|---|
| 1 | Task-decision classifier ("You manage the active task…") | 2 msgs | overhead — killable |
| 2 | PLAN/DIRECT classifier ("Classify the coding request…") | 2 msgs | overhead — killable |
| 3 | Main agent call (persona + full context) | 11 msgs | the real call |

3 calls baseline. The founder's 7–11 = 3 + **4–8 provider-dependent extra
calls** (structured-output parse/repair loops against Sarvam are the prime
suspect — the stub returns instantly-valid JSON and needs zero repairs; each
repair resends the FULL ~4–8k-token context).

## Second real bug found & fixed while building the lane

The first stub run DIED mid-turn: `tiktoken.get_encoding("cl100k_base")`
downloads its BPE file on first use and the failure propagated UNGUARDED
through `token_budget`/`token_tracker` → `turn_failed`. On the founder's
machine the cache was warm, so this was latent: **any fresh machine /
offline / proxied first run would kill turn #1.** Fixed: any tokenizer
acquisition failure now degrades to a ~chars/4 heuristic encoder (logged
once, never fatal). Pin: `test_token_counting_never_dies_without_tiktoken`.
Also un-broke 37 sandbox-only test failures with the same root cause.

## Also

- `scripts/run_paid_pbr002_guarded.ps1` now REFUSES to reuse an existing
  run-id (founder-pbr002-2 re-run silently destroyed run A's artifacts).
- `scripts/analyze_llm_requests.py` now compares MULTIPLE run dirs and prints
  the variance table (calls/tokens/cost min-max-avg + swing %).

## Next spend decision (founder)

Run 3 for the rule of three (~1.5–2 cr, FRESH run-id) AND paste the analyzer
output on the 11-call run. If repair loops confirm, the fix is engine-side
(JSON-tolerant parsing / single-retry budget) — land it free, then the
rule-of-three baseline is both green AND cheap.
