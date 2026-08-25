@echo off
REM PulseAI keyless desktop benchmark (one command, zero cost)
REM Usage:  scripts\run_keyless_cdp.bat C:\path\to\a\test\workspace
REM The IDE must already be built at desktop\vscode\.build\electron\PulseAI.exe
setlocal

set REPO=%~dp0..
set PY=%REPO%\.venv\Scripts\python.exe
set IDE=%REPO%\desktop\vscode\.build\electron\PulseAI.exe
set WS=%~1

if "%WS%"=="" (
    echo Usage: run_keyless_cdp.bat C:\path\to\a\test\workspace
    exit /b 1
)
if not exist "%PY%" (
    echo Python not found at %PY%
    exit /b 1
)
if not exist "%IDE%" (
    echo IDE not found at %IDE%
    echo Build it first: cd desktop\vscode ^&^& npm install ^&^& npm run compile
    exit /b 1
)

echo Launching PulseAI IDE and running keyless tasks (PBR-001, PBR-003, PBR-012)...
"%PY%" -m benchmarks.pulse_reliability_v1.harness run-all ^
    --workspace "%WS%" ^
    --launch "\"%IDE%\" --remote-debugging-port=9222" ^
    --port 9222

echo.
echo Report card: bench-results\report-card.md
endlocal
