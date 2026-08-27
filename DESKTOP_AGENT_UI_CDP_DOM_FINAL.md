# Desktop Agent Handoff — Final Manager DOM Check

**Branch:** `arena/01a03741-pulseairepo`  
**Required harness ancestor:** `a8ec019d`  
**Product source:** unchanged from `927d8eb4`  
**Evidence:** `bench-results/agent-ui-cdp-dom-final/`  
**Provider authorization:** none; zero turns

## Scope

Evidence `d8394870` failed before Manager navigation because an already-proven Agent screenshot timed out. Screenshot capture is not needed again: immutable evidence `e886e434` already contains the Agent and Manager screenshots, proves Manager overflow is fixed, and records zero renderer errors.

Harness commit `a8ec019d` makes `--manager-only` purely DOM-driven. It performs no `Page.captureScreenshot`, makes no prompt, and directly validates the one remaining responsive-inspector condition at the real Manager editor width.

## Constraints

- Use the existing correct checkout and fixed branch only.
- Do not compile, install, prompt, access a provider, or rerun any prior lane.
- Preserve all historical evidence.
- Run once. On failure, preserve it and stop.
- Do not merge PR #9 or delete branches.
- Commit only the new evidence directory.

## Procedure

```powershell
$ErrorActionPreference = 'Stop'
$repo = 'D:\pulseAIagent\PulseAIRepo'
cd $repo
if ((git branch --show-current) -ne 'arena/01a03741-pulseairepo') { throw 'Wrong branch — STOP' }
if (git status --porcelain=v1) { throw 'Dirty checkout — STOP without cleaning' }
git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
git merge-base --is-ancestor a8ec019d HEAD
if ($LASTEXITCODE -ne 0) { throw 'Required harness fix missing — STOP' }
node --check scripts/validate_pulse_ui_cdp.js

$evidence = Join-Path $repo 'bench-results\agent-ui-cdp-dom-final'
if (Test-Path $evidence) { throw 'Evidence already exists — STOP' }
New-Item -ItemType Directory -Path $evidence | Out-Null
git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8

$profile = Join-Path $env:TEMP 'pulseai-ui-cdp-dom-final-profile'
if (Test-Path $profile) { throw 'Profile already exists — STOP' }
New-Item -ItemType Directory -Path (Join-Path $profile 'User') -Force | Out-Null
@'
{
  "security.workspace.trust.enabled": false,
  "window.restoreWindows": "none",
  "workbench.startupEditor": "none"
}
'@ | Set-Content (Join-Path $profile 'User\settings.json') -Encoding utf8

if (Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 9222 in use — STOP' }
if (Get-Process PulseAI -ErrorAction SilentlyContinue) { throw 'PulseAI already running — STOP' }

$env:PULSEAI_BRIDGE_RUNNER = 'echo'
$env:PULSEAI_ENGINE_ROOT = $repo
$env:PULSEAI_PYTHON_PATH = Join-Path $repo '.venv\Scripts\python.exe'
$env:PULSEAI_CDP_PORT = '9222'
$process = Start-Process `
  -FilePath (Join-Path $repo 'desktop\vscode\scripts\code.bat') `
  -ArgumentList @($repo, "--user-data-dir=$profile", '--remote-debugging-port=9222') `
  -RedirectStandardOutput "$evidence\desktop-stdout.log" `
  -RedirectStandardError "$evidence\desktop-stderr.log" `
  -PassThru
$process.Id | Set-Content "$evidence\desktop-process-id.txt"

$deadline = (Get-Date).AddSeconds(90)
do {
  try { $version = Invoke-RestMethod 'http://127.0.0.1:9222/json/version' -TimeoutSec 2; break }
  catch { Start-Sleep -Milliseconds 500 }
} while ((Get-Date) -lt $deadline -and -not $process.HasExited)
if (-not $version) { throw 'CDP unavailable — preserve logs and STOP' }
$version | ConvertTo-Json -Depth 5 | Set-Content "$evidence\cdp-version.json" -Encoding utf8

node scripts/validate_pulse_ui_cdp.js $evidence --manager-only 2>&1 |
  Tee-Object "$evidence\cdp-ui-console.log"
$cdpExit = $LASTEXITCODE
```

Expected result:

- mode `manager-only`, prompt `null`, provider requests `0`;
- Screenshots and Echo turn explicitly skipped;
- Manager opens as a visible editor;
- Manager has no horizontal overflow;
- actual Manager container width is positive and `<=880`;
- inspector computed display is `none` and main width is positive;
- zero renderer/console errors;
- overall PASS.

Shutdown and clear temporary variables:

```powershell
if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
Start-Sleep -Seconds 3
Remove-Item Env:PULSEAI_BRIDGE_RUNNER, Env:PULSEAI_ENGINE_ROOT, Env:PULSEAI_PYTHON_PATH, Env:PULSEAI_CDP_PORT -ErrorAction SilentlyContinue
```

Create `validation-summary.json` and `validation-report.md`. The combined Agent/Manager UI runtime verdict may be PASS only when this DOM result is combined with the screenshots, exact echo, overflow fix, and console evidence already preserved in `e886e434`.

```powershell
cd $repo
git status --porcelain=v1 | Set-Content "$evidence\git-status-before-evidence-commit.txt" -Encoding utf8
$unexpected = git status --porcelain=v1 | Where-Object { $_ -notmatch '^\?\? bench-results/agent-ui-cdp-dom-final/' }
if ($unexpected) { throw 'Unexpected changes — STOP' }
Get-FileHash "$evidence\*" -Algorithm SHA256 -ErrorAction SilentlyContinue |
  Format-Table -AutoSize | Out-String -Width 4096 | Set-Content "$evidence\sha256sums.txt" -Encoding utf8
git add -- bench-results/agent-ui-cdp-dom-final
git diff --cached --name-only | Set-Content "$evidence\staged-files.txt" -Encoding utf8
git add -- "$evidence\staged-files.txt"
git commit -m "Add final provider-free Pulse Manager DOM evidence"
git push origin arena/01a03741-pulseairepo
```

Report the evidence commit and stop. Do not merge or delete anything.
