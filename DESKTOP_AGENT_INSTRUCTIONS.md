# Desktop Agent Instructions — RUN exactly one Test 5 desktop attempt

**Founder instruction:** 2026-08-25

**Repository:** `https://github.com/SriAkhilSJ/PulseAIRepo`

**Branch:** `arena/01a03741-pulseairepo`

**Required baseline:** commit `13a16bb7` or newer on this exact branch

**PR:** `https://github.com/SriAkhilSJ/PulseAIRepo/pull/9`

> Run exactly one provider-backed desktop attempt and monitor it every 30
> seconds. Do not retry for any reason. Afterward, preserve and report all
> evidence. Do not merge PR #9, delete branches, or begin Agentic UI work.

## Fixed attempt identity and limits

- Run ID: `test5-8-desktop`
- Fresh workspace: `C:\test5-ws-attempt8`
- Evidence directory: `bench-results\test5-8-desktop\`
- Provider request cap: 20
- Input-token cap: 180,000
- No-file cap: 12 provider requests
- Monitoring interval: 30 seconds
- Silence watchdog: 600 seconds
- Hard timeout: 90 minutes
- Automatic retries of the whole run: **zero**

Preserve all earlier workspaces/evidence, including:

```text
C:\test5-ws-attempt5
C:\test5-ws-attempt6
bench-results\test5-5\
bench-results\test5-6\
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
```

## 1. Sync without losing local work

From the Windows repository root:

```powershell
git status --short
```

If tracked files are dirty, stop and report them. Do not stash, reset, clean, or
overwrite founder work. Ignored `.env`, `.venv`, desktop builds, and old
`bench-results` are expected.

```powershell
git fetch origin
git checkout arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
git log --oneline -1
```

The checked-out commit must be `13a16bb7` or newer on this branch.

Confirm the attempt paths are fresh:

```powershell
if (Test-Path 'C:\test5-ws-attempt8') {
  throw 'STOP: C:\test5-ws-attempt8 already exists; do not reuse it'
}
if (Test-Path 'bench-results\test5-8-desktop') {
  throw 'STOP: attempt evidence already exists; do not overwrite it'
}
```

The existing `.env` must contain the configured Sarvam credential. Never print,
paste, log, commit, or report that key. If `.env` or the key is missing, stop;
do not improvise another credential.

## 2. Run once

Execute exactly once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_test5_guarded.ps1 `
  -Workspace 'C:\test5-ws-attempt8' `
  -RunId 'test5-8-desktop' `
  -MaxLlmCalls 20 `
  -MaxInputTokens 180000 `
  -MaxNoDeliveryCalls 12 `
  -StallSeconds 600 `
  -MaxMinutes 90
```

The wrapper's eight-token connectivity probe is part of this single attempt.
If it fails, report `PREFLIGHT_CONNECTIVITY_FAIL` and stop. Do not rerun the
probe or command.

## 3. Monitor every 30 seconds

Stay attached to the process. The wrapper emits `[watchdog]` every 30 seconds.
At each interval record:

1. elapsed and idle seconds;
2. current `llm.request` count from runner output;
3. workspace file count and total bytes;
4. latest tool name/status, if any;
5. whether the first real file has landed;
6. safety requests, errors, budget/no-delivery stops, or cancellation.

Use this read-only command in a second PowerShell window at each interval if the
wrapper line does not show file totals:

```powershell
$files = @(Get-ChildItem 'C:\test5-ws-attempt8' -Recurse -File -ErrorAction SilentlyContinue)
$bytes = ($files | Measure-Object Length -Sum).Sum
Write-Host "files=$($files.Count) bytes=$bytes"
```

Do not manually cancel because generation is merely quiet. The 600-second
silence watchdog, 12-request no-file breaker, 20-request total cap, and hard
timeout own termination. Manually stop only for an obvious safety incident or
uncontrolled requests beyond those breakers; count that as one human
intervention.

## 4. Preserve runtime evidence

After the process exits, do not rerun it. Capture:

```powershell
Get-Content 'bench-results\test5-8-desktop\outcome.json'
Get-Content 'bench-results\test5-8-desktop\bridge_stderr.log' -Tail 100
Get-ChildItem 'C:\test5-ws-attempt8' -Recurse -File |
  Select-Object FullName, Length, LastWriteTime
```

Inspect `bench-results\test5-8-desktop\frames.jsonl` locally. Report only
metadata, never complete payload text:

- counts of `llm.request`, `tool_call_start`, `tool_call_end`,
  `safety_request`, `verification_updated`, `turn_done`, and `turn_failed`;
- first request model, message roles/count, message characters, tool names,
  tool count/schema characters, and request SHA-256;
- whether the first visible tool surface was exactly `write_file`;
- whether any system role followed the human task (expected: no);
- ordered tool names and success/failure statuses.

## 5. Independently grade the product without provider calls

A `turn_done` frame is not a product pass. Grade the untouched workspace against
`scripts\test5_prompt.txt`. Do not repair Pulse's output manually.

Verify at minimum:

1. executable HTML/CSS/JavaScript and startup instructions exist;
2. Three.js and dependencies are local—no runtime CDN dependency;
3. it runs from a basic static server without a build step;
4. a real browser renders a non-black frame without unhandled console errors;
5. rendering is fragment-shader/Schwarzschild-geodesic based, not image,
   video, texture, or mesh fakery;
6. four presets, 21 live parameters, debug views 0–9, hotkeys, three quality
   profiles, persistence, WebGL recovery, and deterministic screenshot mode
   exist and function;
7. the requested event horizon, photon ring, multi-crossing disk, starfield,
   Milky Way, Doppler/redshift/turbulence, bloom, ACES, vignette, grain, and
   chromatic aberration are implemented;
8. OrbitControls, cinematic paths, telemetry HUD, responsive/Retina behavior,
   and optional synchronized audio are present as requested.

Store independent screenshot and browser-console evidence under:

```text
bench-results\test5-8-desktop\product-grade\
```

## 6. Final report and mandatory stop

Report:

- verdict: `PASS`, `RUNTIME_FAIL`, `PRODUCT_FAIL`, or
  `RUNTIME_AND_PRODUCT_FAIL`;
- exact 30-second timeline;
- complete `outcome.json` excluding secrets;
- frame counts and bounded first-request metadata;
- ordered tool outcomes;
- file inventory and total bytes;
- independent checklist results and screenshot/console evidence paths;
- provider request count and all stop flags;
- human intervention count;
- final `git status --short`.

Then stop. No second attempt, PR merge, branch deletion, source repair, or
Agentic UI work is authorized.
