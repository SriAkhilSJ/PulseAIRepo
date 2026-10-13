# Crusor Full Stack - PowerShell launcher (IDE + Langfuse agent tracing)
#
# Agent tracing (OpenTelemetry, hermes langfuse-plugin parity): every turn is
# a trace - node spans + llm spans (tokens/cost) + tool spans. Local-only:
# Langfuse runs in docker on this machine; nothing is uploaded.
#
# First run starts Langfuse via docker compose; set your project keys below
# (Langfuse UI -> Settings -> API Keys) and watch http://localhost:3000.

$Repo = if ($PSScriptRoot) { $PSScriptRoot } else { (Resolve-Path ".").Path }
$VenvPy = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { $VenvPy = "python" }

# Agent tracing (local OTLP export to Langfuse; no upload)
$env:CRUSORAI_OTEL = "on"
# Your Langfuse project keys (UI: Settings -> API Keys):
# $env:CRUSORAI_LANGFUSE_PUBLIC_KEY = "pk-lf-..."
# $env:CRUSORAI_LANGFUSE_SECRET_KEY = "sk-lf-..."
# $env:CRUSORAI_OTEL_ENDPOINT = "http://127.0.0.1:3000/api/public/otel/v1/traces"

# Local telemetry ledger (turn receipts, local JSONL)
$env:CRUSORAI_OBSERVABILITY = "on"

# Desktop env
$env:CRUSORAI_PYTHON_PATH = $VenvPy
$env:CRUSORAI_ENGINE_ROOT = (Join-Path $Repo ".")
$env:VSCODE_SKIP_PRELAUNCH = "1"

# 1/2 - Langfuse (docker) if not already up
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Push-Location (Join-Path $Repo "langfuse")
    $running = docker compose ps -q langfuse-web 2>$null
    if ($running) {
        Write-Host "[1/2] Langfuse already running -> http://localhost:3000"
    } else {
        Write-Host "[1/2] Starting Langfuse (first boot takes 1-2 min)..."
        docker compose up -d
    }
    Pop-Location
} else {
    Write-Host "[1/2] Docker not found - Langfuse skipped."
    Write-Host "       Install Docker Desktop, then: cd langfuse; docker compose up -d"
    Write-Host "       Tracing export retries in the background (fail-closed)."
}

# 2/2 - Crusor IDE with this repo as workspace
Write-Host "[2/2] Starting Crusor IDE with workspace $Repo ..."
$code = Join-Path $Repo "desktop\vscode\scripts\code.bat"
if (Test-Path $code) { & $code (Join-Path $Repo ".") }

# Open Langfuse (give the first boot a moment)
Start-Sleep -Seconds 5
Start-Process "http://localhost:3000"
