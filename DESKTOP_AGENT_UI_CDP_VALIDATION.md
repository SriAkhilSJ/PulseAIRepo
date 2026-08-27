# Desktop Agent Handoff — Pulse Agent UI CDP Runtime Validation

**Required branch:** `arena/01a03741-pulseairepo`  
**Required source ancestor:** `b790a29d`  
**Required CDP script ancestor:** commit containing `scripts/validate_pulse_ui_cdp.js`  
**Existing checkout:** `D:\pulseAIagent\PulseAIRepo`  
**Provider authorization:** none; use only the echo runner  
**Evidence directory:** `bench-results/agent-ui-cdp-desktop/`

## Correction

R2 proved source/build integrity but did not run the GUI. The repository already documents raw CDP automation in `CDP_TEST_GUIDE.md`, and the Windows host has the established `D:\pulseAIagent\pulse-res\cancel-session-artifacts\CDP_test` setup. The prior “human-only” conclusion was incorrect.

This handoff performs the remaining runtime smoke through Electron's Chrome DevTools Protocol. The committed script uses Node's built-in `fetch` and `WebSocket`; it does not require Playwright, Selenium, AutoIt, or a provider.

## Hard constraints

- Run once. No retry or second prompt.
- No provider/model request, credential access, fallback, or `.env` change.
- Do not modify R1, R2, native-capability, Attempt-12, or any historical evidence.
- Attempt 12 remains immutable runtime/product FAIL.
- Do not modify source, install dependencies, merge PR #9, or delete branches.
- Commit only `bench-results/agent-ui-cdp-desktop/`.

## 1. Preflight

```powershell
$ErrorActionPreference = 'Stop'
$repo = 'D:\pulseAIagent\PulseAIRepo'
cd $repo
if ((git branch --show-current) -ne 'arena/01a03741-pulseairepo') { throw 'Wrong branch — STOP' }
if (git status --porcelain=v1) { throw 'Dirty checkout — preserve it and STOP' }
git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
if ($LASTEXITCODE -ne 0) { throw 'Fast-forward failed — STOP' }
git merge-base --is-ancestor b790a29d HEAD
if ($LASTEXITCODE -ne 0) { throw 'UI repair missing — STOP' }
node --check scripts/validate_pulse_ui_cdp.js
if ($LASTEXITCODE -ne 0) { throw 'CDP script syntax failed — STOP' }

$evidence = Join-Path $repo 'bench-results\agent-ui-cdp-desktop'
if (Test-Path $evidence) { throw 'CDP evidence already exists — STOP' }
New-Item -ItemType Directory -Path $evidence | Out-Null
git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8
git status --porcelain=v1 | Set-Content "$evidence\git-status-before.txt" -Encoding utf8
```

Confirm port 9222 and PulseAI are not already in use. If they are, record the conflict and STOP rather than killing an unrelated process.

```powershell
$listener = Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw 'CDP port 9222 already in use — STOP' }
if (Get-Process PulseAI -ErrorAction SilentlyContinue) { throw 'PulseAI already running — STOP' }
```

## 2. Prepare isolated profile

```powershell
$profile = Join-Path $env:TEMP 'pulseai-ui-cdp-r3-profile'
if (Test-Path $profile) { throw 'R3 profile already exists — STOP; do not reuse it' }
New-Item -ItemType Directory -Path (Join-Path $profile 'User') -Force | Out-Null
@'
{
  "security.workspace.trust.enabled": false,
  "window.restoreWindows": "none",
  "workbench.startupEditor": "none"
}
'@ | Set-Content (Join-Path $profile 'User\settings.json') -Encoding utf8
```

Disabling workspace trust applies only to this disposable validation profile; it avoids an unautomated native trust prompt and does not change repository or user configuration.

## 3. Launch the real Electron workbench with CDP

```powershell
$env:PULSEAI_BRIDGE_RUNNER = 'echo'
$env:PULSEAI_ENGINE_ROOT = $repo
$env:PULSEAI_PYTHON_PATH = Join-Path $repo '.venv\Scripts\python.exe'
$env:PULSEAI_CDP_PORT = '9222'

cd "$repo\desktop\vscode"
$process = Start-Process `
  -FilePath (Join-Path $repo 'desktop\vscode\scripts\code.bat') `
  -ArgumentList @($repo, "--user-data-dir=$profile", '--remote-debugging-port=9222') `
  -RedirectStandardOutput "$evidence\desktop-stdout.log" `
  -RedirectStandardError "$evidence\desktop-stderr.log" `
  -PassThru
$process.Id | Set-Content "$evidence\desktop-process-id.txt"
```

Wait for CDP once, up to 90 seconds:

```powershell
$deadline = (Get-Date).AddSeconds(90)
do {
  try { $version = Invoke-RestMethod 'http://127.0.0.1:9222/json/version' -TimeoutSec 2; break }
  catch { Start-Sleep -Milliseconds 500 }
} while ((Get-Date) -lt $deadline -and -not $process.HasExited)
if (-not $version) { throw 'CDP endpoint did not become ready — preserve logs and STOP' }
$version | ConvertTo-Json -Depth 5 | Set-Content "$evidence\cdp-version.json" -Encoding utf8
```

## 4. Run the one-shot CDP UI smoke

```powershell
cd $repo
node scripts/validate_pulse_ui_cdp.js $evidence 2>&1 |
  Tee-Object "$evidence\cdp-ui-console.log"
$cdpExit = $LASTEXITCODE
```

The script must drive the actual renderer and produce:

- `01-agent-ready.png`
- `02-agent-narrow.png`
- `03-agent-echo-completed.png`
- `04-manager-wide.png`
- `05-manager-responsive.png`
- `cdp-ui-result.json`

It checks:

- Pulse opens via its registered keybinding;
- Agent composer, session header, and Manager button are visible;
- narrow Agent layout has no horizontal overflow;
- exactly one echo-runner prompt completes with a completion receipt;
- the Manager button opens the existing Pulse Manager editor;
- Manager responsive behavior activates after real Electron window resize;
- no renderer exception or console error is observed after CDP attachment;
- provider request count remains zero.

Do not rerun on failure. Preserve the result exactly.

## 5. Shutdown and report

```powershell
if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
Start-Sleep -Seconds 3
Remove-Item Env:PULSEAI_BRIDGE_RUNNER -ErrorAction SilentlyContinue
Remove-Item Env:PULSEAI_ENGINE_ROOT -ErrorAction SilentlyContinue
Remove-Item Env:PULSEAI_PYTHON_PATH -ErrorAction SilentlyContinue
Remove-Item Env:PULSEAI_CDP_PORT -ErrorAction SilentlyContinue
```

Create `validation-summary.json` and `validation-report.md`. Overall PASS requires:

- `$cdpExit -eq 0`;
- `cdp-ui-result.json` says `overall: PASS`;
- all five screenshots exist and are non-empty;
- exact echo text and completion receipt observed;
- Manager opens and responsive check passes;
- zero renderer errors and zero provider requests.

R1 remains immutable FAIL. R2 remains deterministic source/build PASS with interactive smoke NOT RUN. This CDP evidence is the separate runtime verdict.

## 6. Evidence integrity and push

```powershell
cd $repo
git status --porcelain=v1 | Set-Content "$evidence\git-status-before-evidence-commit.txt" -Encoding utf8
$unexpected = git status --porcelain=v1 | Where-Object { $_ -notmatch '^\?\? bench-results/agent-ui-cdp-desktop/' }
if ($unexpected) { $unexpected | Set-Content "$evidence\unexpected-changes.txt"; throw 'Unexpected source changes — STOP' }
Get-FileHash "$evidence\*" -Algorithm SHA256 -ErrorAction SilentlyContinue |
  Format-Table -AutoSize | Out-String -Width 4096 |
  Set-Content "$evidence\sha256sums.txt" -Encoding utf8
git add -- bench-results/agent-ui-cdp-desktop
git diff --cached --name-only | Set-Content "$evidence\staged-files.txt" -Encoding utf8
git add -- "$evidence\staged-files.txt"
git commit -m "Add provider-free Pulse Agent UI CDP runtime evidence"
git push origin arena/01a03741-pulseairepo
```

Report the evidence commit and stop. Do not merge or delete anything.
