# Crusor Full Stack — PowerShell launcher (IDE + AgentOps + Engine)
# Hermes parity: separate frontends, one command to run both
# Improvisation plan: agentops/improvisation_plan.json (you will provide)

$Repo = $PSScriptRoot
if (-not $Repo) { $Repo = (Resolve-Path ".").Path }
$VenvPy = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { $VenvPy = "python" }
$AgentOpsPy = Join-Path $Repo "agentops\.venv\Scripts\python.exe"
if (-not (Test-Path $AgentOpsPy)) { $AgentOpsPy = $VenvPy }

# Engine env
$env:PULSEAI_OBSERVABILITY = "on"
$env:CRUSORAI_OBSERVABILITY = "on"
$env:CRUSORAI_MEMORY = "on"

# AgentOps env — let auto-detect (prefers ~/.crusorai, fallback ~/.pulseai)
# don't force CRUSORAI_OPS_DATA_DIR — remove legacy force
Remove-Item Env:CRUSORAI_OPS_DATA_DIR -ErrorAction SilentlyContinue
$env:CRUSORAI_OPS_HOST = "127.0.0.1"
$env:CRUSORAI_OPS_PORT = "8300"

# Desktop env
$resolved = $null
try { $resolved = (Resolve-Path $VenvPy -ErrorAction SilentlyContinue).Path } catch {}
if ($resolved) { $env:CRUSORAI_PYTHON_PATH = $resolved } else { $env:CRUSORAI_PYTHON_PATH = $VenvPy }
$env:CRUSORAI_ENGINE_ROOT = $Repo
$env:VSCODE_SKIP_PRELAUNCH = "1"

# Show improvisation plan if present
$PlanJson = Join-Path $Repo "agentops\improvisation_plan.json"
$PlanMd = Join-Path $Repo "agentops\improvisation_plan.md"
if (Test-Path $PlanJson) { Write-Host "[AgentOps] Found plan: $PlanJson" -ForegroundColor Cyan; Get-Content $PlanJson | Write-Host }
elseif (Test-Path $PlanMd) { Write-Host "[AgentOps] Found plan: $PlanMd" -ForegroundColor Cyan; Get-Content $PlanMd | Write-Host }
else { Write-Host "[AgentOps] No improvisation_plan.json/.md yet - running with defaults." -ForegroundColor Yellow }

# Start AgentOps backend (new window)
$opsUrl = "http://$env:CRUSORAI_OPS_HOST`:$env:CRUSORAI_OPS_PORT"
Write-Host "[1/2] Starting AgentOps on $opsUrl ..." -ForegroundColor Green
Start-Process -FilePath $AgentOpsPy -ArgumentList "-m backend.app" -WorkingDirectory (Join-Path $Repo "agentops") -WindowStyle Normal
Start-Sleep -Seconds 3

# Build web/dist if missing
if (-not (Test-Path (Join-Path $Repo "agentops\web\dist\index.html"))) {
  Write-Host "[AgentOps] Building web/dist..." -ForegroundColor Yellow
  Push-Location (Join-Path $Repo "agentops\web")
  npm run build
  Pop-Location
}

# Launch IDE
Write-Host "[2/2] Starting Crusor IDE..." -ForegroundColor Green
& (Join-Path $Repo "desktop\vscode\scripts\code.bat") $Repo

# Open browser
$opsUrl2 = "http://$env:CRUSORAI_OPS_HOST`:$env:CRUSORAI_OPS_PORT"
Start-Process $opsUrl2
