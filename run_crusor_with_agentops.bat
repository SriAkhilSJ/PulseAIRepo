@echo off
setlocal
title Crusor Full Stack — IDE + AgentOps + Engine

:: ============================================================
:: Run Crusor IDE (code.bat) + AgentOps (observable dashboard)
:: Hermes parity: IDE + AgentOps are separate frontends, but this
:: launcher runs both so AgentOps can identify everything the
:: Agent should do. Improvisation plan is loaded from
:: agentops/improvisation_plan.json (or .md) if present — you
:: will provide it next.
:: ============================================================

pushd %~dp0

:: --- Resolve paths ---
set "REPO=%~dp0"
:: strip trailing \
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "VENV_PY=%REPO%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" set "VENV_PY=python"
set "AGENTOPS_PY=%REPO%\agentops\.venv\Scripts\python.exe"
if not exist "%AGENTOPS_PY%" set "AGENTOPS_PY=%VENV_PY%"

:: --- Engine env (Hermes parity: observability on, cheap tier, browser UA) ---
set "PULSEAI_OBSERVABILITY=on"
set "CRUSORAI_OBSERVABILITY=on"
set "CRUSORAI_MEMORY=on"
if "%CRUSORAI_CHEAP_API_KEY%"=="" set "CRUSORAI_CHEAP_API_KEY=%CUSTOM_API_KEY%"

:: --- AgentOps env ---
set "CRUSORAI_OPS_HOST=127.0.0.1"
set "CRUSORAI_OPS_PORT=8300"
:: let AgentOps auto-detect data dir: prefers ~/.crusorai (new) else ~/.pulseai (legacy)
:: don't force CRUSORAI_OPS_DATA_DIR — rm any legacy force: set "CRUSORAI_OPS_DATA_DIR="
:: set CRUSORAI_OPS_DEMO=on if you want demo data instead of live (currently LIVE)
:: set "CRUSORAI_OPS_ENGINE_URL=http://127.0.0.1:8080"  & set CRUSORAI_OPS_ENGINE_TOKEN if you use live approvals proxy

:: --- Desktop env (so code.bat finds python + engine) ---
set "CRUSORAI_PYTHON_PATH=%VENV_PY%"
set "CRUSORAI_ENGINE_ROOT=%REPO%"
set "VSCODE_SKIP_PRELAUNCH=1"

:: --- Check improvisation plan (you will provide) ---
set "PLAN_JSON=%REPO%\agentops\improvisation_plan.json"
set "PLAN_MD=%REPO%\agentops\improvisation_plan.md"
if exist "%PLAN_JSON%" (
  echo [AgentOps] Found improvisation plan: %PLAN_JSON%
  type "%PLAN_JSON%"
) else if exist "%PLAN_MD%" (
  echo [AgentOps] Found improvisation plan: %PLAN_MD%
  type "%PLAN_MD%"
) else (
  echo [AgentOps] No improvisation_plan.json/.md yet — running with defaults.
  echo            Create agentops\improvisation_plan.json with your rules.
  echo            Template:
  echo            {
  echo              "when_to_call_agent": ["on file save", "on error", "on SLO breach"],
  echo              "identification_rules": ["tool intent vs result", "cost/latency p95", "cache_break"],
  echo              "improvisation_policy": "propose 3 alternatives then ask"
  echo            }
)

:: --- Start AgentOps backend (new window) ---
echo [1/2] Starting AgentOps backend on http://%CRUSORAI_OPS_HOST%:%CRUSORAI_OPS_PORT% ...
start "Crusor AgentOps" cmd /k ""%AGENTOPS_PY%" -m backend.app"
:: wait a beat for FastAPI to bind
timeout /t 3 /nobreak >nul

:: --- Ensure web build exists (first time only) ---
if not exist "%REPO%\agentops\web\dist\index.html" (
  echo [AgentOps] Building web/dist once...
  pushd "%REPO%\agentops\web"
  call npm run build
  popd
)

echo [2/2] Starting Crusor IDE (code.bat) with workspace %REPO% ...
:: Launch IDE — pass repo as workspace so engine resolves correctly
call "%REPO%\desktop\vscode\scripts\code.bat" "%REPO%"

:: --- Also open AgentOps dashboard in browser ---
start "" "http://%CRUSORAI_OPS_HOST%:%CRUSORAI_OPS_PORT%"

popd
endlocal
