# Desktop Agent Instructions — guarded Test 5 Attempt 6

**Authorized:** 2026-08-25 by the founder

**Repository:** `https://github.com/SriAkhilSJ/PulseAIRepo`

**Branch:** `arena/01a03741-pulseairepo`

**Required reliability commit:** `6d31b0b8` or newer

**PR:** `https://github.com/SriAkhilSJ/PulseAIRepo/pull/9`

> Run exactly one provider-backed attempt. Monitor every 30 seconds, preserve immutable evidence, and grade runtime and product independently. Do not retry a failure. Merge/branch cleanup is permitted only after both verdicts pass.

## 1. Mission and prior boundary

Test 5 is the GARGANTUA raytracer task in `scripts/test5_prompt.txt`. Attempt `test5-5` exhausted 20 requests in platform discovery, empty-workspace verification, replanning, and dependency acquisition without writing a file.

Attempt 6 tests the reviewed repairs:

- Windows `cmd.exe` is stated before tool use and POSIX-only commands are rejected before spawn;
- unavailable typecheck is hidden and cannot trigger phantom KEEP/REPLAN calls;
- deterministic policy/platform outcomes do not pay for a replan classifier;
- required-delivery tasks warn after two main-agent iterations without a mutation;
- after four such iterations, only delivery capabilities remain until a file lands;
- explicit BM25-only indexing cannot enter Hugging Face download retries;
- headless workspace mutations use the repaired workspace-scoped approval path.

This is a candidate, not a claimed pass.

## 2. Sync and prove the branch

From the repository root in PowerShell:

```powershell
git status --short --branch
```

If anything is modified or untracked, preserve it—never delete it:

```powershell
git stash push -u -m "pre-test5-attempt6"
```

Sync:

```powershell
git fetch origin --prune
git switch arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
git log --oneline -6
git status --short --branch
```

Require the repair baseline:

```powershell
git merge-base --is-ancestor 6d31b0b8 HEAD
if ($LASTEXITCODE -ne 0) { throw "Stale branch: 6d31b0b8 is missing" }

@(
  "docs\AGENT_RELIABILITY_PLAN.md",
  "scripts\run_bridge_turn.py",
  "scripts\run_test5_guarded.ps1",
  "scripts\test5_prompt.txt"
) | ForEach-Object {
  if (-not (Test-Path $_)) { throw "Missing required file: $_" }
}

if (-not (Select-String scripts\run_bridge_turn.py "PULSEAI_BRIDGE_APPROVAL_POLICY" -Quiet)) {
  throw "Missing headless approval repair"
}
if (-not (Select-String src\graphs\chat_graph.py "forced_delivery" -Quiet)) {
  throw "Missing pre-delivery no-progress repair"
}
```

Do not merge old branches into this checkout.

## 3. Provider key safety

Use only the private, gitignored desktop `.env`. Per the founder's standing instruction, if the desktop has no valid configured key, recover the historical README key locally and place it only in `.env` without printing it. Never put a key in terminal output, chat, screenshots, evidence, source, or Git.

Required effective settings:

```env
LLM_PROVIDER=custom
LLM_MODEL=sarvam-105b-conversations
CONTEXT_MODEL=sarvam-105b-conversations
CUSTOM_BASE_URL=https://api.sarvam.ai/v1
CUSTOM_API_KEY=<private value>
SUMMARIZER_LLM=aux
PROVIDER_SAFE_LIMIT=0
```

Validate without exposing values:

```powershell
git check-ignore .env
if ($LASTEXITCODE -ne 0) { throw ".env is not ignored — STOP" }
if (-not (Test-Path ".venv\Scripts\python.exe")) { throw "Missing .venv — STOP" }
.\.venv\Scripts\python.exe -c "import langchain_core, langgraph, PIL; print('runtime dependencies OK')"
```

Remove any temporary offline-validation variables from the current shell before the live run:

```powershell
Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:HF_HUB_DISABLE_TELEMETRY -ErrorAction SilentlyContinue
Remove-Item Env:PULSEAI_WEB_TOOLS -ErrorAction SilentlyContinue
```

## 4. Fresh immutable locations

```powershell
$Workspace = "C:\test5-ws-attempt6"
$RunId = "test5-6"

if (Test-Path $Workspace) { throw "$Workspace already exists — STOP; do not delete/reuse" }
if (Test-Path "bench-results\$RunId") { throw "Run ID exists — STOP; evidence is immutable" }
```

Preserve `C:\test5-ws-attempt5` and `bench-results\test5-5\` unchanged.

## 5. Run exactly once

Limits protect the remaining credits:

- 20 observed LLM requests maximum;
- approximately 180,000 cumulative input tokens maximum;
- 90-minute wall cap;
- 600-second activity-aware stall cap;
- watchdog output every 30 seconds.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_test5_guarded.ps1 `
  -Workspace $Workspace `
  -RunId $RunId `
  -MaxMinutes 90 `
  -StallSeconds 600 `
  -MaxLlmCalls 20 `
  -MaxInputTokens 180000
```

Monitoring rules:

- Watch continuously and record each 30-second watchdog status.
- If the tiny provider preflight fails, stop and do not retry.
- Never raise a limit during the run.
- Never edit/help the generated workspace.
- Do not manually approve tool calls; the repaired headless policy owns them.
- A quiet package install can be healthy when CPU/workspace activity continues.
- Let the breaker cancel at either budget cap.
- If the wrapper cannot stop a broken process tree, use `taskkill /T /F /PID <pid>` and grade runtime FAIL.
- Run no second provider-backed attempt.

## 6. Runtime verdict

Require and preserve:

```text
bench-results\test5-6\frames.jsonl
bench-results\test5-6\bridge_stderr.log
bench-results\test5-6\outcome.json
```

Inspect sanitized summaries:

```powershell
Get-Content "bench-results\$RunId\outcome.json"
Get-Content "bench-results\$RunId\bridge_stderr.log" -Tail 100
Get-ChildItem $Workspace -Recurse -File | Select-Object FullName, Length
```

Runtime FAIL if any condition holds:

- missing `outcome.json`;
- result is not `turn_done`;
- `completed` is not true;
- `budget_stop` is true;
- provider/bridge/watchdog crash or kill;
- human intervention;
- no meaningful source files;
- repeated platform-discovery or empty-verification loop;
- file mutations still have not landed after the forced-delivery threshold.

Report `llm_request_frames`, token estimate, `safety_requests`, `safety_approved`, and `safety_denied`. A clean `turn_done` is necessary but not a product pass.

## 7. Independent product grading

Do not modify the generated product. Follow its startup instructions exactly with the required basic static-server workflow.

Verify in a real browser:

1. no blank/black failure screen or unhandled console errors;
2. full-screen fragment-shader rendering—not substitute meshes/images/video;
3. visible event horizon, photon ring, lensed accretion disk, and starfield;
4. orbit controls and cinematic camera paths;
5. all four presets;
6. telemetry HUD;
7. all 21 live parameters present and responsive;
8. debug views 0–9 and documented hotkeys;
9. quality profiles;
10. reproducible URL-driven deterministic screenshot mode;
11. responsive/Retina rendering;
12. WebGL recovery;
13. local Three.js assets/dependencies with no forbidden required CDN/build workflow.

Capture:

- 1280×800 default screenshot;
- all four presets;
- one debug view;
- browser-console evidence;
- exact deterministic screenshot URL.

Comments, labels, placeholders, or partial stubs do not pass.

## 8. Exact report

```text
TEST 5 ATTEMPT 6
Git commit: <exact HEAD>
PR: https://github.com/SriAkhilSJ/PulseAIRepo/pull/9
Run ID: test5-6
Runtime verdict: PASS | FAIL
Product verdict: PASS | FAIL
Human interventions: 0 | <details>
LLM request frames: <count>
Approx input tokens: <count>
Safety requests: <count>
Safety approved: <count>
Safety denied: <count>
Budget stop: true | false
Watchdog kill: true | false
Files delivered: <count>
Static server command: <command>
Console errors: <count>
Screenshots: <paths>
Blocking defects: <none or exact list>
Overall verdict: PASS only if runtime AND product pass
```

Never report the key.

## 9. Failure rule

If either verdict fails:

- do not merge PR #9;
- do not delete branches;
- do not rerun;
- preserve the workspace and `bench-results\test5-6\` exactly;
- report the first confirmed boundary and stop.

## 10. PASS-only consolidation

Only if runtime and product both pass:

```powershell
git status --short --branch
git push origin arena/01a03741-pulseairepo
gh pr view 9
gh pr diff 9 --name-only
gh pr checks 9
```

Review the complete PR diff and sanitized evidence, then merge PR #9:

```powershell
gh pr merge 9 --merge
```

Verify containment:

```powershell
git fetch origin --prune
git merge-base --is-ancestor origin/arena/01a03741-pulseairepo origin/main
if ($LASTEXITCODE -ne 0) { throw "PR branch is not contained in main — delete nothing" }
```

After a verified merge, old superseded branches may be removed only after confirming they have no unintegrated intended work. Do **not** delete `arena/01a03741-pulseairepo` while this Arena session remains active. Stop and report the merge receipt before beginning Agentic UI work.
