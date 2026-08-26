# Desktop Agent Instructions — One Authorized Live Attempt 12

**Updated:** 2026-08-26

**Required branch:** `arena/01a03741-pulseairepo`

**Validated source repair:** `0370515cce811dd4d86d14379dd2729a94e640b1`

**Accepted Windows evidence:** `1b7ce9e1f48de834451abde7f0d41aaf0fac106e`

**No-probe runner commit:** `200783db6ec135022a199cf37c47fea112781a87`

**Open PR:** #9 — do not merge

## Authorization

The founder authorized exactly **one live Attempt 12** using the existing
securely configured OpenRouter model `stealth/ox-alpha`. This authorization is
consumed by the single guarded bridge turn below.

- Do not make a provider probe; use `-SkipProbe`.
- Do not retry the turn for any reason.
- Do not use a fallback provider or model.
- Do not increase any cap.
- Do not print, copy, or commit credentials.
- Provider-free product inspection after the turn is required and does not
  authorize another model call.

## Fixed locations

```text
Repository: D:\pulseAIagent\PulseAIRepo
Workspace:  C:\test5-ws-attempt12
Run ID:     test5-12-desktop
Evidence:   bench-results\test5-12-desktop
```

Use only the existing repository. The workspace and evidence directory must not
already exist. Preserve all Attempt-5 through Attempt-11 workspaces/evidence and
all failed/accepted Windows validation evidence.

## 1. Checkout and local-only configuration check

```powershell
$ErrorActionPreference = 'Stop'
cd D:\pulseAIagent\PulseAIRepo

if ((git branch --show-current) -ne 'arena/01a03741-pulseairepo') {
  throw 'Wrong branch — STOP'
}
if (git status --porcelain=v1) {
  throw 'Checkout is not clean — preserve it and STOP; never reset or clean'
}

git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
if ($LASTEXITCODE -ne 0) { throw 'Fast-forward failed — STOP' }

git merge-base --is-ancestor 0370515cce811dd4d86d14379dd2729a94e640b1 HEAD
if ($LASTEXITCODE -ne 0) { throw 'Validated repair is not an ancestor — STOP' }
git merge-base --is-ancestor 200783db6ec135022a199cf37c47fea112781a87 HEAD
if ($LASTEXITCODE -ne 0) { throw 'No-probe runner is not an ancestor — STOP' }

if (Test-Path C:\test5-ws-attempt12) { throw 'Attempt-12 workspace exists — STOP' }
if (Test-Path bench-results\test5-12-desktop) { throw 'Attempt-12 evidence exists — STOP' }

$python = if (Test-Path '.venv\Scripts\python.exe') {
  (Resolve-Path '.venv\Scripts\python.exe').Path
} else { 'python' }

# Local .env parsing only. This prints provider/model/host and a boolean, never
# the key. It sends no network request.
& $python -c "import json; from urllib.parse import urlparse; from src.config.settings import LLM_PROVIDER, LLM_MODEL, CUSTOM_BASE_URL, CUSTOM_API_KEY; host=urlparse(CUSTOM_BASE_URL or '').hostname or ''; ok=(LLM_PROVIDER=='custom' and LLM_MODEL=='stealth/ox-alpha' and host.lower()=='openrouter.ai' and bool(CUSTOM_API_KEY)); print(json.dumps({'provider':LLM_PROVIDER,'model':LLM_MODEL,'endpoint_host':host,'credential_configured':bool(CUSTOM_API_KEY)})); raise SystemExit(0 if ok else 2)"
if ($LASTEXITCODE -ne 0) { throw 'Exact authorized provider/model is not configured — STOP without probing' }
```

Do not edit `.env` and do not install dependencies in the repository.

## 2. Run exactly one guarded live turn

Use the committed prompt `scripts\test5_prompt.txt` and unchanged guards: 90
minutes, 600-second stall limit, 60 request cap, 250,000 cumulative input-token
runner cap, 12-call no-delivery stop. Pulse's internal 120,000-token and
30-iteration caps remain unchanged, including the new reserve.

```powershell
$monitorTemp = Join-Path $env:TEMP 'pulse-test5-12-monitor.log'
if (Test-Path $monitorTemp) { throw 'Monitor temp file exists — STOP' }
"$((Get-Date).ToUniversalTime().ToString('o')) ATTEMPT12_START" |
  Set-Content $monitorTemp -Encoding utf8

$heartbeat = Start-Job -ArgumentList $monitorTemp -ScriptBlock {
  param($path)
  while ($true) {
    Start-Sleep -Seconds 30
    $frames = 'D:\pulseAIagent\PulseAIRepo\bench-results\test5-12-desktop\frames.jsonl'
    $workspace = 'C:\test5-ws-attempt12'
    $requests = if (Test-Path $frames) {
      @(Select-String -Path $frames -Pattern '"type"\s*:\s*"llm.request"').Count
    } else { 0 }
    $responses = if (Test-Path $frames) {
      @(Select-String -Path $frames -Pattern '"type"\s*:\s*"llm.response"').Count
    } else { 0 }
    $files = if (Test-Path $workspace) {
      @(Get-ChildItem $workspace -Recurse -File -ErrorAction SilentlyContinue)
    } else { @() }
    $bytes = ($files | Measure-Object Length -Sum).Sum
    if ($null -eq $bytes) { $bytes = 0 }
    "$((Get-Date).ToUniversalTime().ToString('o')) HEARTBEAT requests=$requests responses=$responses files=$($files.Count) bytes=$bytes" |
      Add-Content $path
  }
}

try {
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_test5_guarded.ps1 `
    -Workspace C:\test5-ws-attempt12 `
    -Python $python `
    -RunId test5-12-desktop `
    -MaxMinutes 90 `
    -StallSeconds 600 `
    -MaxLlmCalls 60 `
    -MaxInputTokens 250000 `
    -MaxNoDeliveryCalls 12 `
    -SkipProbe
  $turnExit = $LASTEXITCODE
} finally {
  Stop-Job $heartbeat -ErrorAction SilentlyContinue
  Receive-Job $heartbeat -ErrorAction SilentlyContinue | Out-Null
  Remove-Job $heartbeat -Force -ErrorAction SilentlyContinue
}
"$((Get-Date).ToUniversalTime().ToString('o')) ATTEMPT12_END exit=$turnExit" |
  Add-Content $monitorTemp

$runDir = 'bench-results\test5-12-desktop'
if (-not (Test-Path $runDir)) { throw 'Runner produced no evidence directory — STOP' }
Move-Item $monitorTemp "$runDir\monitor.log"
```

The authorization is now consumed regardless of exit code. **Never rerun.**

## 3. Preserve the delivered product before inspection

```powershell
if (Test-Path "$runDir\workspace") { throw 'Evidence workspace already exists — STOP' }
Copy-Item C:\test5-ws-attempt12 "$runDir\workspace" -Recurse
```

Do not repair the product after the turn. Product inspection is read-only.

## 4. Provider-free integrity and trace review

Run the workspace audit and save JSON:

```powershell
& $python -c "import json; from src.context.workspace_integrity import audit_workspace; issues=audit_workspace(r'C:\test5-ws-attempt12'); print(json.dumps({'finding_count':len(issues),'findings':[{'kind':x.kind,'path':x.path,'reference':x.reference,'description':x.describe()} for x in issues]},indent=2))" |
  Set-Content "$runDir\integrity-audit.json" -Encoding utf8
```

Read `outcome.json`, `frames.jsonl`, `bridge_stderr.log`, and the copied
workspace. Create `trace-review.json` recording:

- exact `llm.request` and `llm.response` counts;
- every request model (must all be `stealth/ox-alpha`);
- probe requests: zero;
- fallback provider/model requests: zero;
- finish reasons, output-limit continuations, and budget/reserve stop status;
- tool-call starts/ends and any unpaired IDs;
- final `turn_done.completed` value and graph `task_status` if present;
- mutations after the final passing verification receipt;
- static/build receipt and browser receipt details; and
- first failed boundary, if any.

Do not call a model for this analysis.

## 5. Independent browser/product inspection

This section is provider-free. If executable files were delivered, start a
basic static server rooted at `C:\test5-ws-attempt12`, then use the Desktop
Agent's real browser automation against:

```text
http://127.0.0.1:4173/?shot=1&t=37.4&w=1920&h=1080&path=grazing&preset=photon
```

Use a local command such as:

```powershell
$server = Start-Process -FilePath $python `
  -ArgumentList '-m','http.server','4173','--directory','C:\test5-ws-attempt12' `
  -PassThru
```

Wait for rendering, then save screenshots inside `$runDir`, including the main
1920×1080 deterministic view. Exercise at least one preset, one debug view, one
parameter, pause/resume, and responsive layout. Capture browser console and
failed network requests. Stop the server in `finally`.

Create `browser-review.json` containing URL, HTTP status, title, rendered text,
canvas dimensions, non-blank screenshot result, console errors, failed requests,
interaction results, local-dependency result (no CDN/external runtime assets),
and PASS/FAIL. If no executable product exists, write a skipped/FAIL review with
the reason; do not create fake screenshots.

Create `product-review.md` against every requirement in `scripts/test5_prompt.txt`.
A visually attractive screenshot alone is not enough: shader compilation,
non-black canvas, local dependencies, interactions, and verification receipts
must all be proven.

## 6. Verdict, secret scan, hashes, commit

Create `attempt_summary.json` with the fixed repository/branch/head, repair and
runner commits, provider/model, `probe_requests: 0`, exact usage/counts, delivery
files/bytes, runtime verdict, product verdict, first failed boundary, browser
verdict, and the statement `One live Attempt 12 consumed; no retry authorized.`

Verdict rules:

- `RUNTIME_PASS` requires a paired terminal protocol, honest
  `turn_done.completed=true`, and no runner/budget/watchdog failure.
- `PRODUCT_PASS` additionally requires zero integrity findings, fresh passing
  static and real-browser receipts after the final mutation, independent browser
  PASS, no console/network/shader errors, local dependencies, and all requested
  behavior delivered.
- Otherwise report FAIL and the first concrete boundary. Never upgrade a failed
  receipt based on narrative.

Scan evidence against exact secret values loaded locally from `.env`; save only
boolean/count results to `credential-scan.json`, never secret text. Any match is
FAIL and must be removed from evidence without exposing it.

After every evidence file and screenshot is final, generate recursive SHA-256
entries for all committed evidence files except `sha256sums.txt` itself.

```powershell
git status --short
```

Only `bench-results/test5-12-desktop/` may be added. If source, tests, prompt,
historical evidence, or unrelated paths changed, preserve and STOP without
reset/clean.

```powershell
git add -f bench-results/test5-12-desktop
git commit -m "test: record guarded live Attempt 12"
git push origin arena/01a03741-pulseairepo
```

## Final response and mandatory stop

Report exact provider request/response counts, token/cost telemetry, delivery,
verification receipts, integrity findings, browser result, runtime/product/overall
verdict, evidence commit, and first failed boundary. Then:

```text
STOPPED — Attempt 12 authorization consumed; no retry or merge authorized
```

Do not merge PR #9, delete branches, start Agentic UI work, or run another
provider request.
