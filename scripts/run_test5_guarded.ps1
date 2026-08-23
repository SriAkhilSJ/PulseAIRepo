# run_test5_guarded.ps1 — Test 5 (GARGANTUA) through the real bridge, guarded.
#
# Watchdog: 30s checks; kills the tree after 300s of total silence or at the
# hard cap (90 min). Every frame recorded; analyzer runs at the end.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\run_test5_guarded.ps1 -Workspace C:\test5-ws

param(
    [Parameter(Mandatory = $true)][string]$Workspace,
    [string]$Python = ".venv\Scripts\python.exe",
    [string]$RunId = "test5-1",
    [int]$MaxMinutes = 90,
    [int]$StallSeconds = 300,
    [int]$MaxLlmCalls = 60,
    [int]$MaxInputTokens = 250000
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

if (-not (Test-Path $Python)) { Write-Host "PREFLIGHT FAIL: python not found at $Python" -ForegroundColor Red; exit 2 }
if (-not (Test-Path ".env"))  { Write-Host "PREFLIGHT FAIL: .env missing (CUSTOM_API_KEY lives there)" -ForegroundColor Red; exit 2 }
$RunDir = Join-Path $RepoRoot "bench-results\$RunId"
if (Test-Path $RunDir) {
    Write-Host "RUN-ID CONFLICT: $RunDir exists. Use a fresh -RunId." -ForegroundColor Red; exit 2
}
$Workspace = [System.IO.Path]::GetFullPath($Workspace)
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
Write-Host "[preflight] workspace ready at $Workspace"

# Credit gate: ONE 8-token probe. Bad provider = no test started.
$probePy = Join-Path $env:TEMP "pulse_probe.py"
@"
import json, time, urllib.request
key = ""
for line in open(".env", encoding="utf-8"):
    if line.startswith("CUSTOM_API_KEY="):
        key = line.strip().split("=", 1)[1]
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
    print("PROBE_FAIL", type(e).__name__, str(e)[:200]); raise SystemExit(1)
"@ | Set-Content -Encoding UTF8 $probePy
& $Python $probePy
if ($LASTEXITCODE -ne 0) { Write-Host "[probe] FAILED — test NOT started." -ForegroundColor Red; exit 2 }

# Long build turn: the driver records every frame; watchdog watches the run dir.
$LogOut = Join-Path $env:TEMP "$RunId.out.log"
$proc = Start-Process -FilePath $Python `
    -ArgumentList "scripts\run_bridge_turn.py", "--workspace", $Workspace, `
                  "--prompt-file", "scripts\test5_prompt.txt", `
                  "--run-id", $RunId, "--timeout-s", ($MaxMinutes * 60 - 120), `
                  "--max-llm-calls", $MaxLlmCalls, `
                  "--max-input-tokens", $MaxInputTokens `
    -NoNewWindow -PassThru -RedirectStandardOutput $LogOut -RedirectStandardError (Join-Path $env:TEMP "$RunId.err.log")

$started = Get-Date
$deadline = $started.AddMinutes($MaxMinutes)
$lastActivity = $started
$epoch = Get-Date "2000-01-01"
while (-not $proc.HasExited) {
    Start-Sleep -Seconds 30
    $now = Get-Date
    if ($now -gt $deadline) {
        & taskkill /T /F /PID $proc.Id 2>&1 | Out-Null
        Write-Host "[watchdog] hard cap $MaxMinutes min exceeded — killed." -ForegroundColor Red; exit 3
    }
    $newest = $epoch
    if ((Test-Path $LogOut) -and ((Get-Item $LogOut).LastWriteTime -gt $newest)) { $newest = (Get-Item $LogOut).LastWriteTime }
    if (Test-Path $RunDir) {
        Get-ChildItem $RunDir -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.LastWriteTime -gt $newest) { $newest = $_.LastWriteTime }
        }
    }
    if ($newest -gt $lastActivity) { $lastActivity = $newest }
    $idle = ($now - $lastActivity).TotalSeconds
    Write-Host ("[watchdog] +{0:n0}s alive pid={1} idle={2:n0}s" -f ($now - $started).TotalSeconds, $proc.Id, $idle)
    if ($idle -gt $StallSeconds) {
        & taskkill /T /F /PID $proc.Id 2>&1 | Out-Null
        Write-Host "[watchdog] STALLED ${idle}s — killed." -ForegroundColor Red; exit 3
    }
}

Write-Host "[run] exited with code $($proc.ExitCode)"
if (Test-Path "$RunDir\outcome.json") { Get-Content "$RunDir\outcome.json" }
if (Test-Path $LogOut) { Write-Host "`n===== driver tail ====="; Get-Content $LogOut -Tail 15 }
& $Python scripts\analyze_llm_requests.py --help *> $null 2>&1
exit $proc.ExitCode
