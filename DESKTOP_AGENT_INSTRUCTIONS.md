# Desktop Agent Instructions — deterministic Attempt-8 postmortem validation only

**Updated:** 2026-08-25

**Repository:** `https://github.com/SriAkhilSJ/PulseAIRepo`

**Branch:** `arena/01a03741-pulseairepo`

**Required baseline:** `7f55a5de` or newer on this exact branch

> This handoff authorizes **zero-provider deterministic validation only**. Do
> not run Test 5, `test5.py`, a connectivity probe, Sarvam, or any other LLM.
> Do not merge PR #9, delete branches, modify preserved workspaces, or begin
> Agentic UI work.

## Mission

Validate the Windows behavior of the post-Attempt-8 repairs and push complete
receipts so Arena can inspect them. This is not authorization for Attempt 9.
The remaining Hermes parity gaps—stream completeness, finish-reason handling,
and partial-tool-call rejection—are still under Arena review.

## 1. Update the existing Windows clone

Use the existing clone containing the ignored `.venv` and `.env`; do not create
a second clone and do not open the Test-5 workspace as the repository.

```powershell
$RepoRoot = (git rev-parse --show-toplevel 2>$null)
if (-not $RepoRoot) { throw 'STOP: terminal is not inside the existing PulseAIRepo clone' }
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot.Trim())
Set-Location -LiteralPath $RepoRoot
if (-not (Test-Path 'scripts\run_test5_guarded.ps1')) {
  throw "STOP: wrong repository folder: $RepoRoot"
}
$Remote = (git remote get-url origin).Trim()
if ($Remote -notmatch 'SriAkhilSJ/PulseAIRepo(?:\.git)?$') {
  throw "STOP: wrong origin: $Remote"
}
$Dirty = @(git status --short --untracked-files=normal)
$Unexpected = @($Dirty | Where-Object {
  $_ -notmatch '^\?\? (bench-results/|\.env$|\.venv/|desktop/vscode/\.build/)'
})
if ($Unexpected.Count -gt 0) {
  $Unexpected
  throw 'STOP: local source changes exist; do not stash/reset/overwrite them'
}
$BeforeHead = (git rev-parse HEAD).Trim()
git fetch --prune origin
git checkout arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
if ($LASTEXITCODE -ne 0) { throw 'STOP: update was not a clean fast-forward' }
$Head = (git rev-parse HEAD).Trim()
$RemoteHead = (git rev-parse origin/arena/01a03741-pulseairepo).Trim()
if ($Head -ne $RemoteHead) { throw "STOP: stale clone local=$Head remote=$RemoteHead" }
git merge-base --is-ancestor 7f55a5de $Head
if ($LASTEXITCODE -ne 0) { throw 'STOP: required repair commit is missing' }
if (@(git status --short --untracked-files=no).Count -ne 0) {
  throw 'STOP: tracked tree is dirty after update'
}
Write-Host "SYNC PASS: $RepoRoot @ $Head"
```

Never print, inspect, copy, or commit `.env`. The validation shell shadows all
provider-key variables with empty values and blocks outbound proxy traffic, so
an accidental client construction cannot spend credits.

## 2. Prove preserved evidence is untouched

Do not edit these paths:

```text
C:\test5-ws-attempt5
C:\test5-ws-attempt6
C:\test5-ws-attempt8
bench-results\test5-5\
bench-results\test5-6\
bench-results\test5-8-desktop\
```

Record the committed Attempt-8 evidence tree before validation:

```powershell
$Receipt = 'bench-results\test5-8-postmortem-validation'
if (Test-Path $Receipt) { throw "STOP: receipt directory exists: $Receipt" }
New-Item -ItemType Directory -Path $Receipt | Out-Null
git ls-tree -r 6586d7af -- 'bench-results/test5-8-desktop' |
  Out-File "$Receipt\attempt8-evidence-tree-before.txt" -Encoding utf8
```

## 3. Enforce a zero-provider environment

Use the existing venv only. Do not install dependencies or invoke any wrapper
that reads `.env`.

```powershell
$Python = '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'STOP: existing venv Python is missing' }
$env:PULSEAI_DISABLE_LONG_TERM_MEMORY = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:NO_PROXY = ''
$env:HTTP_PROXY = 'http://127.0.0.1:9'
$env:HTTPS_PROXY = 'http://127.0.0.1:9'
$env:ALL_PROXY = 'http://127.0.0.1:9'
$env:CUSTOM_API_KEY = ''
$env:OPENAI_API_KEY = ''
$env:GROQ_API_KEY = ''
$env:GEMINI_API_KEY = ''
$env:NVIDIA_API_KEY = ''
```

The invalid loopback proxy is intentional: a mistaken network call must fail
closed rather than spend credits.

## 4. Validate PowerShell syntax without running the harness

Parsing the wrapper must not execute it:

```powershell
$parseErrors = $null
$tokens = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path 'scripts\run_test5_guarded.ps1'),
  [ref]$tokens,
  [ref]$parseErrors
) | Out-Null
$parseErrors | ConvertTo-Json -Depth 6 |
  Out-File "$Receipt\powershell-parse-errors.json" -Encoding utf8
if ($parseErrors.Count -ne 0) {
  $parseErrors
  throw 'FAIL: guarded wrapper has PowerShell parse errors'
}
'PowerShell parse PASS' | Out-File "$Receipt\powershell-parse.txt" -Encoding utf8
```

Then statically prove the wrapper contains all Attempt-8 guards:

```powershell
$Wrapper = Get-Content 'scripts\run_test5_guarded.ps1' -Raw
$Required = @(
  '$env:PULSEAI_DISABLE_LONG_TERM_MEMORY = "1"',
  'function Write-WatchdogOutcome',
  '-Result "watchdog-hard-cap"',
  '-Result "watchdog-stalled"',
  'llm={3} files={4} bytes={5}'
)
$Missing = @($Required | Where-Object {
  $Wrapper.IndexOf($_, [System.StringComparison]::Ordinal) -lt 0
})
[pscustomobject]@{
  required = $Required
  missing = $Missing
  passed = ($Missing.Count -eq 0)
} | ConvertTo-Json -Depth 5 |
  Out-File "$Receipt\wrapper-static-contract.json" -Encoding utf8
if ($Missing.Count -ne 0) { throw "FAIL: wrapper contracts missing: $Missing" }
```

## 5. Run focused tests with complete logs

Run only these local tests:

```powershell
$Tests = @(
  'src/tests/test_progress_helpers.py',
  'src/tests/test_retry_proxy.py',
  'src/tests/test_retry_proxy_stream_cleanup.py',
  'src/tests/test_autonomous_runtime_contract.py',
  'src/tests/test_cancellation_gates.py',
  'src/tests/test_test5_guarded_script.py'
)
& $Python -m pytest -q @Tests --disable-warnings --maxfail=1 *>&1 |
  Tee-Object -FilePath "$Receipt\pytest.log"
$PytestExit = $LASTEXITCODE
[pscustomobject]@{
  exit_code = $PytestExit
  tests = $Tests
  provider_calls_authorized = 0
  network_blocked = $true
} | ConvertTo-Json -Depth 5 |
  Out-File "$Receipt\pytest-outcome.json" -Encoding utf8
if ($PytestExit -ne 0) { throw "FAIL: focused pytest exit=$PytestExit" }
```

Compile changed Python modules:

```powershell
& $Python -m py_compile `
  src\graphs\chat_graph.py `
  src\llm\factory.py *>&1 |
  Tee-Object -FilePath "$Receipt\py-compile.log"
$CompileExit = $LASTEXITCODE
[pscustomobject]@{ exit_code = $CompileExit } | ConvertTo-Json |
  Out-File "$Receipt\py-compile-outcome.json" -Encoding utf8
if ($CompileExit -ne 0) { throw "FAIL: py_compile exit=$CompileExit" }
```

## 6. Record post-validation integrity

```powershell
git diff --check *>&1 | Tee-Object -FilePath "$Receipt\git-diff-check.log"
$DiffExit = $LASTEXITCODE
git ls-tree -r 6586d7af -- 'bench-results/test5-8-desktop' |
  Out-File "$Receipt\attempt8-evidence-tree-after.txt" -Encoding utf8
$BeforeTree = Get-Content "$Receipt\attempt8-evidence-tree-before.txt" -Raw
$AfterTree = Get-Content "$Receipt\attempt8-evidence-tree-after.txt" -Raw
[pscustomobject]@{
  evidence_tree_unchanged = ($BeforeTree -ceq $AfterTree)
  diff_check_exit = $DiffExit
  head = $Head
  repo_root = $RepoRoot
  timestamp = (Get-Date).ToString('o')
} | ConvertTo-Json -Depth 4 |
  Out-File "$Receipt\validation-summary.json" -Encoding utf8
if ($BeforeTree -cne $AfterTree) { throw 'FAIL: preserved Attempt-8 evidence changed' }
if ($DiffExit -ne 0) { throw 'FAIL: git diff --check failed' }
```

Create SHA-256 receipts. Because `bench-results/**` is now `-text`, these bytes
must survive Git unchanged:

```powershell
Get-ChildItem $Receipt -Recurse -File | ForEach-Object {
  [pscustomobject]@{
    path = $_.FullName.Substring((Resolve-Path $Receipt).Path.Length + 1)
    bytes = $_.Length
    sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
  }
} | ConvertTo-Json -Depth 4 |
  Out-File "$Receipt\receipt-manifest.json" -Encoding utf8
```

## 7. Commit and push receipts for Arena verification

Only the fresh validation receipt directory may be staged:

```powershell
git add -f -- 'bench-results/test5-8-postmortem-validation'
$Staged = @(git diff --cached --name-only)
$UnexpectedStaged = @($Staged | Where-Object {
  $_ -notlike 'bench-results/test5-8-postmortem-validation/*'
})
if ($UnexpectedStaged.Count -gt 0) {
  $UnexpectedStaged
  throw 'STOP: unrelated files staged'
}
git commit -m "evidence: validate Attempt 8 post-tool repairs on Windows"
git push origin arena/01a03741-pulseairepo
$EvidenceCommit = (git rev-parse HEAD).Trim()
Write-Host "EVIDENCE PUSH PASS: $EvidenceCommit"
git status --short
```

If Git commit/push fails, do not run Test 5. Preserve receipts and report the
Git error.

## 8. Report and stop

Report:

- local repository path and synced source commit;
- PowerShell parser result;
- wrapper static-contract result;
- pytest count/result and exit code;
- py_compile and diff-check results;
- evidence-tree unchanged result;
- validation receipt commit SHA and push status;
- final `git status --short`;
- provider calls: exactly zero.

Then stop. No Test-5 run, provider probe, product modification, PR merge, branch
deletion, or Agentic UI work is authorized.
