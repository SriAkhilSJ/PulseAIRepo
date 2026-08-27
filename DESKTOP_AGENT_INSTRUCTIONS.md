# Desktop Agent Instructions — Provider-Free Four-Mode UI Validation

**Updated:** 2026-08-27
**Required branch:** `arena/01a03741-pulseairepo`
**Required implementation ancestor:** `d0843937`
**Required CDP harness ancestor:** `d9cdec27`
**Evidence directory:** `bench-results/agent-ui-execution-modes-desktop`
**Open PR:** #9 — do not merge

## Authorization and stop rules

This is a provider-free source/build/CDP validation of the functional **Agent / Plan / Debug / Ask** implementation. No provider request, probe, fallback, live Test 5 turn, credential inspection, merge, or branch deletion is authorized.

Use only the existing repository at `D:\pulseAIagent\PulseAIRepo`. Do not clone, reset, clean, amend source, or touch historical evidence. Set `PULSEAI_BRIDGE_RUNNER=echo` before launching the IDE; this is the mandatory network/provider guard. Run the CDP harness once. A failure remains evidence and must not be overwritten by a retry.

## 1. Establish the exact clean source

```powershell
$ErrorActionPreference = 'Stop'
cd D:\pulseAIagent\PulseAIRepo

if ((git branch --show-current) -ne 'arena/01a03741-pulseairepo') { throw 'Wrong branch — STOP' }
if (git status --porcelain=v1) { throw 'Checkout is not clean — preserve it and STOP' }

git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
if ($LASTEXITCODE -ne 0) { throw 'Fast-forward failed — STOP' }
git merge-base --is-ancestor d0843937 HEAD
if ($LASTEXITCODE -ne 0) { throw 'Mode implementation is not an ancestor — STOP' }
git merge-base --is-ancestor d9cdec27 HEAD
if ($LASTEXITCODE -ne 0) { throw 'Mode CDP harness is not an ancestor — STOP' }

$evidence = 'bench-results\agent-ui-execution-modes-desktop'
if (Test-Path $evidence) { throw 'Evidence directory already exists — STOP; never overwrite or retry' }
New-Item -ItemType Directory -Path $evidence | Out-Null

git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8
git status --short | Set-Content "$evidence\initial-status.txt" -Encoding utf8
node --version | Set-Content "$evidence\node-version.txt" -Encoding utf8
npm --version | Set-Content "$evidence\npm-version.txt" -Encoding utf8
$python = (Resolve-Path '.venv\Scripts\python.exe').Path
& $python --version 2>&1 | Set-Content "$evidence\python-version.txt" -Encoding utf8
```

If the existing `.venv` or installed desktop/UI dependencies are unavailable, record that as the first failed boundary and stop. Do not install or alter dependencies for this validation.

## 2. Provider-free focused contracts and builds

Run each command once and preserve complete output plus exit code. Do not continue to CDP if any source/build check fails.

```powershell
& $python -m pytest -q `
  src/tests/test_execution_modes.py `
  src/tests/test_bridge.py `
  src/tests/test_bridge_transport.py `
  src/tests/test_bridge_protocol_v2.py `
  src/tests/test_desktop_renderer_architecture.py `
  src/tests/test_pulseai_branding.py 2>&1 |
  Tee-Object "$evidence\focused-pytest.log"
if ($LASTEXITCODE -ne 0) { throw 'Focused pytest failed — STOP' }

& $python scripts\generate_bridge_protocol.py --check 2>&1 |
  Tee-Object "$evidence\protocol-generation.log"
if ($LASTEXITCODE -ne 0) { throw 'Protocol generation check failed — STOP' }

Push-Location ui
npm run check:desktop-syntax 2>&1 | Tee-Object "..\$evidence\desktop-syntax.log"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Desktop syntax failed — STOP' }
npm run build 2>&1 | Tee-Object "..\$evidence\ui-build.log"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'UI build failed — STOP' }
Pop-Location

Push-Location desktop\vscode
npm run typecheck-client 2>&1 | Tee-Object "..\..\$evidence\desktop-typecheck-client.log"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Desktop typecheck failed — STOP' }
npm run valid-layers-check 2>&1 | Tee-Object "..\..\$evidence\desktop-valid-layers.log"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Desktop layer check failed — STOP' }
npm run compile 2>&1 | Tee-Object "..\..\$evidence\desktop-compile.log"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Desktop compile failed — STOP' }
Pop-Location
```

The focused tests must prove mode manifest parity, generated TypeScript currency, bridge rejection/propagation, Ask no-execution routing, preserved Plan behavior, and Agent/Debug execution routing.

## 3. One raw-CDP desktop run

Read `CDP_TEST_GUIDE.md` first. Launch the built desktop with the exact existing Python environment, repository root, echo runner, and CDP port. Never read or print `.env`.

```powershell
$env:PULSEAI_PYTHON_PATH = $python
$env:PULSEAI_ENGINE_ROOT = 'D:\pulseAIagent\PulseAIRepo'
$env:PULSEAI_BRIDGE_RUNNER = 'echo'
$env:PULSEAI_CDP_PORT = '9222'

$desktop = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', `
  'set PULSEAI_BRIDGE_RUNNER=echo&&set PULSEAI_PYTHON_PATH=D:\pulseAIagent\PulseAIRepo\.venv\Scripts\python.exe&&set PULSEAI_ENGINE_ROOT=D:\pulseAIagent\PulseAIRepo&&desktop\vscode\scripts\code.bat D:\pulseAIagent\PulseAIRepo --remote-debugging-port=9222' `
  -PassThru
try {
  node scripts\validate_pulse_ui_cdp.js $evidence 2>&1 |
    Tee-Object "$evidence\cdp-ui.log"
  $cdpExit = $LASTEXITCODE
} finally {
  if ($desktop -and -not $desktop.HasExited) { Stop-Process -Id $desktop.Id -Force -ErrorAction SilentlyContinue }
}
if ($cdpExit -ne 0) { throw 'CDP validation failed — preserve evidence and STOP without retry' }
```

The committed harness must capture and verify:

- restrained theme-aware welcome/composer rendering;
- the upward mode menu screenshot with Agent, Plan, Debug, and Ask;
- accessible menu roles, descriptions, selected state, and working Ask→Agent DOM selection;
- exact echo turn and completion receipt with zero provider traffic;
- narrow Agent layout, Manager opening, responsive Manager layout, and no overflow;
- screenshots and zero renderer/console errors.

## 4. Evidence report, hashes, and commit

Create `validation-summary.json` and `validation-report.md` from the actual logs. Record exact HEAD, every command and exit code, focused test count, all CDP checks/snapshots/screenshots, console error count, `provider_requests: 0`, overall PASS/FAIL, and the first failed boundary. A build PASS cannot upgrade a CDP FAIL. Do not claim runtime behavior not demonstrated by the focused tests and echo CDP run.

Confirm no provider events or credential material appear in evidence. Save only boolean/count results in `credential-scan.json`, never any secret value. Then hash every evidence file except the hash manifest itself:

```powershell
Get-ChildItem $evidence -Recurse -File |
  Where-Object Name -ne 'sha256sums.txt' |
  Sort-Object FullName |
  ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    $relative = [IO.Path]::GetRelativePath((Resolve-Path $evidence), $_.FullName).Replace('\','/')
    "$hash  $relative"
  } | Set-Content "$evidence\sha256sums.txt" -Encoding ascii

git status --short
```

Only `bench-results/agent-ui-execution-modes-desktop/` may be new. If source, tests, generated files, lockfiles, or historical evidence changed, preserve everything and STOP without reset/clean.

```powershell
git add -f bench-results/agent-ui-execution-modes-desktop
git commit -m "test(ui): validate functional execution modes on desktop"
git push origin arena/01a03741-pulseairepo
```

Report exact results and evidence commit, then stop. Do not merge PR #9 or delete any branch.

Desktop agent task
