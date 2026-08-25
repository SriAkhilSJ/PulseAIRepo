# run_test5_guarded.ps1 - Test 5 (GARGANTUA) through the real bridge, guarded.
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
    [int]$StallSeconds = 600,
    [int]$MaxLlmCalls = 60,
    [int]$MaxInputTokens = 250000,
    [int]$MaxNoDeliveryCalls = 12
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
if ($LASTEXITCODE -ne 0) { Write-Host "[probe] FAILED - test NOT started." -ForegroundColor Red; exit 2 }

# Hermes alignment for long build turns: STREAM the provider (first token
# arrives in seconds; the timeout then guards stalls, not total generation
# length) and give big generations room. Pre-set env values win.
if (-not $env:PULSEAI_LLM_STREAMING) { $env:PULSEAI_LLM_STREAMING = "1" }
if (-not $env:PULSEAI_LLM_TIMEOUT)   { $env:PULSEAI_LLM_TIMEOUT = "280" }

# Long build turn: the driver itself records every protocol frame and bridge
# stderr in the run directory. Do NOT use PowerShell 5.1 Start-Process stream
# redirection here: desktop diagnostics proved its redirected parent/child
# path can deadlock even when the child exits cleanly. Inherit the console so
# output is drained live; the watchdog uses immutable run/workspace files.
$proc = Start-Process -FilePath $Python `
    -ArgumentList "scripts\run_bridge_turn.py", "--workspace", $Workspace, `
                  "--prompt-file", "scripts\test5_prompt.txt", `
                  "--run-id", $RunId, "--timeout-s", ($MaxMinutes * 60 - 120), `
                  "--max-llm-calls", $MaxLlmCalls, `
                  "--max-input-tokens", $MaxInputTokens, `
                  "--max-no-delivery-calls", $MaxNoDeliveryCalls `
    -NoNewWindow -PassThru

$started = Get-Date
$deadline = $started.AddMinutes($MaxMinutes)
$lastActivity = $started
$epoch = Get-Date "2000-01-01"
while (-not $proc.HasExited) {
    Start-Sleep -Seconds 30
    $now = Get-Date
    if ($now -gt $deadline) {
        & taskkill /T /F /PID $proc.Id 2>&1 | Out-Null
        Write-Host "[watchdog] hard cap $MaxMinutes min exceeded - killed." -ForegroundColor Red; exit 3
    }
    $newest = $epoch
    if (Test-Path $RunDir) {
        Get-ChildItem $RunDir -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.LastWriteTime -gt $newest) { $newest = $_.LastWriteTime }
        }
    }
    # The WORKSPACE is activity too: a long npm install writes thousands of
    # files there while emitting no frames (test5-2 was killed mid-install
    # at 5/8 steps -- healthy, just quiet). Any file younger than the stall
    # window anywhere under the workspace counts as a heartbeat.
    if (Test-Path $Workspace) {
        $wsNewest = Get-ChildItem $Workspace -Recurse -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($wsNewest -and ($wsNewest.LastWriteTime -gt $newest)) { $newest = $wsNewest.LastWriteTime }
    }
    # CPU is activity: a busy build burns cycles even when files are quiet.
    try {
        $cpu = (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue).CPU
        if ($null -ne $script:LastCpu -and $null -ne $cpu -and ($cpu - $script:LastCpu) -gt 0.5) {
            $lastActivity = $now
        }
        $script:LastCpu = $cpu
    } catch { }
    if ($newest -gt $lastActivity) { $lastActivity = $newest }
    $idle = ($now - $lastActivity).TotalSeconds
    Write-Host ("[watchdog] +{0:n0}s alive pid={1} idle={2:n0}s" -f ($now - $started).TotalSeconds, $proc.Id, $idle)
    if ($idle -gt $StallSeconds) {
        & taskkill /T /F /PID $proc.Id 2>&1 | Out-Null
        Write-Host "[watchdog] STALLED ${idle}s - killed." -ForegroundColor Red; exit 3
    }
}

Write-Host "[run] exited with code $($proc.ExitCode)"
if (Test-Path "$RunDir\outcome.json") { Get-Content "$RunDir\outcome.json" }
& $Python scripts\analyze_llm_requests.py --help *> $null 2>&1
exit $proc.ExitCode
