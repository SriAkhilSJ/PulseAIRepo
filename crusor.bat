@echo off
rem Crusor launcher (Windows): ensures the preview proxy is up for the opened
rem folder, then starts the IDE. The proxy is what the Preview window frames —
rem without it the chip has nothing to open ("no preview proxy published").
rem
rem Usage:
rem   crusor.bat [folder] [extra args passed to code.bat...]
rem   crusor.bat --proxy-only [folder]   (start/verify the proxy, do not launch the IDE)
rem
rem With no folder, the current directory is used. An already-running proxy for
rem the SAME folder is reused; a proxy for another folder (or none) is replaced.
setlocal EnableDelayedExpansion

set "REPO=%~dp0"
set "FOLDER="
set "PROXYONLY="
set "EXTRA="

:parse
if "%~1"=="" goto :parsed
if "%~1"=="--proxy-only" (
  set "PROXYONLY=1"
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

rem Probe: healthy AND serving this folder?
"%PY%" -c "import json,os,sys,urllib.request; want=os.path.normcase(os.path.abspath(sys.argv[1])); h=urllib.request.urlopen('http://127.0.0.1:8931/crusor-preview/health',timeout=3).status; ep=json.load(open(os.path.join(os.path.expanduser('~'),'.crusorai','preview','ide.json'))); have=os.path.normcase(os.path.abspath(ep.get('workspace',''))); sys.exit(0 if h==200 and have==want else 1)" "%FOLDER%" >nul 2>&1
if %errorlevel%==0 (
  echo [crusor] preview proxy already serving "%FOLDER%".
  goto :launch
)

echo [crusor] starting preview proxy for "%FOLDER%" ...
start "Crusor preview proxy" /min /d "%REPO%" "%PY%" -m src.preview.server --workspace "%FOLDER%" --port 8931 --endpoint-session ide

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
