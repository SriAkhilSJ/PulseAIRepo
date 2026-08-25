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

---

# Rule of three banked + the 4-vs-11 visibility gap fixed (2026-08-23, session 6)

## Founder results

PBR-002: **three consecutive greens** (runs 2, 2-re, 3) — the correctness
claim (exact-workspace routing through every layer) is now verified under the
rule of three. Cumulative spend ≈ $0.14.

But the efficiency axis trends the WRONG way: 7 → 11 → 14 model calls
($0.031 → $0.049 → $0.058) for the identical task, and the analyzer saw only
**4 llm.request frames vs 11 counted calls**.

## Root cause of the visibility gap (found + fixed)

The bridge subscribed the event bus SESSION-FILTERED; provider calls made
where no active session is set (planner pre-turn, post-turn review threads)
carry session_id=None and were silently dropped from frames while still
counted by engine telemetry. Fix: the forwarder takes an admin subscription
and filters itself — session-less events are kept, another session's events
are dropped (concurrent-turn isolation preserved). Pin:
`test_forwarder_keeps_sessionless_events_drops_other_sessions`.

## Growth attribution status

Local stub lane (deterministic, keyless): two sequential full turns —
IDENTICAL call count and message counts (2 frames, msgs 2+9 both runs).
The engine core is not self-growing. The founder's 7→11→14 growth is
environment-driven: prime suspects are (a) Sarvam response variance →
structured-output repair loops, (b) cross-run memory accumulation on the
founder machine (embeddings active there; disabled in the sandbox lane).
The forwarder fix makes the NEXT founder run show every provider call as a
frame — full attribution without new tooling.

## Next (founder, ~2 credits)

1. `python scripts\analyze_llm_requests.py bench-results\founder-pbr002-3 bench-results\founder-pbr002-4`
2. Run 4 with a fresh run-id at tip (forwarder fix included).
3. If frames now equal telemetry and the extras are repair loops → engine
   fix lands free before any further spend.

---

# Cross-run pollution — root cause found, proven, fixed (2026-08-23, session 7)

## The tell

Founder PBR-002 call counts grew LINEARLY: 7 → 11 → 14 → 17 calls and
+~10k input tokens per run (30,747 → 47,690 → 56,767 → 66,224), same task,
all green. Not variance — accumulation.

## Proof (local stub lane, zero credits, same session id three times)

| run | llm frames | main-call msgs |
|---|---|---|
| 1 | 2 | 9 |
| 2 | 3 | 12 (+3) |
| 3 | 3 | 15 (+3) |

Root cause: the engine's durable langgraph checkpointer (`~/.pulseai/
sessions.db`) keys history by thread id, and the harness driver used the
FIXED session id `bench` for every run — so each run created a session that
silently resumed ALL prior benchmark runs' turns. The four "green" rows
measured the history of all previous runs, not this run. (Earlier local
stub runs with different ids were byte-stable — which is what narrowed it.)

## Fixes

1. **Driver**: every BridgeDriver instance mints a unique
   `bench-<hex10>` session id — each benchmark run is an isolated thread.
   Pin: `test_bridge_driver_session_id_is_unique_per_instance`.
2. **Bridge honesty**: `session_create` replies now carry
   `prior_checkpoints` (read-only count from sessions.db; None when
   unknown) — a session id with durable history can never again claim a
   fresh start silently. Pin: `test_session_create_reports_prior_checkpoints`.

## Consequences for the scoreboard

- Runs 2/2re/3/4 stay green for CORRECTNESS (routing/proof/completion are
  unaffected by replayed history) but their cost/latency numbers are
  polluted and must not be used as a baseline.
- The clean baseline = next run at tip with unique ids (expect ~2-4 calls,
  small msg count — the local lane suggests ~$0.01-0.02 per isolated run).
- Rule-of-three for COST claims must be re-earned on clean runs.

---

# CLEAN BASELINE — PBR-002 at $0.0152/turn (2026-08-23, founder run founder-pbr002-5)

## The number

**3 model calls · 14,931 in / 278 out tokens · $0.0152 · 3/3 checks · 5th
consecutive green.** The session-pollution fix (349f8a88) dropped calls
17 → 3 and cost $0.0676 → $0.0152 (**-78%**) on the identical task —
closing the loop on the linear-growth diagnosis (fix the id, growth vanishes).

## Clean-run anatomy (analyzer, frames == telemetry now)

| # | offset | msgs | call |
|---|---|---|---|
| 1 | +35.3s | 2 | PLAN/DIRECT classifier |
| 2 | +36.8s | 10 | main agent (context + question) |
| 3 | +40.3s | 14 | main agent, 2nd graph iteration (replays #2's exchange) |

Frame count (3) == telemetry count (3): the forwarder visibility gap is closed.

## What is now claimable vs pending

- ✅ CORRECTNESS (rule of three ×5): workspace routing verified.
- ✅ Efficiency DIRECTION: one trivial turn = 3 calls / $0.015 clean.
- 🔜 COST claim (rule of three): two more clean runs (±% swing), ~$0.03 total.
- 🔜 LATENCY: first provider call at +35.3s (engine boot + context prep).
  The API itself answers in ~0.7s (probe). The 35s is process cold-start —
  the IDE's persistent utility process is the structural fix (warm engine),
  plus the 2nd main iteration (msgs 10→14) is the next token saver.

## Next (founder, ~$0.03)

1. Two more clean runs: `-RunId founder-pbr002-6`, then `-7` (fresh ids,
   same workspace — unique session ids make reuse safe now).
2. `python scripts\analyze_llm_requests.py bench-results\founder-pbr002-5 bench-results\founder-pbr002-6 bench-results\founder-pbr002-7`
3. Then PBR-012 on the REAL engine (bridge lane, cancel fires before any
   model call — effectively free) and PBR-004 (20k-entry workspace, ~$0.02-0.05).

---

# COST CLAIM VERIFIED — clean rule of three (2026-08-23, runs 5/6/7)

| Run | Calls | Tokens in | Est. $ |
|---|---|---|---|
| founder-pbr002-5 | 3 | 14,931 | $0.0152 |
| founder-pbr002-6 | 4 | 22,562 | $0.0228 |
| founder-pbr002-7 | 3 | 14,884 | $0.0151 |

**Claimable: one trivial turn = 3–4 provider calls, $0.015–0.023, median
$0.015.** 7 consecutive greens overall. Cumulative spend $0.26.

## Reading the swing honestly

The min-max swing (52%) is bimodal, not noisy: runs 5 and 7 are within 1%
of each other; run 6 alone added ONE call with ~7.6k more input tokens —
the shape of an extra main-agent graph iteration (a second/third
full-context lap), not a repair retry (all attempts observed = 1).

Why it matters beyond $0.008: the +1-lap mechanism scales with context —
on a real coding task (large context per lap) one extra iteration per turn
is a 30–50% cost multiplier. Attribution BEFORE fixing: the run-6 record
already contains the answer — `analyze_llm_requests.py
bench-results\founder-pbr002-6` (free) shows the extra call's message
heads and iteration shape.

## Next lanes

1. FREE: analyzer on run 6 alone (attribute the 4th call).
2. FREE: PBR-012 on the real engine (bridge lane) — cancel fires before any
   provider call; proves real-engine cancel + zero post-cancel sends.
3. ~$0.03: PBR-004 (20k-entry workspace) — context bounding under load.

---

# Lane-aware timeouts + PBR-012 real-engine green; PBR-004 gap isolated (2026-08-23, session 8)

## Founder failures diagnosed (both free)

- **PBR-012 bridge failed_harness**: the scenario waited 30s for turn_started;
  the real engine's cold start is ~26-36s. The cancel itself worked PERFECTLY
  (0 provider calls after cancel — engine honours cancel before any spend).
- **PBR-004 bridge failed_environmental**: 60s window for a 20k-entry first
  index build. Also needs the engine receipt (below).

## Fix: lane-aware waits (echo instant, real lanes generous)

`_lane_wait_s(driver, echo_s, real_s)` — PBR-002/003: 240s, PBR-004: 900s
(first 20k index build is minutes), PBR-011: 300s, PBR-012: 300s.

## Local proof (stub lane, 0 credits, real engine)

- **PBR-012 bridge: PASSED** (cancelled-protocol + no-post-cancel-model-call;
  cancel honoured during prep, zero provider calls).
- **PBR-004 on a real 20,001-file fixture: turn COMPLETED in ~3.4s** —
  `bounded-turn-completes` now passes; the engine handles a 20k tree fast.
- Remaining PBR-004 gap, isolated: `single-degraded-receipt` — the engine
  emits `runtime.degraded` only on MID-WALK truncation; a workspace pruned
  within budget by design (skip rules / task-aware layer selection) emits
  NOTHING. The check demands a receipt (count 1, files_considered <= 1000)
  proving the bound was respected. Engine work, next session: emit the
  receipt whenever the workspace exceeds the scan budget — with real counts.

## Run-6 attribution (from founder analyzer paste)

4th call = a THIRD main-agent iteration (msgs 10 -> 13 -> 16), not a repair
retry (all attempts = 1). The +lap mechanism is the last token lever; cap
or early-exit trivial turns engine-side (future work, free to build on the
stub lane).

## Spend guidance

- PBR-012 re-run on founder machine: FREE (cancel precedes any call).
- PBR-004: HOLD the ~$0.03 until the receipt fix lands — it cannot pass
  today, and we do not pay for red runs.

---

# PBR-004 unblocked — by-design bounding receipt (2026-08-23, session 9)

## Engine fix

`ContextEngine._emit_build_receipt` now also fires when the WORKSPACE itself
exceeds the scan budget (bounded O(cap) root probe, `_workspace_exceeds_
budget`) — not only on mid-walk truncation. A 20k-tree pruned by skip rules
still earns its receipt: the bound is actively protecting the turn, and the
receipt carries the REAL counts (files_considered <= 1000, bytes_read <= 16MB).
Reason string distinguishes the cases honestly
("workspace exceeds scan budget — bounded by design").

## Proof (local, real engine, stub provider, 0 credits)

PBR-004 on a genuine 20,001-file fixture: **passed** —
`single-degraded-receipt` (1 event, bounds respected) AND
`bounded-turn-completes`. Total turn ~3.7s on 20k files.

Pins: `test_oversized_workspace_gets_bounding_receipt` (exactly one receipt
with real counts on a 1200-file ws; NONE on a small ws),
`test_workspace_exceeds_budget_probe`. 133 passed across the touched surface.

## Founder: PBR-004 spend is now UNBLOCKED (~$0.02-0.05)

First run pays the one-time 20k index build (minutes); the receipt and turn
completion are proven. Then PBR-002 runs 8/9 can complete the cost
rule-of-three bookkeeping if desired — the claim is already verified.

---

# PBR-004 receipt consolidation + the 20-lap finding (2026-08-23, session 10)

## Founder run founder-pbr004-1 (first paid 20k run, ~$0.12)

- `bounded-turn-completes` PASSED — the turn finishes on a real 20k tree.
- `single-degraded-receipt` FAILED: **20 events != 1** — one receipt per
  graph lap. The engine lapped ~20 times (21 model calls, 118k input
  tokens): the receipt-per-lap was noise; the LAP COUNT is the real issue.

## Fix: ONE consolidated receipt per session

The engine-level receipt now carries an instance once-latch (engines are
session-scoped), and the pool's atomic once-flag already dedupes within a
build — whichever emitter fires first wins, later laps stay silent.
Pin: `test_by_design_receipt_fires_once_per_session` (5 builds -> exactly 1
receipt, bounds respected). Local e2e PBR-004 on the 20,001-file fixture:
**passed** (1 receipt, bounds respected, turn completes).

## The 20-lap problem (OPEN — next free attribution)

21 calls / 118k in-tokens for "Summarize the workspace." is the +lap
mechanism at scale (probably PLAN-path steps or finish-detection misses on
Sarvam replies). The run record has all 21 llm.request events:
`python scripts\analyze_llm_requests.py bench-results\founder-pbr004-1`
(free) attributes them before any engine change. Hold further PBR-004
spend until the lap fix lands; a re-run should then cost ~$0.02, not $0.12.

---

# The 20-lap root cause FIXED — one-step questions never plan (2026-08-23, session 11)

## Attribution (founder analyzer paste, founder-pbr004-1)

22 calls total: PLAN/DIRECT classifier (verdict: PLAN — wrong) → ~20 plan
laps at ~25s cadence, msgs 5→62, ZERO tool calls, one summarizer call, a
186s gap for the 20k index build. The router gates were bounded — the PLAN
LOOP was the lap source, entered because the LLM classifier's confident-wrong
PLAN verdict was trusted unconditionally.

## Fix (planner)

`_looks_like_direct_question`: obvious one-step questions (summarize /
explain / describe / what-is / tell-me / list / show-me, <200 chars, not a
creation+execution plan shape) return DIRECT **without spending the
classifier call**; and a PLAN verdict on such a question is overridden (the
heuristic only wins when the task is not ALSO an obvious plan task).

## Local e2e proof (20,001-file workspace, stub provider, 0 credits)

PBR-004: **passed** — provider calls **1** (was 2; classifier call gone),
PLAN-classifier calls 0, exactly 1 runtime_degraded receipt, turn completes.
Expected founder effect: the $0.12 20-lap turn becomes a 1-3 lap ~$0.02 turn.

Pins: test_planner_direct_gate.py (3 tests — obvious questions skip the
classifier and never plan; wrong PLAN verdict overridden; real multi-step
tasks still reach the classifier). 83 passed on the touched surface.

---

# Hermes-source review: the keyword hack was wrong — reverted (2026-08-23, session 12)

## What the hermes-agent source actually does (read, not guessed)

Fetched and read `agent/conversation_loop.py` from
NousResearch/hermes-agent (8,418 lines):

- **There is no PLAN/DIRECT intent classifier at all.** No upfront
  "should I plan?" model call.
- The loop is mechanical: model replies WITH tool calls -> dispatch, loop;
  model replies WITHOUT tool calls -> **that is the final answer**, turn
  ends.
- The only re-prompt guards are bounded (stall-guard 2/turn, dropped
  tool-call 3/consecutive, budget wrap-up) and watch **what the model DID**
  (trailing "I will now..." intent, finish_reason=tool_calls with empty
  array) — never keyword-guess what the user MEANT.

## Verdict on my session-11 fix

`_looks_like_direct_question` (keyword list) was the same disease as the
PLAN/DIRECT classifier it patched — intent interpretation by word list.
**Reverted.** The classifier override and its tests are gone
(commit history preserves the episode).

## The hermes-faithful fix (needs founder sign-off — product behavior)

Make the LOOP obey the law: an iteration with no tool call and no state
change ends the turn with the model's answer; keep only bounded behavior
guards. The PLAN/DIRECT classifier + upfront planner call can then be
retired entirely (hermes architecture) or kept as advisory UX.

## Before implementing: one free attribution

`scripts/analyze_llm_requests.py` now prints the run's LOOP ANATOMY
(tool_call_start names, safety_request counts, plan_updated frames) before
the per-call list — re-run it on founder-pbr004-1 (free) to see whether
the 20 laps were plan-steps or denied/dropped tool calls. Attribute, then
fix the loop once, correctly.

---

# Value extracted from hermes-agent's TEST infrastructure (2026-08-23, session 13)

Read hermes' AGENTS.md testing doctrine + tests/ layout (3,298 files) and
adopted what fits; documented what we deliberately did not.

## Adopted

1. **`scripts/run_tests.sh` — hermetic runner** (their "ALWAYS use the
   wrapper, never bare pytest" rule):
   - provider keys UNSET by default → no test can ever make a paid call
     (PULSEAI_TEST_KEEP_KEYS=1 opt-out for integration scripts)
   - fresh temp HOME per run → ~/.pulseai state (sessions.db,
     runtime_events.db, code indexes) can never leak across runs or onto the
     developer machine — the cross-run pollution class, killed at test level
     (PULSEAI_TEST_REAL_HOME=1 opt-out)
   - TZ=UTC, LANG=C.UTF-8 for determinism
   Proven: single-file run green under wrapper; key stripped (checked);
   real ~/.pulseai untouched after state-heavy bridge/context runs (71 passed).

2. **Audit against "never read source code in tests"** (their hard ban):
   `src/tests/test_workbench_capabilities.py` reads TS source text with
   regexes — flagged as a banned pattern. It currently guards the desktop
   catalog the only way possible without the Node toolchain; conversion path
   (behavior test over a compiled catalog, or a codegen-time check in the TS
   build) is queued for the desktop lane, not silently deleted.

## Deliberately NOT adopted (yet / ever)

- Per-file subprocess isolation (`run_tests_parallel.py`) — follow-up once
  the suite grows into it; the wrapper is the entry point either way.
- Flake-retry-with-⚠-FLAKY-summary policy — follow-up; needs the per-file
  runner first.
- Conformance vector generators — platform-rendering specific (discord/
  slack/...); our referee (drivers → recorder → evaluator, lanes with
  graded evidence) already goes beyond what hermes ships for product claims.
  Our benchmark lane approach is ORIGINAL relative to hermes; what we took
  from them is the testing discipline AROUND it.

## Doctrine deltas now enforced in this repo

- Behavior contracts, not change-detectors (already our evaluator's shape).
- Never read source in tests (newly flagged violation).
- E2E over mocks: our stub-provider lane is exactly this and stays the
  zero-credit attribution path.

---

# External 16-point code review — fact-checked, verdicts + fixes (2026-08-23, session 14)

Every claim was verified against the code before acting. Scorecard:

| # | Claim | Verdict |
|---|---|---|
| 1 | duplicate `_zero/_merge_token_usage` defs (merge artifact) | **TRUE — FIXED** (second copy deleted; file parses, tests green) |
| 2 | `_allow_embedding_compute = False`, never flipped; semantic scoring/dedup/memory layers dead | **TRUE** (0 `= True` anywhere). Nuance: matches the bounded-scan doctrine (production budgets cache-only; only `unbounded()` maintenance may compute) — but the README oversells active semantics. README correction queued; enabling is a founder product decision |
| 3 | repaired tool-call ids not persisted to checkpointer | **TRUE in substance** — repaired AIMessage is appended to state, the broken original remains in checkpointed history |
| 4 | feedback append not atomic on Windows | **TRUE-ish** — O_APPEND atomicity claim in the comment is wrong on Windows; defensive JSONDecodeError handling already exists |
| 5 | memory_manager late binding fragile | TRUE (style; works today) |
| 6 | `store_replan_lesson` unguarded → crash | **FALSE** — guarded by `if memory_manager:` two lines above (reviewer missed it) |
| 7 | "go ahead" vs "ok go ahead" quick-path inconsistency | **TRUE** — both strings sit in the veto list AND the ack vocab |
| 8 | final-response fallback returns any message type | **TRUE — FIXED** (only assistant messages qualify now) |
| 9 | duplicated 50-line denial blocks in SafeToolNode | TRUE (refactor queued) |
| 10 | state hash computed twice per turn | TRUE (two call sites; micro-perf) |
| 11 | run_tests.sh HOME path bug | **FALSE in mechanism** — `mktemp -d TEMPLATE` creates in CWD and returns a RELATIVE path, so `$PWD/$OUT` was valid (71 tests ran under it). Still, the reviewer's instinct was right that the pattern was fragile — **hardened** to an absolute `${TMPDIR}/...` template (verified absolute on GNU) |
| 12 | BROWSER_TOOLS module-level import vs README "lazy" claim | **TRUE** — contradiction stands |
| 13 | safety-guard regex bypass (`wget|bash`, `python -c`) | TRUE (acknowledged in its own comments; human checkpoint, not sandbox) |
| 14 | tool-call id seed includes index → reorder changes ids | TRUE by code (volatile-tail nuance softens the cache impact) |
| 15 | cancelled session id poisons reuse without begin() | TRUE (stale cancel_event; unique session ids mask it in the benchmark) |
| 16 | "branch is just a bot adding a broken script" | **MISLEADING** — the branch carries the session's product fixes (key scrub, observability frames, pollution fix, tokenizer durability, receipts); the review's real finds (#1,#2,#3,#8...) predate the branch — they are the inherited engine's bugs and are now tracked |

Fixes landed this session: #1 (dedup), #8 (AI-only fallback), #11 (mktemp
hardening). Queued with owners: #2/#12 (README honesty + product decision),
#3 (checkpoint repair), #7 (quick-path consistency), #9 (denial dedup), #15
(reuse cleanup). The referee culture applies to us too: the review was
graded, not trusted.

---

# Round 2 of the external review — verified + fixed (2026-08-23, session 15)

New claims, graded:

- **invoke_agent had the same msgs[-1] bug** — TRUE (fair hit: fixed the
  stream path last commit, missed the sibling). **FIXED**: only assistant
  messages qualify as the final answer, empty string if none.
- **#7 quick-path boundary** ("go ahead" pays, "ok go ahead" was free) —
  TRUE. **FIXED conservatively**: any ack CONTAINING an approval word now
  pays the classifier like the exact phrase (the approval branch owns
  routing; free "continue" is for pure acks only).
- **run_tests.sh footgun** (KEEP_KEYS + REAL_HOME) — TRUE-ish. **FIXED**:
  the combination now REFUSES without an explicit
  PULSEAI_TEST_UNSAFE_INTEGRATION=1 ack (verified firing).
- **#16 "spin"** — fair: the latest commit WAS micro-fixes + scorecard; the
  characterization was of the commit, the defense was of the branch. Both
  true, no dispute.
- **"README not updated" (founder's own diagnosis)** — CORRECT and now
  treated as the root cause it was: README carried two claims the code
  never satisfied (#2 embeddings active, #12 browser lazy import). Both
  sections now carry honest status notes; enabling embeddings stays a
  founder product decision.

Remaining queue (real refactors, unchanged): #3 checkpoint repair
persistence, #4 Windows append atomicity, #9 denial-block dedup, #10 double
hash, #13 sandbox-grade safety, #14 id-seed reorder, #15 session reuse.

---

# Hermes loop architecture ported into the agent (2026-08-23, session 16)

Founder directive: extract the ARCHITECTURE value from hermes-agent and
implement it. Read the source (conversation_loop.py, repetition_guard.py),
not the docs, and ported the two behavior-based loop disciplines:

## 1. The loop law — `src/graphs/loop_guards.py` + `gates.should_continue`

Hermes: a reply without tool calls IS the final answer; only bounded
behavior re-prompts (stall 2/turn, dropped-call 3) may continue. Ported
for a LangGraph router: `consecutive_no_tool_ai_messages` counts the
TRAILING no-tool assistant streak (resets on tool activity or user input);
after `NO_TOOL_TURN_LIMIT = 3` the turn MUST finalize regardless of which
loop produced the laps (plan, replan, intent misroute). PulseAI's bounded
finish/verify nudges are untouched below the cap — first no-tool reply
still gets its nudge; the cap only backstops the pathological streak.

## 2. Repetition content-sanity — faithful port of hermes #86581 guard

`is_repetition_dominated`: 60+ char verbatim windows, >=5 occurrences,
>=50% coverage of a >=400-char fragment (line-aligned fast path + sliding
window). A degenerate echo reply concludes the turn instead of feeding
another lap. Conservative by construction; fail-open on short inputs.

## Proof (stub lane, real engine, 0 credits)

- 102 tests green across loop-guards + bridge + benchmark + context +
  subagent-autodeny (5 new loop-guard pins: streak counting, hermes-shape
  repetition detection, router caps at 3, bounded nudges preserved below
  the cap, repetition reply finalizes).
- Live e2e with guards active: PBR-002 **passed 3/3 — 1 provider call**
  (guards did not interfere with a clean turn); PBR-004 on the 20k
  workspace **passed** (receipt + completion).

Effect on the founder's 20-lap class: capped at 3 laps worst case, no
matter which loop causes it. No intent classification involved.

---

# TEST 5, attempt 1 — VERDICT: FAIL (provider timeout; discipline held) 2026-08-23

## Graded per the pre-registered rules

turn_failed / completed=false => FAIL. But the failure CLASS is the cheapest
possible: ~$0.02 spent, ZERO human interventions, watchdog + circuit-breaker
never misfired, full frame evidence captured.

## Anatomy (from frames.jsonl)

1. PLAN/DIRECT classifier -> PLAN (1s)
2. Planner -> 8-step plan (15s)
3. MAIN call (11 msgs, full GARGANTUA task) -> died at ~122s with
   "Request timed out." = TWO 60s attempts. Root cause: the custom-provider
   request timeout default (60s) is sized for ping latency, not GENERATION
   length -- a 100B model writing the first big response of a huge build
   legitimately needs >60s when NOT streaming. Hermes sizes timeouts to
   generation and streams first (timeout then guards stalls, not length);
   it also continues truncated responses with boosted budgets.

## Fix (hermes-aligned)

- factory default timeout 60 -> 180s (env override unchanged, cap 300)
- runner sets PULSEAI_LLM_STREAMING=1 + PULSEAI_LLM_TIMEOUT=280 for the
  child (pre-set env wins); script made pure-ASCII (em-dash encoding bug
  on the founder box fixed by their agent, now structural)

Engine verified importing + a full stub turn completes with the new
default. Retry = same command, fresh RunId.

---

# TEST 5, attempt 3 (test5-3) — product FAIL, harness PASS (2026-08-23)

## Graded

turn_done, in budget (17 calls / ~127k in / breaker untouched), zero kills,
zero interventions -- every harness fix held. Product: FAIL -- deliverable
is package.json only; no site, no vendored Three.js, nothing renders.

## Root cause (agent strategy, not machinery)

The execute_code sandbox blocks imports/sockets/open() by design. Faced
with "use local Three.js files", the agent burned turns trying
urllib/subprocess INSIDE scripts, pivoted to web_fetch, then tried
execute_code downloading again -- and never used the working paths it
already has (run_terminal npm install WORKED in attempt 2; web_fetch ->
write_file was never tried).

## Fix (teaching at the moment of failure)

- execute_code docstring: explicit vendoring playbook -- install via
  run_terminal("npm install <pkg>"), vendor a file via web_fetch(url) +
  write_file(path, content); never urllib/subprocess/open() here.
- Sandbox denial message now carries the PIVOT, not just the block --
  the model reads exactly what to do at the moment it is told no.

38 code-exec/PTC tests green. Attempt 4 expectations: same command, fresh
RunId; npm cache warm; the strategy dead-end is now taught away.

---

# Plan-vs-task constraint validator — general, no hardcoded data (2026-08-23)

Founder correction accepted: after the test5-3 strategy failure, the WRONG
fix was another hardcoded planner rule (a Next.js-specific line was one
keystroke away -- same disease as the reverted keyword gate). What shipped
instead is a GENERAL mechanism:

`_plan_constraint_violation` asks the model to check the plan against the
TASK's own explicit constraints and answer OK or VIOLATION with the quoted
contradiction. One bounded retry with the contradiction quoted. Zero
hardcoded technology names -- the knowledge that "Next.js implies a build
step" lives in the model, where it belongs; the mechanism only moves text.

Category note (what is and is not "hardcoding"):
- environment documentation (the sandbox denial's PIVOT line, the
  execute_code docstring playbook) describes the environment's REAL
  capabilities -- that is API documentation, kept.
- task-specific or tech-specific rules in prompts -- NOT added; the
  near-miss was discarded.

Pins: 3 tests (OK path actually asks the model; contradiction is quoted;
validator failure is advisory). The first draft of test 1 passed
vacuously without patching get_llm (real provider raised -> advisory "");
the rewrite asserts the model was actually asked.

---

# TEST 5, desktop attempt 4b (test5-4b) — runtime FAIL, product FAIL (2026-08-25)

## Observed boundary

Sarvam reached a roughly 30KB `main.js` `write_file`, then the run produced no
workspace files and no `outcome.json`. The payload was far below the bridge's
1 MiB frame limit, so raising that limit was rejected as an unsupported fix.
No merge or branch deletion followed.

## Confirmed root cause

The guarded runner set `PULSEAI_AUTO_APPROVE_WRITES=1`, but the real bridge
opened an approval channel while leaving `stream_agent` at interactive policy
`ask`. An ordinary safe mutation therefore entered `approval_queue` and could
wait 300 seconds. The headless runner only recorded `safety_request`; it never
sent `safety_reply`. This is the confirmed unattended approval deadlock. An
exact desktop serialization exception was not available and is not claimed.

## Repair and no-credit proof

- guarded bridge turns explicitly select `workspace_session` approval;
- residual safety requests are always answered, with auto-approval restricted
  to warning-free workspace-contained file mutations and all other requests
  denied;
- runner transport errors still write a sanitized outcome receipt;
- Hermes-aligned guidance keeps individual tool arguments below roughly 8K
  tokens and tells the model to split rather than repeat a dropped large call;
- a deterministic 35KB write lands through the real `SafeToolNode` path;
- the focused bridge/tool/harness/prompt selection passes 79 tests, and an echo
  runner smoke completes with zero model calls and zero safety requests.

The next eligible live run is one guarded desktop attempt 5 (`test5-5`). It
must pass both runtime and independent product grading before any merge.

---

# TEST 5, attempt 5 (test5-5) — runtime FAIL, product FAIL (2026-08-25)

## Preserved desktop verdict

The guarded run reached its configured 20-LLM-call circuit breaker after the
Sarvam 105B model remained in a planning/search loop. Safety policy blocked a
`curl` download attempt. No file mutation landed and the workspace was empty,
so there was no product to grade. The operator reports approximately four
credits consumed. Evidence was preserved and PR #9 was not merged.

## What this result establishes

The attempt-4b unattended approval deadlock was repaired: attempt 5 progressed
to a different boundary. The observed failure class is now model/tool strategy
before first delivery. The summary alone does not establish that permitting
`curl` would be safe or sufficient; review the preserved frames and stderr to
determine whether the model ignored the already documented supported vendoring
pivot, repeated planning, or received misleading tool feedback.

Stop condition: no automatic rerun, no merge, and no branch deletion. Preserve
`C:\test5-ws-attempt5` and `bench-results\test5-5\` pending founder review.

## Postmortem repair (no provider calls)

The sanitized frame timeline exposed cross-tool no-progress rather than one
identical-call loop. The runtime now states Windows `cmd.exe` before execution,
rejects every listed POSIX-only verb before spawn, hides unavailable typecheck,
skips deterministic KEEP/REPLAN model calls, warns after two pre-delivery
iterations, and narrows to delivery capabilities after four until a file lands.
The exact reported direct curl command remains safety-allowed in regression;
safety was not weakened without the exact denial frame.

A separate apparent full-suite deadlock at 57% was traced with faulthandler to
Hugging Face TLS backoff: explicit `ChunkIndex(embedder=None)` accidentally
loaded the lazy default model. Explicit None is now genuinely BM25-only; the
stuck test completes in ~0.1s. See `docs/AGENT_RELIABILITY_PLAN.md`.

---

# Desktop deterministic validation of 191cbeae (2026-08-25)

Zero provider calls and zero credits. The former Hugging Face retry boundary is
fixed: the targeted index test completed in under five seconds with no network
request. Desktop assertion receipts were 69/69 for the repair selection, 93/93
for language/index/context, and 161/161 for the broader selection. Python
compile and diff checks passed; Git was clean; failed-run workspace/evidence
remained preserved.

A follow-up process-lifecycle diagnostic resolved the apparent teardown hang.
Direct `python -m pytest`, direct `pytest.exe`, an in-process `pytest.main()`,
and `Start-Process -NoNewWindow` without redirection all returned cleanly in
about 8–10 seconds for the targeted test. No non-daemon thread or child process
remained, and `pytest.main()` returned before process exit. The hang reproduced
only when Windows PowerShell 5.1 `Start-Process` redirected stdout or stderr;
it is a parent/child pipe-redirection deadlock in the diagnostic invocation,
not a pytest fixture, plugin, or Pulse runtime teardown defect. Desktop
**deterministic validation PASS** is therefore supported for these selections.

The report did not launch the IDE, so visual workbench cleanliness remains
unverified. No merge, branch deletion, live Test-5 rerun, provider call, or UI
change was performed.

---

# Test 5 Attempt 6 authorization (2026-08-25)

After the Attempt-5 postmortem repair passed deterministic desktop validation,
the founder authorized exactly one fresh guarded provider-backed run. Run ID
`test5-6`, workspace `C:\test5-ws-attempt6`, unchanged 20-call / 180k-input
circuit breakers, 30-second monitoring, immutable evidence, and independent
product grading are specified in `DESKTOP_AGENT_INSTRUCTIONS.md`. No automatic
retry is authorized. PR #9 merge and obsolete-branch cleanup remain conditional
on both runtime and product PASS.

---

# TEST 5, attempt 6 (test5-6) — operator-cancelled / product FAIL (2026-08-25)

After 16 observed LLM requests and more than 180 seconds, the workspace still
contained zero files. The model varied empty-workspace inspection across think,
list_files, cmd `dir`, and four execute_code/os.walk scripts. The founder
manually cancelled the run. Human interventions are therefore 1, regardless of
the initial report's zero. Missing `outcome.json` and `turn_done` are not proof
of a bridge crash: the runner did not catch KeyboardInterrupt, and the wrapper
used PowerShell `Start-Process` stream redirection already shown to hang.

## Confirmed guard defect

Forced delivery depended on `iteration_used`, but execute_code-only provider
turns were refunded. Worse, forced-delivery mode intentionally retained
execute_code for web_fetch->write batching. The model instead used it for
read-only os.walk, so the copied Hermes refund and broad PTC capability jointly
bypassed the cap. Hermes refunds PTC inside a larger budget/guardrail system;
copying that one behavior into Pulse's 20-call paid harness was not equivalent.

Repair direction completed: every Pulse provider request counts; varied pre-delivery tool
observations share one cap; forced delivery exposes only direct file mutations;
the paid runner cancels if no file exists by a hard request threshold; operator
cancellation always writes an outcome; and the PowerShell wrapper inherits the
console instead of redirecting Start-Process streams.

The subsequent payload-level Hermes audit identified the earlier layer that
made inspection attractive: 16,445 characters of interactive persona,
contradictory reasoning/overview/clarification context, advisory planning, a
trailing system role, and 33 initial tools / 18,070 schema characters. The
repaired autonomous first request on Windows is deterministically four messages /
3,084 content characters / one `write_file` schema (591 characters), with no
planner calls. Complete post-sanitizer payload capture is available for offline replay.
See `docs/HERMES_RUNTIME_AUDIT.md`. Focused deterministic tests pass, but no
rerun is authorized by that fact alone.
