# Desktop Agent Handoff — Pulse Agent UI Revalidation R2

**Required branch:** `arena/01a03741-pulseairepo`  
**Required repair ancestor:** `b790a29d`  
**Existing checkout only:** `D:\pulseAIagent\PulseAIRepo` if unchanged  
**Provider authorization:** none; zero provider/model requests  
**Prior evidence:** `bench-results/agent-ui-validation-desktop/` is immutable FAIL evidence  
**PR #9:** keep open and unmerged

## Purpose

R1 correctly failed because the Agent's Manager button called a host method that was absent from both the renderer contract and host adapter. Commit `b790a29d` declares `openManager()`, maps it to the existing `PulseAICommandId.OpenManager` command, and adds a structural regression.

Validate the repaired source once. If compilation passes, complete the provider-free interactive Agent and Manager smoke that R1 could not run.

## Constraints

- Do not modify or overwrite R1 or any historical evidence.
- Do not modify source, configuration, lockfiles, credentials, or `.env`.
- No provider probe, provider prompt, fallback, retry, or second turn.
- Attempt 12 remains immutable runtime/product FAIL and must not be rerun or relabeled.
- Do not reset, clean, merge, delete branches, or create another clone.
- Run each command once. Preserve any failure and stop dependent checks.
- Use `npm ci` only if existing dependencies are absent; never use `npm install`.
- Commit only `bench-results/agent-ui-validation-desktop-r2/`.

## Preflight

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
if ($LASTEXITCODE -ne 0) { throw 'Repair commit missing — STOP' }

$evidence = Join-Path $repo 'bench-results\agent-ui-validation-desktop-r2'
if (Test-Path $evidence) { throw 'R2 evidence already exists — STOP' }
New-Item -ItemType Directory -Path $evidence | Out-Null
git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8
git status --porcelain=v1 | Set-Content "$evidence\git-status-before.txt" -Encoding utf8
```

## Provider-free deterministic checks

```powershell
$python = if (Test-Path '.venv\Scripts\python.exe') { (Resolve-Path '.venv\Scripts\python.exe').Path } else { 'python' }
& $python -m pytest -q `
  src/tests/test_desktop_renderer_architecture.py `
  src/tests/test_pulseai_branding.py `
  src/tests/test_desktop_workspace_boundary.py `
  --basetemp "$env:TEMP\pulse-agent-ui-r2-pytest" `
  2>&1 | Tee-Object "$evidence\focused-pytest.log"
$pytestExit = $LASTEXITCODE

cd "$repo\ui"
if (-not (Test-Path node_modules)) { npm ci 2>&1 | Tee-Object "$evidence\ui-npm-ci.log" }
npm run check:desktop-syntax 2>&1 | Tee-Object "$evidence\desktop-syntax.log"
$syntaxExit = $LASTEXITCODE
npm run build 2>&1 | Tee-Object "$evidence\ui-build.log"
$uiBuildExit = $LASTEXITCODE

cd "$repo\desktop\vscode"
if (-not (Test-Path node_modules)) { npm ci 2>&1 | Tee-Object "$evidence\desktop-npm-ci.log" }
node --version | Tee-Object "$evidence\node-version.txt"
npm --version | Tee-Object "$evidence\npm-version.txt"

npm run typecheck-client 2>&1 | Tee-Object "$evidence\desktop-typecheck-client.log"
$typecheckExit = $LASTEXITCODE
npm run valid-layers-check 2>&1 | Tee-Object "$evidence\desktop-valid-layers.log"
$layersExit = $LASTEXITCODE
npm run compile 2>&1 | Tee-Object "$evidence\desktop-compile.log"
$compileExit = $LASTEXITCODE
```

Monitor long commands every 30 seconds without restarting them. If compilation fails, record R2 FAIL and do not launch the desktop.

## Interactive desktop smoke

Only if all required checks pass, use the established desktop launch command with a fresh temporary profile:

```powershell
cd $repo
$env:PULSEAI_BRIDGE_RUNNER = 'echo'
$env:PULSEAI_ENGINE_ROOT = $repo
```

1. Launch with no folder. Open Pulse Agent; confirm starter cards and composer are disabled. Capture `01-no-workspace.png`.
2. Open the repository folder. Confirm Pulse Ready, session/workspace header, empty state, and visible Manager button. Capture `02-agent-ready.png`.
3. Resize Agent to approximately 260, 340, and 420 px. Confirm no horizontal page scroll, overlap, or clipped composer/send control. Capture `03-agent-narrow.png`.
4. Use Tab navigation and confirm visible focus and logical order.
5. Submit exactly one deterministic turn: `Pulse Agent UI provider-free echo smoke R2`.
6. Confirm exact echo text and completion receipt, no provider/credential/approval UI, and no renderer exception. Capture `04-agent-echo-completed.png`.
7. Click **Manager**. Confirm the existing Pulse Manager editor opens, then validate normal and narrow responsive layouts. Capture `05-manager-wide.png` and `06-manager-responsive.png`.
8. Save relevant window/engine/console logs. Confirm zero `llm.request` and `llm.response` frames.
9. Close the app and clear only the temporary environment variables.

```powershell
Remove-Item Env:PULSEAI_BRIDGE_RUNNER -ErrorAction SilentlyContinue
Remove-Item Env:PULSEAI_ENGINE_ROOT -ErrorAction SilentlyContinue
```

Plan/tool disclosure may be `NOT OBSERVED` because the echo runner need not emit either. High contrast and reduced motion may be `NOT RUN`; do not infer runtime proof from CSS.

## Evidence and result

Create `validation-summary.json` and `validation-report.md` recording exact counts, exits, screenshots, console errors, interactive observations, and:

- source commit and required repair ancestor `b790a29d`;
- R1 remains immutable FAIL;
- Attempt 12 remains immutable runtime/product FAIL;
- provider requests: 0;
- PR #9 remains open/unmerged;
- overall `PASS` only if all deterministic checks and actual Agent/Manager desktop smoke pass.

```powershell
cd $repo
git status --porcelain=v1 | Set-Content "$evidence\git-status-before-evidence-commit.txt" -Encoding utf8
$unexpected = git status --porcelain=v1 | Where-Object { $_ -notmatch '^\?\? bench-results/agent-ui-validation-desktop-r2/' }
if ($unexpected) { $unexpected | Set-Content "$evidence\unexpected-changes.txt"; throw 'Unexpected changes — STOP' }
Get-FileHash "$evidence\*" -Algorithm SHA256 -ErrorAction SilentlyContinue |
  Format-Table -AutoSize | Out-String -Width 4096 |
  Set-Content "$evidence\sha256sums.txt" -Encoding utf8
git add -- bench-results/agent-ui-validation-desktop-r2
git diff --cached --name-only | Set-Content "$evidence\staged-files.txt" -Encoding utf8
git add -- "$evidence\staged-files.txt"
git commit -m "Add provider-free Pulse Agent UI R2 validation evidence"
git push origin arena/01a03741-pulseairepo
```

Report the evidence commit hash and stop. Do not merge or delete anything after PASS.
