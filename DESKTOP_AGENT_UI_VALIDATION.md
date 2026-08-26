# Desktop Agent Handoff — Provider-Free Pulse Agent UI Validation

**Date:** 2026-08-26  
**Required branch:** `arena/01a03741-pulseairepo`  
**Required UI implementation ancestor:** `0f84d2df`  
**Repository:** use the existing correct repository folder only (`D:\pulseAIagent\PulseAIRepo` if unchanged)  
**Provider authorization:** none; zero model/provider requests  
**PR #9:** open; do not merge

## Mission

Validate the refined first-party Pulse Agent and Pulse Manager UI on the real Windows desktop checkout. This task validates source/build integrity and the actual desktop renderer. It must not exercise a provider.

The UI increment adds a stronger session header, readable transcript lane, expandable plan strip, stable working dock, compact action timeline, workspace-gated starter actions, polished composer, responsive behavior, keyboard focus, and reduced-motion handling. Pulse branding, workbench registration, renderer architecture, host contracts, workspace safety, and approvals must remain unchanged.

## Hard constraints

- No provider probe, prompt, live model call, fallback, retry, credential inspection, or `.env` changes.
- Attempt 12 remains immutable **runtime/product FAIL**. Do not rerun, repair, relabel, or modify its evidence.
- Do not alter `bench-results/native-capability-validation-desktop/`; that validation is closed.
- Do not modify source, configuration, lockfiles, historical evidence, or existing workspaces.
- Do not reset, clean, overwrite, delete, merge PR #9, merge to `main`, or delete branches.
- Use only the existing correct checkout and fixed branch. Do not create another clone.
- Never run `npm install`; use `npm ci` only if the relevant `node_modules` is absent.
- Run each validation command exactly once. Preserve failures; do not fix or rerun them.
- Monitor long commands every 30 seconds without restarting or duplicating them.
- Commit only the new evidence directory `bench-results/agent-ui-validation-desktop/`.

## 1. Sync and immutable preflight

```powershell
$ErrorActionPreference = 'Stop'
$repo = 'D:\pulseAIagent\PulseAIRepo'
cd $repo

if ((git branch --show-current) -ne 'arena/01a03741-pulseairepo') { throw 'Wrong branch — STOP' }
if (git status --porcelain=v1) { throw 'Checkout is not clean — preserve it and STOP' }

git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
if ($LASTEXITCODE -ne 0) { throw 'Fast-forward failed — STOP' }

git merge-base --is-ancestor 0f84d2df HEAD
if ($LASTEXITCODE -ne 0) { throw 'Required UI commit is not an ancestor — STOP' }

$evidence = Join-Path $repo 'bench-results\agent-ui-validation-desktop'
if (Test-Path $evidence) { throw 'UI validation evidence already exists — STOP' }
New-Item -ItemType Directory -Path $evidence | Out-Null

git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8
git status --porcelain=v1 | Set-Content "$evidence\git-status-before.txt" -Encoding utf8
git log --oneline -8 | Set-Content "$evidence\recent-commits.txt" -Encoding utf8
```

Confirm all previous evidence is untouched:

```powershell
$historical = git status --porcelain=v1 -- bench-results
if ($historical) { $historical | Set-Content "$evidence\historical-evidence-changes.txt"; throw 'Historical evidence changed — STOP' }
```

## 2. Focused provider-free source checks

Use the existing Python environment. Do not recreate it if missing.

```powershell
$python = if (Test-Path '.venv\Scripts\python.exe') { (Resolve-Path '.venv\Scripts\python.exe').Path } else { 'python' }

& $python -m pytest -q `
  src/tests/test_desktop_renderer_architecture.py `
  src/tests/test_pulseai_branding.py `
  src/tests/test_desktop_workspace_boundary.py `
  --basetemp "$env:TEMP\pulse-agent-ui-pytest" `
  2>&1 | Tee-Object "$evidence\focused-pytest.log"
$focusedExit = $LASTEXITCODE

cd "$repo\ui"
if (-not (Test-Path node_modules)) {
  npm ci 2>&1 | Tee-Object "$evidence\ui-npm-ci.log"
  if ($LASTEXITCODE -ne 0) { throw 'UI npm ci failed — preserve evidence and STOP' }
}

npm run check:desktop-syntax 2>&1 | Tee-Object "$evidence\desktop-syntax.log"
$syntaxExit = $LASTEXITCODE
npm run build 2>&1 | Tee-Object "$evidence\ui-build.log"
$uiBuildExit = $LASTEXITCODE
```

Expected: focused tests pass, all 22 Pulse contribution files parse, and the UI production build passes.

## 3. Code OSS compile validation

```powershell
cd "$repo\desktop\vscode"
node --version | Tee-Object "$evidence\node-version.txt"
npm --version | Tee-Object "$evidence\npm-version.txt"
Get-Content "$repo\desktop\.nvmrc" | Set-Content "$evidence\required-node-version.txt"

if (-not (Test-Path node_modules)) {
  npm ci 2>&1 | Tee-Object "$evidence\desktop-npm-ci.log"
  if ($LASTEXITCODE -ne 0) { throw 'Desktop npm ci failed — preserve evidence and STOP desktop checks' }
}

npm run typecheck-client 2>&1 | Tee-Object "$evidence\desktop-typecheck-client.log"
$typecheckExit = $LASTEXITCODE
npm run valid-layers-check 2>&1 | Tee-Object "$evidence\desktop-valid-layers.log"
$layersExit = $LASTEXITCODE
npm run compile 2>&1 | Tee-Object "$evidence\desktop-compile.log"
$compileExit = $LASTEXITCODE
```

Capture a timestamped heartbeat every 30 seconds for long commands. A silent command is not permission to restart it.

## 4. Actual desktop UI smoke — echo runner only

Run only after compilation succeeds and using the repository's established desktop launch command. Use a fresh temporary profile, not an Attempt profile. Set these variables only in the launch shell:

```powershell
cd $repo
$env:PULSEAI_BRIDGE_RUNNER = 'echo'
$env:PULSEAI_ENGINE_ROOT = $repo
```

Do not enter any provider credential. The echo runner is deterministic and provider-free.

### A. Empty and workspace-gated state

1. Launch with the fresh profile and no folder open.
2. Open the Pulse Agent view.
3. Confirm the polished empty state renders without clipping.
4. Confirm starter actions and the composer are disabled while no project is open.
5. Capture `01-agent-no-workspace.png` and relevant renderer/window logs.

### B. Ready Agent state and responsive layout

1. Open the existing repository folder itself as the workspace.
2. Confirm Pulse reaches Ready without a renderer error.
3. Confirm the header shows the current session/workspace hierarchy and the Manager button.
4. Resize the Agent pane to approximately 260 px, 340 px, and 420 px widths.
5. At every width, confirm there is no horizontal page scrollbar, overlapping text, inaccessible send/stop control, or clipped composer.
6. Use Tab navigation through starter controls and composer controls; confirm visible focus and logical order.
7. Capture `02-agent-ready-wide.png` and `03-agent-ready-narrow.png`.

### C. Deterministic completed turn

Submit exactly once:

```text
Pulse Agent UI provider-free echo smoke
```

Expected:

- the composer changes to Stop while active and returns after completion;
- a stable working strip may appear while the turn is active;
- the exact text returns in the transcript;
- the run completion receipt appears;
- no provider, approval, or credential UI appears;
- no `llm.request` or `llm.response` appears in logs;
- no renderer exception appears.

Capture `04-agent-echo-completed.png` and the relevant engine/window logs. Do not submit a second turn and do not retry a failure.

### D. Pulse Manager

1. Use the Agent header's Manager button.
2. Confirm Pulse Manager opens as the existing editor surface, not a replacement webview or external page.
3. Confirm workspace/session navigation remains visible, the transcript is centered at a readable width, and the inspector remains present at a normal desktop width.
4. Narrow the editor enough to trigger its responsive inspector/sidebar behavior; confirm the main session and composer remain usable.
5. Capture `05-manager-wide.png` and `06-manager-responsive.png`.

### E. Accessibility and console receipt

- Confirm every interactive control reached during the smoke has visible keyboard focus.
- Confirm plan/tool rows use native expandable disclosure if present; the echo runner may legitimately produce no plan/tools, which must be reported as `NOT OBSERVED`, not PASS.
- Inspect the application developer console once and save relevant Pulse renderer errors/warnings to `desktop-console.log`.
- Record whether Windows high-contrast or reduced-motion was tested. If not, mark each `NOT RUN`; do not infer from source checks.

Close the app, then clear only the temporary process environment:

```powershell
Remove-Item Env:PULSEAI_BRIDGE_RUNNER -ErrorAction SilentlyContinue
Remove-Item Env:PULSEAI_ENGINE_ROOT -ErrorAction SilentlyContinue
```

## 5. Required report

Create `validation-summary.json` containing at least:

```json
{
  "source_commit": "<full tested hash>",
  "required_ui_ancestor": "0f84d2df",
  "provider_requests": 0,
  "attempt12_classification": "runtime/product FAIL (immutable; not rerun)",
  "focused_pytest_exit": 0,
  "desktop_syntax_exit": 0,
  "ui_build_exit": 0,
  "desktop_typecheck_exit": 0,
  "desktop_layers_exit": 0,
  "desktop_compile_exit": 0,
  "desktop_ui_smoke": "PASS | FAIL | NOT RUN",
  "agent_responsive": "PASS | FAIL | NOT RUN",
  "manager_responsive": "PASS | FAIL | NOT RUN",
  "keyboard_focus": "PASS | FAIL | NOT RUN",
  "plan_and_tool_disclosure": "PASS | FAIL | NOT OBSERVED",
  "high_contrast": "PASS | FAIL | NOT RUN",
  "reduced_motion": "PASS | FAIL | NOT RUN",
  "renderer_console_errors": 0,
  "overall": "PASS | FAIL"
}
```

Overall PASS requires all source/build checks and the actual Agent/Manager desktop smoke to pass. Optional accessibility modes and unproduced echo-runner plan/tool rows may be `NOT RUN`/`NOT OBSERVED`. Process startup, compilation, or screenshots alone are not an interactive runtime PASS.

Create a concise `validation-report.md` listing:

- exact command exit codes and test counts;
- each observed UI state;
- every screenshot filename;
- whether plan/tool disclosure was actually observed;
- console error count;
- explicit confirmation of zero provider requests;
- explicit confirmation Attempt 12 and all prior evidence remained untouched;
- explicit confirmation PR #9 remains open and unmerged.

## 6. Evidence integrity, commit, and push

```powershell
cd $repo
git status --porcelain=v1 | Set-Content "$evidence\git-status-before-evidence-commit.txt" -Encoding utf8

$unexpected = git status --porcelain=v1 | Where-Object { $_ -notmatch '^\?\? bench-results/agent-ui-validation-desktop/' }
if ($unexpected) { $unexpected | Set-Content "$evidence\unexpected-changes.txt"; throw 'Unexpected checkout changes — STOP without committing' }

Get-FileHash "$evidence\*" -Algorithm SHA256 -ErrorAction SilentlyContinue |
  Format-Table -AutoSize | Out-String -Width 4096 |
  Set-Content "$evidence\sha256sums.txt" -Encoding utf8

git add -- bench-results/agent-ui-validation-desktop
git diff --cached --name-only | Set-Content "$evidence\staged-files.txt" -Encoding utf8
git add -- "$evidence\staged-files.txt"
git commit -m "Add provider-free Pulse Agent UI desktop validation evidence"
git push origin arena/01a03741-pulseairepo
```

Report the evidence commit hash and stop. Do not merge or delete anything after PASS.
