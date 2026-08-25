# Desktop Agent Instructions — RUN exactly one Test 5 desktop attempt

**Founder instruction:** 2026-08-25

**Repository:** `https://github.com/SriAkhilSJ/PulseAIRepo`

**Branch:** `arena/01a03741-pulseairepo`

**Required baseline:** commit `00cf8be2` or newer on this exact branch

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

The checked-out commit must be `00cf8be2` or newer on this branch.

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

## 2. Run once and capture the complete console

Use a transcript outside the run directory during startup because the guarded
runner correctly rejects a pre-existing evidence directory. Execute this block
exactly once:

```powershell
$ConsoleLog = Join-Path $env:TEMP 'test5-8-desktop-console.log'
$MonitorLog = Join-Path $env:TEMP 'test5-8-monitor-30s.jsonl'
if ((Test-Path $ConsoleLog) -or (Test-Path $MonitorLog)) {
  throw 'STOP: stale attempt-8 console/monitor evidence exists in TEMP'
}
$RunExit = 999
Start-Transcript -Path $ConsoleLog -NoClobber
try {
  powershell -ExecutionPolicy Bypass -File scripts\run_test5_guarded.ps1 `
    -Workspace 'C:\test5-ws-attempt8' `
    -RunId 'test5-8-desktop' `
    -MaxLlmCalls 20 `
    -MaxInputTokens 180000 `
    -MaxNoDeliveryCalls 12 `
    -StallSeconds 600 `
    -MaxMinutes 90
  $RunExit = $LASTEXITCODE
} finally {
  Stop-Transcript
}
New-Item -ItemType Directory -Force -Path 'bench-results\test5-8-desktop' | Out-Null
Move-Item -LiteralPath $ConsoleLog `
  -Destination 'bench-results\test5-8-desktop\desktop-console.log'
if (Test-Path $MonitorLog) {
  Move-Item -LiteralPath $MonitorLog `
    -Destination 'bench-results\test5-8-desktop\monitor-30s.jsonl'
}
Write-Host "guarded run exit=$RunExit"
```

The wrapper's eight-token connectivity probe is part of this single attempt.
If it fails, record `PREFLIGHT_CONNECTIVITY_FAIL`, preserve the transcript, and
stop. Do not rerun the probe or command. `desktop-console.log` must contain all
watchdog and runner output needed for later verification.

## 3. Monitor every 30 seconds

Stay attached to the process and **actively read the newly emitted output every
30 seconds**. Do not start the command and return only after it finishes. The
wrapper emits `[watchdog]` every 30 seconds, while the inherited runner console
prints every protocol event. Confirm each interval is present in
`desktop-console.log` and maintain an exact timestamped timeline.

At every 30-second interval record:

1. wall-clock timestamp plus elapsed and idle seconds;
2. all new output since the previous interval;
3. current `llm.request` count from runner output;
4. workspace file count and total bytes;
5. latest tool name/status, if any;
6. whether the first real file has landed;
7. safety requests, errors, budget/no-delivery stops, or cancellation.

Missing an interval is a monitoring failure and must be reported honestly; do
not reconstruct or invent it afterward. In the monitoring PowerShell window,
append one JSON object per observed interval to
`$env:TEMP\test5-8-monitor-30s.jsonl`. Use actual observed values:

```powershell
[pscustomobject]@{
  timestamp = (Get-Date).ToString('o')
  elapsed_seconds = 30  # replace at each interval: 30, 60, 90, ...
  idle_seconds = 0      # replace from the watchdog line
  new_output = @('verbatim new bounded console lines since prior interval')
  llm_requests = 0      # replace
  workspace_files = 0   # replace
  workspace_bytes = 0   # replace
  latest_tool = $null   # replace when present
  latest_tool_status = $null
  file_landed = $false
  stop_or_error = $null
} | ConvertTo-Json -Compress | Add-Content `
  (Join-Path $env:TEMP 'test5-8-monitor-30s.jsonl') -Encoding utf8
```

Do not put API keys or full captured request payloads into the timeline.

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

## 6. Copy, sanitize, commit, and push all evidence

The Arena agent cannot inspect files that remain only on the desktop. Copy the
untouched delivered workspace into the run evidence, then commit and push the
complete run. Include **all JSON, JSONL, logs, monitoring output, screenshots,
browser-console captures, grading notes, manifests, and delivered source**.
Do not cherry-pick or selectively omit failed evidence.

```powershell
$Evidence = 'bench-results\test5-8-desktop'
$Delivered = Join-Path $Evidence 'workspace-delivery'
New-Item -ItemType Directory -Force -Path $Delivered | Out-Null
Copy-Item -Path 'C:\test5-ws-attempt8\*' -Destination $Delivered `
  -Recurse -Force -ErrorAction SilentlyContinue

git status --short | Out-File `
  (Join-Path $Evidence 'git-status-before-evidence.txt') -Encoding utf8
Get-ChildItem $Evidence -Recurse -File | ForEach-Object {
  [pscustomobject]@{
    path = $_.FullName.Substring((Resolve-Path $Evidence).Path.Length + 1)
    bytes = $_.Length
    sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
  }
} | ConvertTo-Json -Depth 4 | Out-File `
  (Join-Path $Evidence 'evidence-manifest.json') -Encoding utf8
```

Before staging, prove the configured credential did not enter any evidence.
This check prints only matching file paths, never the key:

```powershell
$keyLine = Get-Content '.env' | Where-Object { $_ -match '^CUSTOM_API_KEY=' } |
  Select-Object -First 1
if (-not $keyLine) { throw 'STOP: cannot perform evidence credential scan' }
$key = ($keyLine -split '=', 2)[1].Trim()
$leaks = Get-ChildItem $Evidence -Recurse -File |
  Where-Object { $_.Extension -in '.json','.jsonl','.log','.txt','.md','.html','.js','.css' } |
  Select-String -SimpleMatch $key -List
$key = $null
if ($leaks) {
  $leaks | ForEach-Object { Write-Host "CREDENTIAL LEAK PATH: $($_.Path)" }
  throw 'STOP: remove/redact credentials before any commit; never print the value'
}
```

Check for unexpectedly large files. Commit normal product dependencies and
screenshots, but GitHub rejects individual files at 100 MB. If any file is 95 MB
or larger, stop before staging and report its path, size, and SHA-256; do not
silently omit or rewrite it.

```powershell
$tooLarge = Get-ChildItem $Evidence -Recurse -File |
  Where-Object { $_.Length -ge 95MB }
if ($tooLarge) {
  $tooLarge | Select-Object FullName, Length
  throw 'STOP: evidence contains a GitHub-incompatible large file'
}
```

`bench-results/` is intentionally ignored during ordinary development, so this
one immutable evidence directory must be force-added explicitly:

```powershell
git add -f -- 'bench-results/test5-8-desktop'
git diff --cached --name-only
```

The staged list must contain only `bench-results/test5-8-desktop/**`. It must
include at least `desktop-console.log`, `frames.jsonl`, `bridge_stderr.log`,
`outcome.json`, `evidence-manifest.json`, the exact 30-second timeline,
`workspace-delivery/**`, and `product-grade/**` when those files exist. If the
run failed before one of the standard files was created, add a short
`missing-evidence.json` naming the absent file and the observed reason rather
than fabricating it.

Commit and push to the session branch so Arena can verify everything:

```powershell
git commit -m "evidence: preserve Test 5 desktop attempt 8"
git push origin arena/01a03741-pulseairepo
git rev-parse HEAD
git status --short
```

If commit or push fails, do not rerun Test 5. Preserve the local evidence and
report the Git/GitHub error. Never add `.env`, the temporary probe script,
credentials, prior runs, or unrelated local files.

## 7. Final report and mandatory stop

Only after the evidence push succeeds, report:

- verdict: `PASS`, `RUNTIME_FAIL`, `PRODUCT_FAIL`, or
  `RUNTIME_AND_PRODUCT_FAIL`;
- exact 30-second timeline and confirmation that every interval's new output
  was actively inspected;
- complete `desktop-console.log` and `outcome.json` evidence paths;
- complete `outcome.json` excluding secrets;
- frame counts and bounded first-request metadata;
- ordered tool outcomes;
- file inventory and total bytes;
- independent checklist results and screenshot/console evidence paths;
- provider request count and all stop flags;
- human intervention count;
- evidence commit SHA and successful push receipt;
- final `git status --short`.

Then stop. No second attempt, PR merge, branch deletion, source repair, or
Agentic UI work is authorized.
