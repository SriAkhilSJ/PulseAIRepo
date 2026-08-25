# Desktop Agent Instructions — Deterministic Repair Validation Only

**Updated:** 2026-08-25

**Required branch:** `arena/01a03741-pulseairepo`

**Repair commit to validate:** `0bb00413f4a03b0172c4f6214018bad156fb1d2a`

**Open PR:** #9 — do not merge

> The founder authorized preparation of this desktop handoff. This handoff
> authorizes **provider-free deterministic validation only**. It does not
> authorize an OpenRouter, Sarvam, or other provider probe/request; a live Test-5
> attempt; a cap increase; source repair; PR merge; branch deletion; or Agentic
> UI work.

## Objective

Validate on the existing correct Windows repository checkout that the committed
Attempt-10 repair:

1. preserves raw finish metadata and canonicalizes LangChain's exact
   `lengthlength` aggregation to `length`;
2. routes empty output-limit responses through at most three dedicated
   continuation calls;
3. continues to reject incomplete tool calls with paired `ToolMessage` errors
   and executes none of their arguments;
4. emits bounded usage/reasoning telemetry without hidden reasoning or tool
   arguments;
5. survives an injected heartbeat-console `OSError` and preserves a sanitized,
   bounded runner traceback; and
6. recognizes OpenRouter budget discovery through an `openrouter.ai` custom
   base URL without making a network request.

This validation can establish deterministic Windows parity only. It must not be
reported as a runtime or product PASS.

## Hard safety boundaries

- Use the **existing correct PulseAI repository folder**. Do not use an old
  checkout, a Test-5 generated workspace, an Arena path, or a second clone.
- Do not recreate `C:\test5-ws-attempt5`.
- Do not modify or delete any preserved Attempt-5 through Attempt-10 evidence.
- Do not print, read into evidence, commit, or transmit credentials.
- Do not run provider preflight, probe, bridge live turn, guarded live wrapper,
  or any command that can call a model endpoint.
- Do not install or upgrade dependencies. If the existing environment cannot
  run the focused tests, record the missing dependency and STOP.
- Do not run the full test suite. Its unrelated environment/order-sensitive
  failures are documented in `docs/OUTPUT_LIMIT_RECOVERY_REPAIR.md`, and some
  tokenizer paths can attempt a dependency-data download.
- Do not edit runtime source to make a test pass. Evidence files and this
  handoff's status receipt are the only permitted changes.
- Never use `git reset --hard`, `git clean`, force push, or branch switching.

## Preserve exactly

```text
C:\test5-ws-attempt6
C:\test5-ws-attempt8
C:\test5-ws-attempt9
C:\test5-ws-attempt10
bench-results\test5-5\
bench-results\test5-6\
bench-results\test5-8-desktop\
bench-results\test5-stream-parity-validation\
bench-results\test5-stream-parity-validation-followup\
bench-results\test5-9-desktop\
bench-results\test5-10-desktop\
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
```

Attempt-10 evidence commit
`e344bc00e6de2961a2695d4fc7cfa7401ad64c87` remains immutable.

## Step 1 — Prove the checkout before changing anything

From the existing repository's PowerShell window, capture only non-secret Git
identity data:

```powershell
$ErrorActionPreference = 'Stop'
$branch = git branch --show-current
$root = git rev-parse --show-toplevel
$remote = git remote get-url origin
$headBefore = git rev-parse HEAD
$statusBefore = git status --porcelain=v1

if ($branch -ne 'arena/01a03741-pulseairepo') {
  throw "Wrong branch: $branch"
}
if ($remote -notmatch 'SriAkhilSJ/PulseAIRepo') {
  throw "Wrong repository remote"
}
if ($statusBefore) {
  throw "Checkout is not clean; preserve it and STOP without resetting"
}
```

Do not echo environment variables. Do not search for credentials.

## Step 2 — Fast-forward the fixed branch

```powershell
git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
$validationHead = git rev-parse HEAD
git merge-base --is-ancestor 0bb00413f4a03b0172c4f6214018bad156fb1d2a HEAD
if ($LASTEXITCODE -ne 0) {
  throw "Required repair commit is not an ancestor of $validationHead"
}
```

If the branch cannot fast-forward cleanly, record the error and STOP. Do not
resolve it by resetting, rebasing, or making source edits.

## Step 3 — Create a new evidence directory

Use this exact path unless it already exists:

```powershell
$evidence = 'bench-results\test5-output-limit-repair-validation-windows'
if (Test-Path $evidence) {
  throw "Evidence path already exists; do not overwrite graded evidence"
}
New-Item -ItemType Directory -Path $evidence | Out-Null
```

Record timestamps before and after every command. The tests are expected to be
short, so 30-second live-test monitoring is not applicable; there is no live
provider test. If any command exceeds 30 seconds, append a timestamped heartbeat
to `monitor.log` every 30 seconds without interrupting it.

## Step 4 — Disable provider credentials in this child shell

This is defense in depth. Do not record old values.

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

Do not run any test outside the exact allowlist below.

## Step 5 — Run the focused deterministic contract

Use the repository's existing Python environment. If `.venv\Scripts\python.exe`
exists, use it; otherwise use the already configured `python`. Do not install
anything.

```powershell
$python = if (Test-Path '.venv\Scripts\python.exe') {
  (Resolve-Path '.venv\Scripts\python.exe').Path
} else {
  'python'
}

& $python -m pytest -q `
  src/tests/test_retry_proxy_stream_cleanup.py `
  src/tests/test_output_limit_recovery.py `
  src/tests/test_model_budgets.py `
  src/tests/test_run_bridge_turn.py `
  src/tests/test_autonomous_runtime_contract.py `
  src/tests/test_bridge.py `
  src/tests/test_desktop_sidecar_architecture.py `
  2>&1 | Tee-Object -FilePath "$evidence\focused-tests.log"
$focusedExit = $LASTEXITCODE
```

Expected collection/result at the repair commit:

```text
70 passed
```

Then run the protocol and syntax checks:

```powershell
& $python -m pytest -q src/tests/test_bridge_protocol_v2.py `
  2>&1 | Tee-Object -FilePath "$evidence\protocol-tests.log"
$protocolExit = $LASTEXITCODE

& $python scripts/generate_bridge_protocol.py --check `
  2>&1 | Tee-Object -FilePath "$evidence\protocol-generation.log"
$generationExit = $LASTEXITCODE

& $python -m compileall -q `
  src/llm/factory.py `
  src/graphs/chat_graph.py `
  src/graphs/gates.py `
  src/graphs/state.py `
  src/context/model_budgets.py `
  scripts/run_bridge_turn.py `
  2>&1 | Tee-Object -FilePath "$evidence\compile.log"
$compileExit = $LASTEXITCODE
```

Do not substitute a provider-backed smoke test for any failed deterministic
check.

## Step 6 — Record bounded evidence

Create `validation_summary.json` containing only:

- UTC start/end timestamps;
- repository remote, branch, and validated commit;
- OS and Python version;
- exact command names (not environment values);
- each exit code and parsed pass/fail/skip counts;
- `provider_requests: 0` and `provider_probes: 0`;
- whether the source checkout was clean before validation;
- final deterministic verdict; and
- an explicit statement that this is not runtime/product PASS evidence.

Also save:

```text
checkout.txt
monitor.log
focused-tests.log
protocol-tests.log
protocol-generation.log
compile.log
validation_summary.json
sha256sums.txt
```

`checkout.txt` may contain only the root path, remote, branch, before/after
commit hashes, and porcelain status. `sha256sums.txt` must cover every other
file in this new evidence directory. Do not include an environment dump,
credential status, `.env` contents, prompts, or unrelated filesystem listings.

Deterministic verdict rules:

- `DETERMINISTIC_PASS` only if all four commands return zero, 70 focused tests
  pass, 7 protocol tests pass, generation is current, compilation succeeds,
  and no provider traffic occurred.
- Otherwise use `DETERMINISTIC_FAIL`, preserve the first failing boundary, and
  STOP. Do not repair source.

Neither verdict is a Test-5 runtime or product verdict.

## Step 7 — Commit and push evidence only

First prove that no tracked source changed:

```powershell
git status --short
```

Only the new evidence directory and the minimal handoff status update may be
present. If runtime source, tests, preserved evidence, or unrelated files
changed, do not discard them; record the unexpected paths and STOP for review.

Commit and push on the required branch:

```powershell
git add bench-results/test5-output-limit-repair-validation-windows DESKTOP_AGENT_INSTRUCTIONS.md
git commit -m "test: validate output-limit repair on Windows"
git push origin arena/01a03741-pulseairepo
```

If `DESKTOP_AGENT_INSTRUCTIONS.md` has no desktop status update, stage only the
evidence directory. Record the resulting commit hash in the final response.

## Mandatory final response and STOP

Report only:

1. validated repository root, branch, and repair commit;
2. deterministic verdict and exact test counts;
3. provider probes/requests, both expected to be zero;
4. evidence directory and evidence commit hash;
5. first failing boundary, if any; and
6. `STOPPED — no live attempt authorized`.

After pushing evidence, STOP. Do not merge PR #9, delete any branch, run a
provider request, or begin Agentic UI work.
