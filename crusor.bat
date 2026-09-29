@echo off
rem Crusor launcher (Windows): ensures the preview proxy is up for the opened folder, then starts
rem the IDE. The proxy is what the Preview window frames — without it the chip has nothing to open
rem ("no preview proxy published").
rem
rem ONE window, not two. The proxy used to be started with `start ... python.exe`, which opens a
rem console-subsystem process in its own window — so `.\crusor.bat` gave you the desktop app *and* a
rem minimized Python terminal. It is now started through src/preview/autostart.py, which spawns it
rem with CREATE_NO_WINDOW and its output in <runtime home>\preview\proxy-ide.log: nothing new
rem appears next to the app. `--show-proxy` brings the visible console back for debugging the proxy
rem itself.
rem
rem The app also starts this proxy by itself as soon as a session binds the opened folder, so this
rem launcher is a convenience, not a requirement. Either way an already-running proxy for the SAME
rem folder is reused, and a proxy for another folder (or none) is replaced.
rem
rem Usage:
rem   crusor.bat [folder] [extra args passed to code.bat...]
rem   crusor.bat --proxy-only [folder]   (start/verify the proxy, do not launch the IDE)
rem   crusor.bat --show-proxy [folder]   (start the proxy in a visible, minimized console)
rem
rem With no folder, the current directory is used.
setlocal EnableDelayedExpansion

set "REPO=%~dp0"
set "FOLDER="
set "PROXYONLY="
set "SHOWPROXY="
set "EXTRA="

:parse
if "%~1"=="" goto :parsed
if "%~1"=="--proxy-only" (
  set "PROXYONLY=1"
) else if "%~1"=="--show-proxy" (
  set "SHOWPROXY=1"
) else if not defined FOLDER (
  set "FOLDER=%~1"
) else (
  set "EXTRA=!EXTRA! "%~1""
)
shift
goto :parse
:parsed

if not defined FOLDER set "FOLDER=%CD%"
set "PY=%REPO%.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [crusor] no venv python at "%PY%" — run setup first. 1>&2
  exit /b 1
)

rem Where the proxy's output goes when it has no console. Same resolution as src/preview/endpoint.py
rem (CRUSORAI_HOME, else %USERPROFILE%\.crusorai) with the session id the IDE looks for ("ide").
set "CRUSORAI_ROOT=%CRUSORAI_HOME%"
if not defined CRUSORAI_ROOT set "CRUSORAI_ROOT=%USERPROFILE%\.crusorai"
set "LOG=%CRUSORAI_ROOT%\preview\proxy-ide.log"

rem `%REPO%.` / `%FOLDER%\.`: a Windows argument that ENDS in a backslash escapes the closing quote
rem in the C runtime's parser (a classic `... "C:\path\"` bug), and %REPO% always ends in one.
rem Probe with the engine's own resolver: a healthy proxy for THIS folder already published?
"%PY%" -c "import sys; sys.path.insert(0, sys.argv[1]); from src.preview.autostart import find_serving_endpoint; sys.exit(0 if find_serving_endpoint(sys.argv[2]) else 1)" "%REPO%." "%FOLDER%\." >nul 2>&1
if %errorlevel%==0 (
  echo [crusor] preview proxy already serving "%FOLDER%".
  goto :launch
)

if defined SHOWPROXY goto :start_visible

echo [crusor] starting preview proxy for "%FOLDER%" (no window; log: "%LOG%") ...
"%PY%" -c "import sys; sys.path.insert(0, sys.argv[1]); from src.preview.autostart import ensure_proxy; h=ensure_proxy(sys.argv[2]); print('  origin:', h.origin) if h else None; sys.exit(0 if h else 1)" "%REPO%." "%FOLDER%\."
if errorlevel 1 (
  echo [crusor] preview proxy did not start — continuing without it. 1>&2
  echo [crusor] its log is "%LOG%", or start it with --show-proxy to watch it live. 1>&2
  goto :launch
)
echo [crusor] preview proxy is up.
goto :launch

:start_visible
echo [crusor] starting preview proxy for "%FOLDER%" (visible, minimized) ...
start "Crusor preview proxy" /min /d "%REPO%" "%PY%" -u -m src.preview.server --workspace "%FOLDER%\." --port 8931 --endpoint-session ide
rem Wait (10s) for the health endpoint instead of hoping.
set "UP="
for /L %%i in (1,1,10) do (
  "%PY%" -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8931/crusor-preview/health',timeout=2).status==200 else 1)" >nul 2>&1
  if !errorlevel!==0 (
    set "UP=1"
    goto :up
  )
  timeout /t 1 /nobreak >nul
)
:up
if not defined UP (
  echo [crusor] preview proxy did not answer on :8931 — continuing without it. 1>&2
  goto :launch
)
echo [crusor] preview proxy is up.

:launch
if defined PROXYONLY exit /b 0
call "%REPO%desktop\vscode\scripts\code.bat" "%FOLDER%"%EXTRA%
