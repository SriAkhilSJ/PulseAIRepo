@echo off
setlocal
title Crusor Full Stack - IDE + Langfuse (agent tracing)

:: ============================================================
:: Run Crusor IDE + Langfuse (self-hosted, local-only).
::
:: Agent tracing (OpenTelemetry, hermes langfuse-plugin parity):
::   every turn = a trace: node spans (task_manager, planner, ai,
::   finish_gate...) + llm spans (model, tokens, cost) + tool spans.
:: View it at http://localhost:3000 (Tracing tab).
::
:: First run: this starts Langfuse via docker compose (needs Docker
:: Desktop running) and prints the API-key setup steps.
:: ============================================================
pushd %~dp0

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" set "VENV_PY=python"

:: --- Agent tracing (local OTLP export to Langfuse; no upload) ---
set "CRUSORAI_OTEL=on"
:: Your Langfuse project keys (UI: Settings -> API Keys). Leave blank and
:: Langfuse will reject spans until you fill them in.
if "%CRUSORAI_LANGFUSE_PUBLIC_KEY%"=="" set "CRUSORAI_LANGFUSE_PUBLIC_KEY=pk-lf-FILL-ME"
if "%CRUSORAI_LANGFUSE_SECRET_KEY%"=="" set "CRUSORAI_LANGFUSE_SECRET_KEY=sk-lf-FILL-ME"
:: set "CRUSORAI_OTEL_ENDPOINT=http://127.0.0.1:3000/api/public/otel/v1/traces"

:: --- Local telemetry ledger (turn receipts, still local JSONL) ---
set "CRUSORAI_OBSERVABILITY=on"

:: --- Desktop env (so code.bat finds python + engine) ---
set "CRUSORAI_PYTHON_PATH=%VENV_PY%"
set "CRUSORAI_ENGINE_ROOT=%~dp0."
set "VSCODE_SKIP_PRELAUNCH=1"

:: --- Start Langfuse (docker) if not already up ---
where docker >nul 2>nul
if %errorlevel%==0 (
  pushd "%~dp0langfuse"
  docker compose ps -q langfuse-web >nul 2>nul
  if %errorlevel%==0 (
    echo [1/2] Langfuse already running -> http://localhost:3000
  ) else (
    echo [1/2] Starting Langfuse (first boot takes 1-2 min)...
    docker compose up -d
  )
  popd
) else (
  echo [1/2] Docker not found - Langfuse skipped.
  echo       Install Docker Desktop, then: cd langfuse ^&^& docker compose up -d
  echo       Agent tracing will retry export in the background (fail-closed).
)

:: --- Start Crusor IDE with this repo as workspace ---
echo [2/2] Starting Crusor IDE with workspace %~dp0 ...
call "%~dp0desktop\vscode\scripts\code.bat" "%~dp0."

:: --- Open Langfuse in the browser (give the first boot a moment) ---
timeout /t 5 /nobreak >nul
start "" "http://localhost:3000"

popd
endlocal
