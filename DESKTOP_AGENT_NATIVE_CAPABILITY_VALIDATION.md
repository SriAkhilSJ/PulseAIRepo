# Desktop Agent Handoff — Provider-Free Native Capability Bridge Validation

**Date:** 2026-08-26  
**Required branch:** `arena/01a03741-pulseairepo`  
**Required implementation ancestor:** `b270f8cd`  
**Repository:** use the existing correct repository folder only (`D:\pulseAIagent\PulseAIRepo` if unchanged)  
**Provider authorization:** none; zero model/provider requests  
**PR #9:** open; do not merge

## Mandatory state correction

The prior acknowledgement said Attempt 12 was “runtime PASS, product PARTIAL.” That is incorrect and must not appear in the validation report.

Attempt 12 is consumed and immutable. Its final bridge outcome had `completed=false`, its workspace referenced missing `./src/main.js`, and it lacked sufficient verified product evidence. Provider/model behavior dominated the 22-minute latency, but Pulse also had independent completion, integrity, and lifecycle defects. The truthful classification remains **runtime/product FAIL**. Do not rerun, repair, relabel, or modify Attempt-12 evidence.

## Mission

Validate commit `b270f8cd` provider-free on the real Windows desktop checkout:

1. focused Python contracts for the host capability broker and protocol;
2. generated protocol parity;
3. native/UI tool-catalog parity;
4. complete first-party Pulse TypeScript syntax parsing;
5. UI TypeScript/Vite build;
6. Code OSS client typecheck, layer validation, and compile;
7. optional deterministic desktop echo smoke if compilation succeeds;
8. preserve and push all validation evidence without source edits.

The implementation exposes only these read-only host capabilities:

- `workspace.trust`
- `editor.activeSelection`
- `editor.dirtyText`
- `diagnostics.markers`
- `language.symbols`
- `language.definitions`
- `language.references`
- `search.workspace`
- `scm.state`

Mutation, terminal execution, tasks/tests execution, extension tools, MCP, remote execution, and secrets must remain unavailable through `invoke_host_capability`.

## Hard constraints

- No provider probe, prompt, live model call, fallback, retry, or credential inspection.
- Do not edit `.env` or print credentials.
- Do not modify source to make a test pass.
- Do not install or update dependencies unless the existing lockfile-preserving install documented below is required.
- Never run `npm install`; use `npm ci` only when `node_modules` is absent.
- Do not reset, clean, overwrite, or delete any historical evidence/workspace.
- Do not merge PR #9, merge to `main`, delete branches, or create another clone.
- Monitor long compile commands every 30 seconds. A silent command is not permission to restart it.
- If a command fails, capture the complete failure and continue only where the next check is independent. Never repair source.
- Only evidence files created under `bench-results/native-capability-validation-desktop/` may be committed by the Desktop Agent.

## 1. Sync and immutable preflight

```powershell
$ErrorActionPreference = 'Stop'
$repo = 'D:\pulseAIagent\PulseAIRepo'
cd $repo

if ((git branch --show-current) -ne 'arena/01a03741-pulseairepo') {
  throw 'Wrong branch — STOP'
}
if (git status --porcelain=v1) {
  throw 'Checkout is not clean — preserve it and STOP; do not reset or clean'
}

git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
if ($LASTEXITCODE -ne 0) { throw 'Fast-forward failed — STOP' }

git merge-base --is-ancestor b270f8cd HEAD
if ($LASTEXITCODE -ne 0) { throw 'Required bridge commit b270f8cd is not an ancestor — STOP' }

$evidence = Join-Path $repo 'bench-results\native-capability-validation-desktop'
if (Test-Path $evidence) { throw 'Validation evidence directory already exists — STOP' }
New-Item -ItemType Directory -Path $evidence | Out-Null

git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8
git status --porcelain=v1 | Set-Content "$evidence\git-status-before.txt" -Encoding utf8
git log --oneline -8 | Set-Content "$evidence\recent-commits.txt" -Encoding utf8
```

Confirm no historical evidence is changed:

```powershell
$historical = git status --porcelain=v1 -- bench-results/test5-5-desktop bench-results/test5-6-desktop bench-results/test5-7-desktop bench-results/test5-8-desktop bench-results/test5-9-desktop bench-results/test5-10-desktop bench-results/test5-11-desktop bench-results/test5-12-desktop
if ($historical) { $historical | Set-Content "$evidence\historical-evidence-changes.txt"; throw 'Historical evidence changed — STOP' }
```

## 2. Focused Python validation

Use the existing repository environment. Do not recreate it if missing; report the missing environment instead.

```powershell
$python = if (Test-Path '.venv\Scripts\python.exe') {
  (Resolve-Path '.venv\Scripts\python.exe').Path
} else { 'python' }

& $python -m pytest -q `
  src/tests/test_host_capability_broker.py `
  src/tests/test_bridge_protocol_v2.py `
  src/tests/test_workbench_capabilities.py `
  src/tests/test_desktop_renderer_architecture.py `
  src/tests/test_ui_tool_catalog.py `
  src/tests/test_desktop_sidecar_architecture.py `
  --basetemp "$env:TEMP\pulse-native-capability-pytest" `
  2>&1 | Tee-Object "$evidence\focused-pytest.log"
$focusedExit = $LASTEXITCODE
```

Expected: zero failures. Record the exact count; do not assume a count from this handoff.

Run generation and Python syntax checks independently:

```powershell
& $python scripts/generate_bridge_protocol.py --check 2>&1 |
  Tee-Object "$evidence\protocol-generation.log"
$protocolExit = $LASTEXITCODE

& $python -m compileall -q src 2>&1 |
  Tee-Object "$evidence\python-compileall.log"
$compileallExit = $LASTEXITCODE
```

## 3. Deterministic stdio bridge smoke

This uses the echo runner and sends no provider request. It verifies handshake, workspace binding, and capability publication while filtering out `terminal.native`.

```powershell
@'
import json, os, subprocess, sys
frames = [
    {'type':'hello','protocol':2},
    {'type':'session_create','session_id':'host-desktop','workspace':r'C:\pulse-host-fixture'},
    {'type':'host_capabilities_update','session_id':'host-desktop','workspace':r'C:\pulse-host-fixture','capabilities':[
        {'id':'diagnostics.markers','availability':'available','risk':'read','provider':'markerService'},
        {'id':'terminal.native','availability':'available','risk':'execute','provider':'terminalService'},
    ]},
    {'type':'shutdown'},
]
env = dict(os.environ)
env['PULSEAI_BRIDGE_RUNNER'] = 'echo'
p = subprocess.run([sys.executable, '-m', 'src.bridge'], input=''.join(json.dumps(x)+'\n' for x in frames), text=True, capture_output=True, env=env, timeout=30)
print(p.stdout, end='')
print(p.stderr, file=sys.stderr, end='')
out = [json.loads(line) for line in p.stdout.splitlines()]
assert p.returncode == 0
assert out[0]['type'] == 'hello' and out[0]['protocol'] == 2
assert any(x.get('host_capabilities_updated') == 1 for x in out)
assert not any(x.get('type') in {'llm.request','llm.response'} for x in out)
'@ | & $python - 2>&1 | Tee-Object "$evidence\bridge-echo-smoke.log"
$bridgeExit = $LASTEXITCODE
```

## 4. UI and first-party TypeScript validation

```powershell
cd "$repo\ui"
if (-not (Test-Path node_modules)) {
  npm ci 2>&1 | Tee-Object "$evidence\ui-npm-ci.log"
  if ($LASTEXITCODE -ne 0) { throw 'UI npm ci failed; preserve log and continue with independent desktop checks' }
}

npm run check:desktop-syntax 2>&1 |
  Tee-Object "$evidence\desktop-syntax.log"
$desktopSyntaxExit = $LASTEXITCODE

npm run build 2>&1 |
  Tee-Object "$evidence\ui-build.log"
$uiBuildExit = $LASTEXITCODE
```

Expected syntax receipt: all 22 first-party Pulse contribution TypeScript files parse.

## 5. Full Code OSS validation

Use the vendored fork's pinned Node version from `desktop\.nvmrc`. Record actual versions first.

```powershell
cd "$repo\desktop\vscode"
node --version | Tee-Object "$evidence\node-version.txt"
npm --version | Tee-Object "$evidence\npm-version.txt"
Get-Content "$repo\desktop\.nvmrc" | Set-Content "$evidence\required-node-version.txt"

if (-not (Test-Path node_modules)) {
  npm ci 2>&1 | Tee-Object "$evidence\desktop-npm-ci.log"
  if ($LASTEXITCODE -ne 0) { throw 'Desktop npm ci failed — preserve evidence and STOP desktop checks' }
}
```

Run each command exactly once. Use a separate PowerShell/job only to append a timestamped heartbeat every 30 seconds; do not poll, restart, or duplicate the command.

```powershell
npm run typecheck-client 2>&1 | Tee-Object "$evidence\desktop-typecheck-client.log"
$typecheckExit = $LASTEXITCODE

npm run valid-layers-check 2>&1 | Tee-Object "$evidence\desktop-valid-layers.log"
$layersExit = $LASTEXITCODE

npm run compile 2>&1 | Tee-Object "$evidence\desktop-compile.log"
$desktopCompileExit = $LASTEXITCODE
```

Expected: zero new TypeScript errors, zero layer violations, successful compile. If the vendored fork has a known unrelated baseline failure, capture the full output and classify it separately; do not call the bridge PASS unless Pulse files typecheck and the failure is proven unrelated.

## 6. Optional desktop echo runtime smoke

Run only if the Code OSS compile succeeded and an existing dev desktop build is available. This remains provider-free.

```powershell
cd $repo
$env:PULSEAI_BRIDGE_RUNNER = 'echo'
$env:PULSEAI_ENGINE_ROOT = $repo
```

Launch a fresh profile using the repository's established desktop launch command. Do not reuse Attempt profiles. Open the Pulse view, submit the literal text:

```text
native capability bridge echo smoke
```

Expected:

- Pulse opens without a renderer error;
- the sidecar reaches Ready;
- the exact echo text returns;
- no approval or provider UI appears;
- no `llm.request`/`llm.response` appears in captured logs;
- no “unknown method: host_capabilities_update” error appears.

Capture one screenshot and the relevant window/engine logs under the evidence directory. If there is no already-built desktop executable, mark this check `NOT RUN — no existing build`; do not improvise another checkout or generated app.

Clear only the temporary process environment after closing the app:

```powershell
Remove-Item Env:PULSEAI_BRIDGE_RUNNER -ErrorAction SilentlyContinue
Remove-Item Env:PULSEAI_ENGINE_ROOT -ErrorAction SilentlyContinue
```

## 7. Report and evidence integrity

Create `validation-summary.json` with at least:

```json
{
  "source_commit": "<full hash>",
  "provider_requests": 0,
  "attempt12_classification": "runtime/product FAIL (immutable; not rerun)",
  "focused_pytest_exit": 0,
  "protocol_generation_exit": 0,
  "python_compileall_exit": 0,
  "bridge_echo_exit": 0,
  "desktop_syntax_exit": 0,
  "ui_build_exit": 0,
  "desktop_typecheck_exit": 0,
  "desktop_layers_exit": 0,
  "desktop_compile_exit": 0,
  "desktop_runtime_smoke": "PASS | FAIL | NOT RUN",
  "overall": "PASS | FAIL"
}
```

Overall PASS requires all non-optional checks to pass. HTTP/process startup alone is not product or runtime PASS. Do not use `PARTIAL` to conceal a required failure.

Then record final state:

```powershell
cd $repo
git status --porcelain=v1 | Set-Content "$evidence\git-status-before-evidence-commit.txt" -Encoding utf8
Get-FileHash "$evidence\*" -Algorithm SHA256 -ErrorAction SilentlyContinue |
  Format-Table -AutoSize | Out-String -Width 4096 |
  Set-Content "$evidence\sha256sums.txt" -Encoding utf8
```

The status may contain only the new evidence directory plus ignored build artifacts. Any tracked source change is a FAIL; do not commit it.

Commit and push all evidence to the fixed branch:

```powershell
git add -- bench-results/native-capability-validation-desktop
git diff --cached --name-only | Set-Content "$evidence\staged-files.txt" -Encoding utf8
git add -- "$evidence\staged-files.txt"
git commit -m "Add provider-free native capability desktop validation evidence"
git push origin arena/01a03741-pulseairepo
```

Report:

- evidence commit hash;
- exact pass/fail counts;
- every command exit code;
- whether desktop runtime smoke ran;
- confirmation of zero provider requests;
- confirmation Attempt 12 remained untouched and correctly classified;
- confirmation PR #9 remains open and unmerged.

Do not merge or delete anything after PASS.
