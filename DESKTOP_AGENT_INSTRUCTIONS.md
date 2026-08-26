# Desktop Agent Instructions — Attempt-11 Repair Validation Only

**Updated:** 2026-08-25

**Required branch:** `arena/01a03741-pulseairepo`

**Repair commit to validate:** `aaeacc26e192db3ce55f8b7c0a5bb4e9d056ad4f`

**Open PR:** #9 — do not merge

> This handoff authorizes one provider-free Windows deterministic validation of
> the post-Attempt-11 completion-integrity repair. It does not authorize a
> provider probe/request, live Test-5 turn, dependency installation, source
> repair, cap increase, PR merge, branch deletion, or Agentic UI work.

## Objective

Validate that Windows behavior matches the deterministic contracts for:

1. canonical `stopstop → stop` and `tool_callstool_calls → tool_calls` metadata
   while retaining raw reasons;
2. explicit UTF-8 terminal subprocess transport;
3. complete tool-event forwarding before `turn_done`;
4. propagation of `finalize_node.task_completed` to the bridge;
5. `completed=false` for unverified or failed work; and
6. replacement of premature “I will inspect next” text with the honest finalize
   summary.

This validation cannot establish a live runtime or product PASS.

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

From the existing repository PowerShell window:

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
git merge-base --is-ancestor aaeacc26e192db3ce55f8b7c0a5bb4e9d056ad4f HEAD
if ($LASTEXITCODE -ne 0) {
  throw "Required repair is not an ancestor of $validationHead"
}
```

If fast-forward fails, STOP. Do not repair the checkout with reset or rebase.

## Step 2 — Create immutable evidence

```powershell
$evidence = 'bench-results\test5-11-completion-repair-validation-windows'
if (Test-Path $evidence) {
  throw 'Evidence directory already exists; do not overwrite it'
}
New-Item -ItemType Directory -Path $evidence | Out-Null
$started = (Get-Date).ToUniversalTime().ToString('o')
"$started VALIDATION_START" | Set-Content "$evidence\monitor.log" -Encoding utf8
```

Record command start/end timestamps in `monitor.log`. If a command runs longer
than 30 seconds, append a timestamped heartbeat every 30 seconds. This is not a
live provider test, but the evidence must still show command liveness.

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

## Step 4 — Run the exact focused suite

```powershell
"$((Get-Date).ToUniversalTime().ToString('o')) FOCUSED_START" | Add-Content "$evidence\monitor.log"
& $python -m pytest -q `
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
  2>&1 | Tee-Object -FilePath "$evidence\focused-tests.log"
$focusedExit = $LASTEXITCODE
"$((Get-Date).ToUniversalTime().ToString('o')) FOCUSED_END exit=$focusedExit" | Add-Content "$evidence\monitor.log"
```

Expected result:

```text
145 collected, 145 passed
```

Do not substitute a provider-backed smoke test if this fails.

## Step 5 — Protocol, compilation, and diff checks

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
  src/graphs/chat_graph.py
$compileExit = $LASTEXITCODE
@{
  exit_code = $compileExit
  modules = @(
    'src/llm/factory.py',
    'src/tools/terminal_tools.py',
    'src/bridge/__main__.py',
    'src/graphs/chat_graph.py'
  )
} | ConvertTo-Json -Depth 3 | Set-Content "$evidence\compile-outcome.json" -Encoding utf8

git diff --check 2>&1 | Tee-Object -FilePath "$evidence\git-diff-check.log"
$diffExit = $LASTEXITCODE
"$((Get-Date).ToUniversalTime().ToString('o')) CHECKS_END protocol=$protocolExit generation=$generationExit compile=$compileExit diff=$diffExit" | Add-Content "$evidence\monitor.log"
```

Expected protocol result: 7/7 passed. Expected generation, compilation, and diff
exit codes: zero.

## Step 6 — Record a bounded summary

Create `validation_summary.json` containing only:

- UTC start/end timestamps;
- repository root, remote, branch, and current head;
- repair commit `aaeacc26e192db3ce55f8b7c0a5bb4e9d056ad4f`;
- OS and Python version;
- exact allowlisted test filenames;
- collected/passed/failed/skipped counts and exit codes;
- protocol generation, compilation, and diff-check exit codes;
- `provider_probes: 0` and `provider_requests: 0`;
- clean checkout status before validation;
- deterministic verdict; and
- `This is not live runtime/product PASS evidence.`

Verdict rules:

- `DETERMINISTIC_PASS` only if focused tests are 145/145, protocol tests are
  7/7, all other checks return zero, the repair is an ancestor, and provider
  probe/request counts are zero.
- Otherwise record `DETERMINISTIC_FAIL`, preserve the first failure, and STOP.

Save exactly these evidence classes:

```text
checkout.txt
python-version.log
monitor.log
focused-tests.log
protocol-tests.log
protocol-generation.log
compile-outcome.json
git-diff-check.log
validation_summary.json
sha256sums.txt
```

Empty successful logs must still be represented by an explicit JSON outcome or
receipt. Do not save an environment dump, `.env`, credentials, unrelated file
listings, or prompts.

Generate `sha256sums.txt` after every other evidence file is final and include
each of those files exactly once.

## Step 7 — Commit and push evidence only

```powershell
git status --short
```

Only the new evidence directory may be present. If source, tests, historical
evidence, or unrelated paths changed, preserve the state and STOP for review.

```powershell
git add bench-results/test5-11-completion-repair-validation-windows
git commit -m "test: validate Attempt 11 completion repair on Windows"
git push origin arena/01a03741-pulseairepo
```

Do not merge PR #9.

## Final response and mandatory STOP

Report only:

1. repository root, branch, validation head, and repair commit;
2. deterministic verdict and exact counts;
3. provider probes/requests, both zero;
4. evidence directory and commit hash;
5. first failed boundary, if any; and
6. `STOPPED — no live attempt authorized`.

Then STOP. No live provider attempt, source repair, merge, branch deletion, or
Agentic UI work is authorized by this handoff.
