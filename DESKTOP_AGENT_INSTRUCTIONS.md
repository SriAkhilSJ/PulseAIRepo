# Desktop Agent Instructions — Attempt-11 Product-Delivery Repair Validation

**Updated:** 2026-08-26

**Required branch:** `arena/01a03741-pulseairepo`

**Repair commit to validate:** `0370515cce811dd4d86d14379dd2729a94e640b1`

**Prior evidence commit:** `84b8e35b`

**Open PR:** #9 — do not merge

> This handoff authorizes one provider-free Windows deterministic validation of
> the post-Attempt-11 product-delivery boundary repair. It does not authorize a
> provider probe/request, live Test-5 turn, dependency installation, source
> repair, cap increase, PR merge, branch deletion, or Agentic UI work.

## Objective

Validate that the product-delivery boundary repair works correctly on Windows:

1. The exact 183-test focused suite passes (includes product-delivery boundary,
   completion-integrity, bridge/runtime, budget, phase, and compaction tests).
2. Attempt-11 fixture detection for both missing vendor modules and
   `MAX_STEPS_LOOP` is verified.
3. Protocol generation and 7 protocol tests pass.
4. Python compilation and clean diff.
5. Zero provider probes/requests.
6. Approximately 30-second monitoring with committed evidence.

## Hard boundaries

- Work only in the existing correct checkout:

  ```text
  D:\pulseAIagent\PulseAIRepo
  ```

- Do not use a generated Test-5 workspace, old checkout, Arena path, or second
  clone.
- Do not modify `C:\test5-ws-attempt11` or any Attempt-5 through Attempt-11
  evidence.
- Do not print, inspect into evidence, transmit, or commit credentials.
- Do not run provider preflight, probe, bridge live turn, guarded live wrapper,
  browser product generation, or any model-backed command.
- Do not install or upgrade dependencies. If the existing environment is
  missing a dependency, record that boundary and STOP.
- Do not run the full suite. Run only the exact allowlist below.
- Do not edit runtime source or tests to make validation pass.
- Never use `git reset --hard`, `git clean`, rebase, force push, or switch
  branches.

## Step 1 — Prove and update the checkout

```powershell
$ErrorActionPreference = 'Stop'
$root = git rev-parse --show-toplevel
$branch = git branch --show-current
$remote = git remote get-url origin
$statusBefore = git status --porcelain=v1

if ($root -ne 'D:/pulseAIagent/PulseAIRepo' -and $root -ne 'D:\pulseAIagent\PulseAIRepo') {
  throw "Wrong repository root: $root"
}
if ($branch -ne 'arena/01a03741-pulseairepo') {
  throw "Wrong branch: $branch"
}
if ($remote -notmatch 'SriAkhilSJ/PulseAIRepo') {
  throw 'Wrong repository remote'
}
if ($statusBefore) {
  throw 'Checkout is not clean; preserve it and STOP without resetting'
}

git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
$validationHead = git rev-parse HEAD
git merge-base --is-ancestor 0370515cce811dd4d86d14379dd2729a94e640b1 HEAD
if ($LASTEXITCODE -ne 0) {
  throw "Required repair is not an ancestor of $validationHead"
}
```

If fast-forward fails, STOP. Do not repair the checkout with reset or rebase.

## Step 2 — Create immutable evidence

```powershell
$evidence = 'bench-results\test5-11-product-delivery-repair-validation-windows'
if (Test-Path $evidence) {
  throw 'Evidence directory already exists; do not overwrite it'
}
New-Item -ItemType Directory -Path $evidence | Out-Null
$started = (Get-Date).ToUniversalTime().ToString('o')
"$started VALIDATION_START" | Set-Content "$evidence\monitor.log" -Encoding utf8
```

Record command start/end timestamps in `monitor.log`. The focused command below
starts a separate local PowerShell heartbeat job, so its foreground execution
cannot prevent 30-second monitoring entries.

## Step 3 — Remove provider credentials from this child shell

Do not record previous values:

```powershell
$env:GROQ_API_KEY = $null
$env:GOOGLE_API_KEY = $null
$env:GEMINI_API_KEY = $null
$env:NVIDIA_API_KEY = $null
$env:OPENAI_API_KEY = $null
$env:CUSTOM_API_KEY = $null
$env:SARVAM_API_KEY = $null
$env:OPENROUTER_API_KEY = $null
```

Select the existing Python environment without installing anything:

```powershell
$python = if (Test-Path '.venv\Scripts\python.exe') {
  (Resolve-Path '.venv\Scripts\python.exe').Path
} else {
  'python'
}
& $python --version 2>&1 | Tee-Object -FilePath "$evidence\python-version.log"
if ($LASTEXITCODE -ne 0) { throw 'Existing Python environment is unavailable' }
```

## Step 4 — Run the exact 183-test focused suite

```powershell
$monitorPath = (Resolve-Path "$evidence\monitor.log").Path
"$((Get-Date).ToUniversalTime().ToString('o')) FOCUSED_START" | Add-Content $monitorPath
$heartbeatJob = Start-Job -ArgumentList $monitorPath -ScriptBlock {
  param($path)
  while ($true) {
    Start-Sleep -Seconds 30
    "$((Get-Date).ToUniversalTime().ToString('o')) FOCUSED_HEARTBEAT" |
      Add-Content $path
  }
}
try {
  & $python -m pytest -q `
    src/tests/test_attempt11_product_delivery_boundary.py `
    src/tests/test_attempt11_completion_integrity.py `
    src/tests/test_retry_proxy_stream_cleanup.py `
    src/tests/test_run_bridge_turn.py `
    src/tests/test_bridge_transport.py `
    src/tests/test_bridge.py `
    src/tests/test_lab_fixes.py `
    src/tests/test_hermes_runtime_values.py `
    src/tests/test_autonomous_runtime_contract.py `
    src/tests/test_output_limit_recovery.py `
    src/tests/test_model_budgets.py `
    src/tests/test_iteration_budget.py `
    src/tests/test_execution_phases.py `
    src/tests/test_compaction.py `
    2>&1 | Tee-Object -FilePath "$evidence\focused-tests.log"
  $focusedExit = $LASTEXITCODE
} finally {
  Stop-Job $heartbeatJob -ErrorAction SilentlyContinue
  Receive-Job $heartbeatJob -ErrorAction SilentlyContinue | Out-Null
  Remove-Job $heartbeatJob -Force -ErrorAction SilentlyContinue
}
"$((Get-Date).ToUniversalTime().ToString('o')) FOCUSED_END exit=$focusedExit" | Add-Content $monitorPath
```

Expected result:

```text
183 collected, 183 passed
```

Do not substitute a provider-backed smoke test if this fails.

## Step 5 — Verify Attempt-11 fixture detection

After the focused suite passes, verify that the workspace-integrity audit
correctly detects the three known Attempt-11 product holes:

```powershell
"$((Get-Date).ToUniversalTime().ToString('o')) FIXTURE_START" | Add-Content "$evidence\monitor.log"
& $python -c @"
from src.context.workspace_integrity import audit_workspace
import json

# Read the committed immutable Attempt-11 fixture; do not use or modify the
# external historical product workspace for this source contract.
issues = audit_workspace(r'bench-results\test5-11-desktop\workspace')
findings = [
    {
        'kind': issue.kind,
        'path': issue.path,
        'reference': issue.reference,
        'description': issue.describe(),
    }
    for issue in issues
]
print(json.dumps({'finding_count': len(findings), 'findings': findings}, indent=2))

expected = [
    ('missing-local-import', '../vendor/three/three.module.min.js'),
    ('missing-local-import', '../vendor/three/controls/OrbitControls.js'),
    ('undefined-shader-constant', 'MAX_STEPS_LOOP'),
]
missing = []
for kind, reference in expected:
    found = any(
        item['kind'] == kind and item['reference'] == reference
        for item in findings
    )
    print(f'  {reference}: {"PASS" if found else "FAIL"}')
    if not found:
        missing.append((kind, reference))
if missing:
    raise SystemExit(f'Missing expected findings: {missing!r}')
"@ 2>&1 | Tee-Object -FilePath "$evidence\fixture-detection.log"
$fixtureExit = $LASTEXITCODE
"$((Get-Date).ToUniversalTime().ToString('o')) FIXTURE_END exit=$fixtureExit" | Add-Content "$evidence\monitor.log"
```

Expected: all three findings detected (exit 0).

## Step 6 — Protocol, compilation, and diff checks

```powershell
"$((Get-Date).ToUniversalTime().ToString('o')) PROTOCOL_START" | Add-Content "$evidence\monitor.log"
& $python -m pytest -q src/tests/test_bridge_protocol_v2.py `
  2>&1 | Tee-Object -FilePath "$evidence\protocol-tests.log"
$protocolExit = $LASTEXITCODE

& $python scripts/generate_bridge_protocol.py --check `
  2>&1 | Tee-Object -FilePath "$evidence\protocol-generation.log"
$generationExit = $LASTEXITCODE

& $python -m compileall -q `
  src/llm/factory.py `
  src/tools/terminal_tools.py `
  src/bridge/__main__.py `
  src/graphs/chat_graph.py `
  src/graphs/gates.py `
  src/graphs/budget.py `
  src/context/compaction.py `
  src/context/context_engine.py `
  src/context/workspace_integrity.py
$compileExit = $LASTEXITCODE
@{
  exit_code = $compileExit
  modules = @(
    'src/llm/factory.py',
    'src/tools/terminal_tools.py',
    'src/bridge/__main__.py',
    'src/graphs/chat_graph.py',
    'src/graphs/gates.py',
    'src/graphs/budget.py',
    'src/context/compaction.py',
    'src/context/context_engine.py',
    'src/context/workspace_integrity.py'
  )
} | ConvertTo-Json -Depth 3 | Set-Content "$evidence\compile-outcome.json" -Encoding utf8

$diffOutput = @(git diff --check 2>&1)
$diffExit = $LASTEXITCODE
if ($diffOutput.Count -eq 0) {
  "git diff --check: clean (exit 0)" |
    Set-Content "$evidence\git-diff-check.log" -Encoding utf8
} else {
  $diffOutput | Set-Content "$evidence\git-diff-check.log" -Encoding utf8
}
"$((Get-Date).ToUniversalTime().ToString('o')) CHECKS_END protocol=$protocolExit generation=$generationExit compile=$compileExit diff=$diffExit" | Add-Content "$evidence\monitor.log"
```

Expected protocol result: 7/7 passed. Expected generation, compilation, and diff
exit codes: zero.

## Step 7 — Record a bounded summary

Create `validation_summary.json` containing only:

- UTC start/end timestamps;
- repository root, remote, branch, and current head;
- repair commit `0370515cce811dd4d86d14379dd2729a94e640b1`;
- prior evidence commit `84b8e35b`;
- OS and Python version;
- exact allowlisted test filenames;
- collected/passed/failed/skipped counts and exit codes;
- fixture detection results (three findings expected);
- protocol generation, compilation, and diff-check exit codes;
- `provider_probes: 0` and `provider_requests: 0`;
- clean checkout status before validation;
- deterministic verdict; and
- `This is not live runtime/product PASS evidence.`

Verdict rules:

- `DETERMINISTIC_PASS` only if focused tests are 183/183, fixture detection
  finds all three expected holes, protocol tests are 7/7, all other checks
  return zero, the repair is an ancestor, and provider probe/request counts
  are zero.
- Otherwise record `DETERMINISTIC_FAIL`, preserve the first failure, and STOP.

Save exactly these evidence classes:

```text
checkout.txt
python-version.log
monitor.log
focused-tests.log
fixture-detection.log
protocol-tests.log
protocol-generation.log
compile-outcome.json
git-diff-check.log
validation_summary.json
sha256sums.txt
```

Generate `sha256sums.txt` after every other evidence file is final and include
each of those files exactly once.

## Step 8 — Commit and push evidence only

```powershell
git status --short
```

Only the new evidence directory may be present. If source, tests, historical
evidence, or unrelated paths changed, preserve the state and STOP for review.

```powershell
git add -f bench-results/test5-11-product-delivery-repair-validation-windows
git commit -m "test: validate Attempt 11 product-delivery repair on Windows"
git push origin arena/01a03741-pulseairepo
```

Do not merge PR #9.

## Final response and mandatory STOP

Report only:

1. repository root, branch, validation head, and repair commit;
2. deterministic verdict and exact counts;
3. fixture detection results;
4. provider probes/requests, both zero;
5. evidence directory and commit hash;
6. first failed boundary, if any; and
7. `STOPPED — no live attempt authorized`.

Then STOP. No live provider attempt, source repair, merge, branch deletion, or
Agentic UI work is authorized by this handoff.
