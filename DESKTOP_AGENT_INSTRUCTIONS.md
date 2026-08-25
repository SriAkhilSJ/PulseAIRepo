# Desktop Agent Instructions — Test 5 Attempt 5

**Updated:** 2026-08-25
**Repository:** `https://github.com/SriAkhilSJ/PulseAIRepo`
**Integration branch:** `arena/01a03741-pulseairepo`
**Required code commit:** `3d89cbc8` plus the Test-5 approval hardening, or newer
**Credit situation:** approximately 50 credits remain

> These instructions supersede every older instruction in this file. Read the entire document before running anything. Do not improvise, expose credentials, rerun a failed probe, or merge based only on `turn_done`.

## 1. Mission

Run **one** guarded provider-backed Test 5 attempt on the founder's Windows desktop, preserve complete evidence, independently inspect the delivered website, and report PASS or FAIL honestly.

The Arena environment could not establish TLS with `api.sarvam.ai`; the desktop previously could. Therefore this run must happen on the desktop.

Test 5 is the GARGANTUA Schwarzschild black-hole raytracer task in:

```text
scripts/test5_prompt.txt
```

Attempts 1–3 and desktop attempt `test5-4b` are recorded failures. Attempt 4b reached a roughly 30KB `write_file` but produced no files because the headless bridge requested interactive approval and nobody replied. This is a fresh **attempt 5** after repairing that approval deadlock; it remains a retest candidate, not an already-proven pass.

## 2. Sync the correct GitHub branch

Do not use the old agent branch `arena/01a02a5c-pulseairepo` directly. Its six useful Test-5 commits were reviewed and selectively integrated into the current R4 desktop branch, then the integration defects and the attempt-4b approval deadlock were fixed.

From the repository root in PowerShell:

```powershell
git status --short --branch
```

If tracked or untracked work exists, preserve it first:

```powershell
git stash push -u -m "pre-test5-attempt5"
```

Then sync:

```powershell
git fetch origin --prune
git switch arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
git log --oneline -5
```

Verify that the reviewed integration baseline is included:

```powershell
git merge-base --is-ancestor 3d89cbc8 HEAD
if ($LASTEXITCODE -ne 0) { throw "Wrong/stale branch: 3d89cbc8 is missing" }
if (-not (Select-String -Path scripts\run_bridge_turn.py -Pattern "PULSEAI_BRIDGE_APPROVAL_POLICY" -Quiet)) {
  throw "Missing Test-5 approval hardening"
}
```

Required files:

```powershell
@(
  "scripts\run_bridge_turn.py",
  "scripts\run_test5_guarded.ps1",
  "scripts\test5_prompt.txt",
  "docs\TEST5_READINESS.md"
) | ForEach-Object {
  if (-not (Test-Path $_)) { throw "Missing required file: $_" }
}
```

Do not merge either old agent branch into this checkout. A whole-tree merge would regress the current vendored Code OSS/R4 desktop state.

## 3. Protect the provider key

Use the desktop's private, gitignored `.env`. Never copy a key into README, source code, a commit, terminal output, screenshot, issue, or chat.

`.env` must contain:

```env
LLM_PROVIDER=custom
LLM_MODEL=sarvam-105b-conversations
CONTEXT_MODEL=sarvam-105b-conversations
CUSTOM_BASE_URL=https://api.sarvam.ai/v1
CUSTOM_API_KEY=<private key>
SUMMARIZER_LLM=aux
PROVIDER_SAFE_LIMIT=0
```

Safety checks:

```powershell
git check-ignore .env
if ($LASTEXITCODE -ne 0) { throw ".env is not ignored — STOP" }

git status --short
```

The historical README key was publicly committed and later removed. Prefer a rotated private key. Never print either key to prove it exists.

Verify the Python environment without making a provider call:

```powershell
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  throw "Missing repository venv — STOP and report"
}

.\.venv\Scripts\python.exe -c "import langchain_core, langgraph, PIL; print('runtime dependencies OK')"
```

## 4. Prepare a fresh workspace and run ID

Do not reuse previous workspaces or evidence directories.

```powershell
$Workspace = "C:\test5-ws-attempt5"
$RunId = "test5-5"

if (Test-Path $Workspace) {
  throw "$Workspace already exists. Choose a fresh empty path; do not delete evidence blindly."
}
if (Test-Path "bench-results\$RunId") {
  throw "Run ID already exists. Choose a fresh ID; evidence is immutable."
}
```

## 5. Run exactly one guarded attempt

The limits below are deliberate for the remaining credits:

- maximum 20 observed LLM request frames;
- maximum approximately 180,000 cumulative input tokens;
- 90-minute hard cap;
- 600-second stall cap for long package installs/build activity;
- watchdog status every 30 seconds.

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_test5_guarded.ps1 `
  -Workspace $Workspace `
  -RunId $RunId `
  -MaxMinutes 90 `
  -StallSeconds 600 `
  -MaxLlmCalls 20 `
  -MaxInputTokens 180000
```

### Monitoring rules

The script prints a watchdog line every 30 seconds. Watch it continuously.

- If the 8-token preflight fails: **STOP. Do not retry.** Record the exact error without credentials.
- If the provider repeatedly fails before producing a response: stop after diagnosis; do not burn through the cap merely because the cap exists.
- A quiet `npm install` may still be healthy. Workspace file changes and CPU activity count as heartbeats; do not kill a healthy build manually.
- Let the circuit breaker cancel at either budget limit.
- Never increase a limit during the run.
- Never intervene in the workspace or help the agent complete the product. Human edits make the autonomous benchmark invalid.

Emergency stop, only if the wrapper itself fails to stop the tree:

```powershell
taskkill /T /F /PID <runner-pid>
```

## 6. Runtime evidence required

After the process exits, preserve and inspect:

```text
bench-results\test5-5\frames.jsonl
bench-results\test5-5\bridge_stderr.log
bench-results\test5-5\outcome.json
```

Print only sanitized summaries:

```powershell
Get-Content "bench-results\$RunId\outcome.json"
Get-Content "bench-results\$RunId\bridge_stderr.log" -Tail 80
```

Immediate runtime FAIL conditions:

- missing `outcome.json`;
- `result` is not `turn_done`;
- `completed` is not `true`;
- `budget_stop` is `true`;
- provider/bridge crash;
- watchdog kill;
- human intervention;
- no meaningful source files delivered.

`turn_done` is necessary but **not sufficient** for product PASS.

## 7. Independently grade the delivered product

Do not modify the agent's output while grading it.

### Delivery checks

The workspace must contain executable source, startup instructions, local Three.js dependencies/assets, and meaningful implementation files—not only `package.json` or a scaffold.

```powershell
Get-ChildItem $Workspace -Recurse -File |
  Select-Object FullName, Length |
  Format-Table -AutoSize
```

Confirm there is no required external CDN dependency and no mandatory build step, because the task explicitly requires native HTML/CSS/JavaScript modules, local Three.js files, and a basic static server.

### Static/runtime checks

Follow the delivered startup instructions exactly. At minimum verify:

1. The page loads from a basic static server.
2. There is no black/blank screen.
3. Browser console has no unhandled errors.
4. The subject is rendered by a full-screen fragment shader, not substituted meshes/images/video.
5. Event horizon, photon ring, lensed accretion disk, and starfield are visibly present.
6. Orbit controls/cinematic camera paths work.
7. Four presets work.
8. Telemetry HUD appears.
9. The 21 live parameters are present and responsive.
10. Debug views 0–9 and documented hotkeys respond.
11. Quality profiles work.
12. Deterministic screenshot mode is URL-driven and reproducible.
13. Responsive/Retina behavior does not break rendering.
14. WebGL recovery is implemented or demonstrably handled.

Capture:

- one 1280×800 default screenshot;
- screenshots for all four presets;
- one debug-view screenshot;
- browser-console evidence;
- the exact URL used for deterministic screenshot mode.

Do not call the result PASS if major visual requirements are represented only by comments, labels, or placeholder UI.

## 8. Final verdict format

Report exactly:

```text
TEST 5 ATTEMPT 5
Git commit: <git rev-parse HEAD>
Run ID: test5-5
Runtime verdict: PASS | FAIL
Product verdict: PASS | FAIL
Human interventions: 0 | <count and details>
LLM request frames: <count>
Approx input tokens: <count>
Budget stop: true | false
Watchdog kill: true | false
Files delivered: <count>
Static server command: <command>
Console errors: <count>
Screenshots: <paths>
Blocking defects: <none or exact list>
Overall verdict: PASS only when runtime AND product pass
```

Never report the key.

## 9. GitHub merge procedure — only after a verified PASS

Do not merge or delete branches merely because the process exited zero.

First ensure the integration branch is pushed and create/reuse its PR:

```powershell
git status --short --branch
git push origin arena/01a03741-pulseairepo

gh pr list --head arena/01a03741-pulseairepo --base main
```

If no PR exists:

```powershell
gh pr create `
  --base main `
  --head arena/01a03741-pulseairepo `
  --title "fix(agent): Test 5 readiness and regression cleanup" `
  --body "See docs/TEST5_READINESS.md. Test 5 attempt 5 passed runtime and independent product verification; sanitized evidence is attached/referenced."
```

Check the complete diff summary, changed-file list, and checks before merging:

```powershell
git fetch origin main
git diff --stat origin/main...HEAD
gh pr diff --name-only
gh pr checks --watch
```

Merge only after the founder confirms the sanitized Test-5 evidence:

```powershell
gh pr merge --merge
```

### Branch deletion order

After GitHub confirms the PR is merged into `main`, verify ancestry:

```powershell
git fetch origin --prune
git merge-base --is-ancestor origin/arena/01a03741-pulseairepo origin/main
if ($LASTEXITCODE -ne 0) { throw "Integration branch is not in main — do not delete anything" }
```

Only then may the two superseded source branches be deleted:

```powershell
git push origin --delete arena/01a02954-pulseairepo
git push origin --delete arena/01a02a5c-pulseairepo
```

Do **not** delete `arena/01a03741-pulseairepo` while the active Arena session or PR still depends on it. Delete it through the GitHub PR UI only after the session is finished and `main` ancestry is verified.

## 10. If Test 5 fails

- Do not merge.
- Do not delete any branches.
- Do not rerun automatically.
- Preserve the workspace and `bench-results\test5-5\` exactly.
- Report the first root-cause boundary: provider, harness, planning, tool strategy, verification, or product quality.
- Wait for a code review/fix and explicit approval before spending more credits.
