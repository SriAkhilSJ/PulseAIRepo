@echo off
setlocal
echo === PulseAI Full Verify + Run (0 tokens for first 3, 1 credit for live) ===
echo.

echo [CLEAN] killing old 8200/8123/5173 ...
taskkill /F /IM node.exe 2>nul
taskkill /F /IM python.exe 2>nul
timeout /t 2 /nobreak >nul

echo.
echo [1/5] tsc -b (pulse-webview) ...
pushd "%~dp0pulse-webview"
call "C:\Program Files\nodejs\npx.cmd" tsc -b
if %errorlevel% neq 0 ( echo tsc FAILED & popd & pause & exit /b 1 )
echo tsc OK
popd

echo.
echo [2/5] DOM tests (pulse-webview 9/9) ...
pushd "%~dp0pulse-webview"
call "C:\Program Files\nodejs\npm.cmd" test
if %errorlevel% neq 0 ( echo DOM FAILED & popd & pause & exit /b 1 )
popd

echo.
echo [3/5] Python bridge + bounded_scan (35 passed) ...
call "%~dp0.venv\Scripts\python.exe" -m pytest src/tests/test_bridge.py src/tests/test_bridge_protocol_v2.py src/tests/test_bounded_scan.py -q
if %errorlevel% neq 0 ( echo pytest FAILED & pause & exit /b 1 )

echo.
echo [4/5] Starting stack 8200 + 8123 + 5173 ...
start "Pulse Runtime 8200" cmd /k "npx --yes tsx pulse-webview/server.ts"
start "Pulse Python 8123" cmd /k "uv run python -m src.server"
start "Pulse Webview 5173" cmd /k "npm run dev --prefix pulse-webview"
timeout /t 8 /nobreak >nul

echo.
echo [5/5] Health checks ...
curl -s http://localhost:8123/health >nul 2>&1 && echo 8123 OK || echo 8123 NOT READY (wait 5s)
curl -s http://localhost:8200/api/copilotkit/info >nul 2>&1 && echo 8200 OK || echo 8200 NOT READY
curl -s http://localhost:5173 >nul 2>&1 && echo 5173 OK || echo 5173 NOT READY

echo.
echo [E2E] browser verify (sends hello, 1 Sarvam credit) ...
pushd "%~dp0pulse-webview"
call "C:\Program Files\nodejs\npx.cmd" playwright test e2e-verify.spec.ts --reporter=list
popd

echo.
echo === Done ===
echo Open http://localhost:5173  (type hello)
echo Desktop: F1 ^> View: Pulse Agent (right AuxiliaryBar fixed, canMoveView:false)
echo Close the 3 black windows with Ctrl+C to stop.
echo Screenshot: D:\pulseAIagent\browser-verify.png
echo.
pause
