# run_paid_pbr002_guarded.ps1 — first paid benchmark row, with a watchdog.
#
# What it does (in order):
#   0. Preflight: python venv + .env key present, tiny PBR-002 fixture built.
#   1. Credit gate: ONE 8-token probe (~0.1 credit). If the key/provider is
#      not healthy the script STOPS HERE — the benchmark never starts, so a
#      bad key cannot burn your afternoon or your credits.
#   2. Runs PBR-002 on the real engine (bridge lane) as a separate process.
#   3. Watchdog: checks every 30 seconds.
#        - process finished?  -> collect result
#        - no output/artifact activity for 120 s? -> KILL the tree (stall)
#        - overall cap (-MaxMinutes, default 10)? -> KILL the tree
#      Killing uses taskkill /T /F so the python engine and every child die.
#   4. Prints the graded checks + token/cost usage from the run artifacts.
#
# Usage (in the repo, on YOUR machine):
#   powershell -ExecutionPolicy Bypass -File scripts\run_paid_pbr002_guarded.ps1 -Workspace C:\pbr002-ws
#
# Optional:
#   -Python .venv\Scripts\python.exe   (default) repo venv used for the engine
#   -RunId founder-pbr002-1            (default) artifact dir under bench-results\
#   -MaxMinutes 10                     (default) hard cap before kill
#   -SkipProbe                         skip the 8-token credit gate (NOT recommended)

param(
    [Parameter(Mandatory = $true)][string]$Workspace,
    [string]$Python = ".venv\Scripts\python.exe",
    [string]$RunId = "founder-pbr002-1",
    [int]$MaxMinutes = 10,
    [switch]$SkipProbe
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Kill-Tree([int]$ProcId) {
    Write-Host "[watchdog] KILLING process tree pid=$ProcId" -ForegroundColor Red
    & taskkill /T /F /PID $ProcId 2>&1 | Out-Null
    Start-Sleep -Seconds 2
}

# ---------------------------------------------------------------- 0. preflight
if (-not (Test-Path $Python)) { Write-Host "PREFLIGHT FAIL: python not found at $Python" -ForegroundColor Red; exit 2 }
if (-not (Test-Path ".env"))  { Write-Host "PREFLIGHT FAIL: .env missing (put CUSTOM_API_KEY in .env — NEVER in README)" -ForegroundColor Red; exit 2 }

$Workspace = [System.IO.Path]::GetFullPath($Workspace)
New-Item -ItemType Directory -Force -Path (Join-Path $Workspace "notes"), (Join-Path $Workspace "data") | Out-Null

# Exact PBR-002 fixture content (benchmarks/pulse_reliability_v1/fixtures.json).
# Single-quoted here-strings: literal text, no escaping; LF-normalised below.
$proofContent = @'
"""Workspace identity proof for PBR-002."""
PROOF = "workspace_proof.py-exact-root"
MARKER = "exact-workspace"
'@
$notesContent = @'
PBR-002 exact-workspace fixture.
This folder is the ONLY opened workspace for the turn.
'@
$csvContent = @'
id,value
1,alpha
2,beta
'@
$lf = [char]10
[IO.File]::WriteAllText((Join-Path $Workspace "workspace_proof.py"), ($proofContent -replace "`r`n", $lf))
[IO.File]::WriteAllText((Join-Path $Workspace "notes\README.md"),    ($notesContent  -replace "`r`n", $lf))
[IO.File]::WriteAllText((Join-Path $Workspace "data\input.csv"),     ($csvContent   -replace "`r`n", $lf))
Write-Host "[preflight] fixture ready at $Workspace"

# ------------------------------------------------------------- 1. credit gate
if (-not $SkipProbe) {
    Write-Host "[probe] one 8-token call to Sarvam (~0.1 credit)..."
    $probePy = @'
import json, time, urllib.request
key = ""
for line in open(".env", encoding="utf-8"):
    if line.startswith("CUSTOM_API_KEY="):
        key = line.strip().split("=", 1)[1]
if not key:
    raise SystemExit("NO KEY in .env")
body = json.dumps({"model": "sarvam-105b-conversations",
                   "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                   "max_tokens": 8, "temperature": 0}).encode()
req = urllib.request.Request("https://api.sarvam.ai/v1/chat/completions", data=body,
                             headers={"Authorization": "Bearer " + key,
                                      "Content-Type": "application/json"})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print("PROBE_OK HTTP", r.status, "in %.2fs" % (time.time() - t0))
except Exception as e:
    print("PROBE_FAIL", type(e).__name__, str(e)[:200])
    raise SystemExit(1)
'@
    & $Python -c $probePy
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[probe] FAILED — benchmark NOT started. Zero benchmark credits spent." -ForegroundColor Red
        exit 2
    }
}

# ------------------------------------------------------------ 2. run + 3. watch
$LogOut = Join-Path $env:TEMP "$RunId.out.log"
$LogErr = Join-Path $env:TEMP "$RunId.err.log"
$RunDir = Join-Path $RepoRoot "bench-results\$RunId"

# Never silently overwrite graded evidence: a re-run with the same id would
# destroy the previous run's artifacts (it happened once — run A's 7-call
# evidence was lost to a re-run). Fail fast with the fix in the message.
if (Test-Path $RunDir) {
    Write-Host "RUN-ID CONFLICT: $RunDir already exists (graded evidence)." -ForegroundColor Red
    Write-Host "Re-run with a fresh id, e.g.: -RunId $RunId-$(Get-Date -Format HHmmss)" -ForegroundColor Yellow
    exit 2
}

Write-Host "[run] PBR-002 bridge lane starting (watchdog: 30s checks, kill on stall)..."
$proc = Start-Process -FilePath $Python `
    -ArgumentList "-m", "benchmarks.pulse_reliability_v1.harness", "run",
                  "--task", "PBR-002", "--driver", "bridge",
                  "--workspace", $Workspace, "--python", $Python,
                  "--run-id", $RunId `
    -NoNewWindow -PassThru -RedirectStandardOutput $LogOut -RedirectStandardError $LogErr

$started = Get-Date
$deadline = $started.AddMinutes($MaxMinutes)
$lastActivity = $started
$stallSeconds = 120
$epoch = Get-Date "2000-01-01"

while (-not $proc.HasExited) {
    Start-Sleep -Seconds 30
    $now = Get-Date
    if ($now -gt $deadline) {
        Kill-Tree $proc.Id
        Write-Host "[watchdog] hard cap $MaxMinutes min exceeded — killed." -ForegroundColor Red
        exit 3
    }

    # newest write across the logs + run artifacts = last sign of life
    $newest = $epoch
    foreach ($f in @($LogOut, $LogErr)) {
        if ((Test-Path $f) -and ((Get-Item $f).LastWriteTime -gt $newest)) { $newest = (Get-Item $f).LastWriteTime }
    }
    if (Test-Path $RunDir) {
        Get-ChildItem $RunDir -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.LastWriteTime -gt $newest) { $newest = $_.LastWriteTime }
        }
    }
    if ($newest -gt $lastActivity) { $lastActivity = $newest }

    $idle = ($now - $lastActivity).TotalSeconds
    $elapsed = ($now - $started).TotalSeconds
    Write-Host ("[watchdog] +{0:n0}s alive pid={1} idle={2:n0}s" -f $elapsed, $proc.Id, $idle)
    if ($idle -gt $stallSeconds) {
        Kill-Tree $proc.Id
        Write-Host "[watchdog] STALLED for ${idle}s with zero output — killed. stderr tail:" -ForegroundColor Red
        if (Test-Path $LogErr) { Get-Content $LogErr -Tail 15 }
        exit 3
    }
}

# ------------------------------------------------------------------- 4. report
Write-Host "[run] process exited with code $($proc.ExitCode)"
if (Test-Path "$RunDir\result.md") {
    Write-Host "`n===== GRADED RESULT =====" -ForegroundColor Green
    Get-Content "$RunDir\result.md"
    Write-Host "`n===== run stdout (tail) ====="
    if (Test-Path $LogOut) { Get-Content $LogOut -Tail 10 }
} else {
    Write-Host "No graded artifacts — printing stderr tail:" -ForegroundColor Yellow
    if (Test-Path $LogErr) { Get-Content $LogErr -Tail 25 }
}
exit $proc.ExitCode
