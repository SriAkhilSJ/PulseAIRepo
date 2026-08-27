# Desktop Agent Handoff — Pulse Manager CDP Revalidation

**Branch:** `arena/01a03741-pulseairepo`  
**Required repair ancestor:** `927d8eb4`  
**Required CDP harness ancestor:** `f61a6ca2`  
**Evidence:** `bench-results/agent-ui-cdp-desktop-r2/`  
**Provider authorization:** none; echo runner only

## Why R1 failed

CDP evidence `0662fb4a` is a valid immutable runtime FAIL. The Agent lane passed every runtime check, but Pulse Manager overflowed because its grid had fixed minimum widths totaling 860px. Its existing responsive rules used viewport media queries, while the Manager editor was only 588px wide inside a larger workbench viewport.

Commit `927d8eb4` makes Manager columns intrinsically shrinkable and adds editor-container queries, so layout responds to actual editor width when Explorer and the auxiliary Agent view are open. Commit `f61a6ca2` also normalizes a maximized Electron window before the CDP resize check.

## Constraints

- Use the existing correct Windows checkout and fixed branch only.
- No provider/model call, probe, fallback, retry, credential access, or second prompt.
- Preserve `agent-ui-cdp-desktop/`, R1/R2, Attempt 12, and all historical evidence.
- Run this repaired source exactly once. Do not modify source on failure.
- Do not merge PR #9 or delete branches.
- Commit only `bench-results/agent-ui-cdp-desktop-r2/`.

## Procedure

```powershell
$ErrorActionPreference = 'Stop'
$repo = 'D:\pulseAIagent\PulseAIRepo'
cd $repo
if ((git branch --show-current) -ne 'arena/01a03741-pulseairepo') { throw 'Wrong branch — STOP' }
if (git status --porcelain=v1) { throw 'Dirty checkout — STOP without cleaning' }
git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
git merge-base --is-ancestor f61a6ca2 HEAD
if ($LASTEXITCODE -ne 0) { throw 'Required repair/harness commits missing — STOP' }

$evidence = Join-Path $repo 'bench-results\agent-ui-cdp-desktop-r2'
if (Test-Path $evidence) { throw 'CDP R2 evidence already exists — STOP' }
New-Item -ItemType Directory -Path $evidence | Out-Null
git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8
node --check scripts/validate_pulse_ui_cdp.js 2>&1 | Tee-Object "$evidence\cdp-script-syntax.log"
```

Refresh the compiled output once because CSS changed:

```powershell
cd "$repo\desktop\vscode"
npm run compile 2>&1 | Tee-Object "$evidence\desktop-compile.log"
$compileExit = $LASTEXITCODE
if ($compileExit -ne 0) { throw 'Compile failed — preserve evidence and STOP' }
```

Create a fresh isolated profile and launch CDP:

```powershell
$profile = Join-Path $env:TEMP 'pulseai-ui-cdp-r4-profile'
if (Test-Path $profile) { throw 'Profile already exists — STOP; do not reuse it' }
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

cd $repo
node scripts/validate_pulse_ui_cdp.js $evidence 2>&1 | Tee-Object "$evidence\cdp-ui-console.log"
$cdpExit = $LASTEXITCODE
```

Do not rerun if `$cdpExit` is nonzero. The expected PASS now includes all Agent checks from R1 plus:

- Manager shell `scrollWidth <= clientWidth`;
- Manager opens as the existing editor surface;
- responsive inspector behavior is reached and passes;
- `04-manager-wide.png` and `05-manager-responsive.png` are captured;
- zero renderer/console errors and zero provider requests.

Shutdown and clear temporary environment:

```powershell
if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
Start-Sleep -Seconds 3
Remove-Item Env:PULSEAI_BRIDGE_RUNNER, Env:PULSEAI_ENGINE_ROOT, Env:PULSEAI_PYTHON_PATH, Env:PULSEAI_CDP_PORT -ErrorAction SilentlyContinue
```

Create `validation-summary.json` and `validation-report.md` with exact compile/CDP exits and observations. Overall PASS requires compile exit 0, CDP exit 0, `cdp-ui-result.json` overall PASS, all five screenshots, and zero provider requests.

```powershell
cd $repo
git status --porcelain=v1 | Set-Content "$evidence\git-status-before-evidence-commit.txt" -Encoding utf8
$unexpected = git status --porcelain=v1 | Where-Object { $_ -notmatch '^\?\? bench-results/agent-ui-cdp-desktop-r2/' }
if ($unexpected) { throw 'Unexpected changes — STOP' }
Get-FileHash "$evidence\*" -Algorithm SHA256 -ErrorAction SilentlyContinue |
  Format-Table -AutoSize | Out-String -Width 4096 | Set-Content "$evidence\sha256sums.txt" -Encoding utf8
git add -- bench-results/agent-ui-cdp-desktop-r2
git diff --cached --name-only | Set-Content "$evidence\staged-files.txt" -Encoding utf8
git add -- "$evidence\staged-files.txt"
git commit -m "Add provider-free Pulse Manager CDP revalidation evidence"
git push origin arena/01a03741-pulseairepo
```

Report the evidence commit and stop. Do not merge or delete anything.
