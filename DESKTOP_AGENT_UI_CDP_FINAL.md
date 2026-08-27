# Desktop Agent Handoff — Final Targeted Manager CDP Check

**Branch:** `arena/01a03741-pulseairepo`  
**Required harness ancestor:** `23f3f0b4`  
**Product source:** unchanged from responsive repair `927d8eb4`  
**New evidence:** `bench-results/agent-ui-cdp-desktop-final/`  
**Provider authorization:** none; this continuation makes zero turns

## Purpose

Evidence `e886e434` proves the Manager overflow fix at runtime (`scrollWidth 636 <= clientWidth 636`) and all Agent checks passed. Its only remaining failure came from calling unsupported CDP method `Browser.getWindowForTarget`.

The Manager was already rendered at a real 636px editor-container width, inside the `<=880px` responsive range. Harness commit `23f3f0b4` now inspects the container query at that actual width and verifies the inspector is hidden. It does not resize the OS window and does not need the unsupported Browser domain.

Run only this targeted manager check. `--manager-only` submits no prompt, so this is not a second turn and cannot contact a provider.

## Constraints

- Existing correct Windows checkout and fixed branch only.
- No compile rerun: `e886e434` already records compile PASS and product source is unchanged.
- No prompt, provider/model request, probe, fallback, credential access, or `.env` edit.
- Preserve all earlier evidence exactly.
- Do not modify source, install dependencies, merge PR #9, or delete branches.
- Run once and commit only the new final evidence directory.

## Run

```powershell
$ErrorActionPreference = 'Stop'
$repo = 'D:\pulseAIagent\PulseAIRepo'
cd $repo
if ((git branch --show-current) -ne 'arena/01a03741-pulseairepo') { throw 'Wrong branch — STOP' }
if (git status --porcelain=v1) { throw 'Dirty checkout — STOP without cleaning' }
git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
git merge-base --is-ancestor 23f3f0b4 HEAD
if ($LASTEXITCODE -ne 0) { throw 'Required harness fix missing — STOP' }
node --check scripts/validate_pulse_ui_cdp.js
if ($LASTEXITCODE -ne 0) { throw 'Harness syntax failed — STOP' }

$evidence = Join-Path $repo 'bench-results\agent-ui-cdp-desktop-final'
if (Test-Path $evidence) { throw 'Final evidence already exists — STOP' }
New-Item -ItemType Directory -Path $evidence | Out-Null
git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8

$profile = Join-Path $env:TEMP 'pulseai-ui-cdp-final-profile'
if (Test-Path $profile) { throw 'Final profile already exists — STOP' }
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

Expected `cdp-ui-result.json`:

- `mode`: `manager-only`;
- `provider_requests`: `0`;
- `Echo turn`: skipped because no turn is made;
- Agent shell/header/composer checks pass;
- Manager opens and has no horizontal overflow;
- Manager container width is positive and `<=880`;
- Manager inspector computed display is `none` while main width remains positive;
- no renderer exceptions or console errors;
- `overall`: `PASS`.

Expected screenshots: `01-agent-ready.png`, `02-agent-narrow.png`, `04-manager-wide.png`, and `05-manager-responsive.png`.

## Shutdown and evidence

```powershell
if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
Start-Sleep -Seconds 3
Remove-Item Env:PULSEAI_BRIDGE_RUNNER, Env:PULSEAI_ENGINE_ROOT, Env:PULSEAI_PYTHON_PATH, Env:PULSEAI_CDP_PORT -ErrorAction SilentlyContinue
```

Create `validation-summary.json` and `validation-report.md`. Keep prior classifications immutable. The combined UI runtime verdict may be PASS only if:

- Agent and exact echo checks remain PASS in `e886e434`;
- Manager overflow remains fixed;
- this targeted responsive inspector check passes;
- this run records zero turns, zero provider requests, and zero renderer errors.

```powershell
cd $repo
git status --porcelain=v1 | Set-Content "$evidence\git-status-before-evidence-commit.txt" -Encoding utf8
$unexpected = git status --porcelain=v1 | Where-Object { $_ -notmatch '^\?\? bench-results/agent-ui-cdp-desktop-final/' }
if ($unexpected) { throw 'Unexpected changes — STOP' }
Get-FileHash "$evidence\*" -Algorithm SHA256 -ErrorAction SilentlyContinue |
  Format-Table -AutoSize | Out-String -Width 4096 | Set-Content "$evidence\sha256sums.txt" -Encoding utf8
git add -- bench-results/agent-ui-cdp-desktop-final
git diff --cached --name-only | Set-Content "$evidence\staged-files.txt" -Encoding utf8
git add -- "$evidence\staged-files.txt"
git commit -m "Add final provider-free Pulse Manager CDP evidence"
git push origin arena/01a03741-pulseairepo
```

Report the evidence commit and stop. Do not merge or delete anything.
