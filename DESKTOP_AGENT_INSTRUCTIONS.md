# Desktop Agent Instructions — authorized Test 5 Attempt 9

**Updated:** 2026-08-25

**Branch:** `arena/01a03741-pulseairepo`

**Repaired implementation:** `b82381d36662e2f0dc9262bafafbedd8508318d6`

**Required deterministic evidence:**

- `503c1972884d6ee190aafb3d9fce7227ef255e84` — initial 42 tests;
- `496591a10e93b13d32065b3ac04d74f89d9fecde` — omitted 8 tests;
- combined Windows result: 50/50 passed, zero provider calls.

> The founder explicitly authorized exactly one live Test 5 Attempt 9. This
> authorization includes one eight-token Sarvam connectivity probe and one
> guarded provider-backed turn. It does not authorize a retry, a second probe,
> PR merge, branch deletion, source repair during the run, or Agentic UI work.

## 1. Fixed locations and identity

Use only the existing correct repository:

```text
D:\pulseAIagent\PulseAIRepo
```

Use exactly:

```text
Run ID:     test5-9-desktop
Workspace:  C:\test5-ws-attempt9
Evidence:   bench-results\test5-9-desktop\
Prompt:     scripts\test5_prompt.txt
Provider:   Sarvam custom OpenAI-compatible endpoint
Model:      sarvam-105b-conversations
```

Do not use an old checkout, Arena filesystem path, generated workspace, second
clone, or previous Test-5 workspace.

## 2. Mandatory preconditions — STOP without provider traffic if any fail

1. Confirm the existing checkout is clean and on
   `arena/01a03741-pulseairepo`.
2. Fetch origin and fast-forward the existing local branch to
   `origin/arena/01a03741-pulseairepo`. Never detach HEAD, reset, force-push,
   switch/create a branch, or create another clone.
3. Record the full run-parent commit and prove:

   ```text
   git rev-parse HEAD == git rev-parse origin/arena/01a03741-pulseairepo
   git merge-base --is-ancestor b82381d36662e2f0dc9262bafafbedd8508318d6 HEAD
   git merge-base --is-ancestor 503c1972884d6ee190aafb3d9fce7227ef255e84 HEAD
   git merge-base --is-ancestor 496591a10e93b13d32065b3ac04d74f89d9fecde HEAD
   ```

4. Confirm both are absent. Freshness is mandatory; do not delete/reuse either:

   ```text
   C:\test5-ws-attempt9
   bench-results\test5-9-desktop
   ```

5. Confirm `scripts/test5_prompt.txt` is tracked and unchanged.
6. Parse `scripts/run_test5_guarded.ps1` with the PowerShell parser without
   executing it. Any parse error is a pre-provider STOP.
7. Record `git status --short`, Python/PowerShell versions, the full source
   commit, prompt SHA-256, wrapper SHA-256, and freshness checks in a temporary
   preflight receipt. Move it into the evidence directory after the runner
   creates that directory.
8. Record byte length/SHA-256 manifests of all preserved Test-5 evidence trees
   before the run. Attempt 9 must not modify them.

If a precondition fails, create a `PRECONDITION_STOP` receipt in a new Attempt-9
evidence directory, commit/push it, and stop with **zero provider requests**.

## 3. Credential handling

Use the credential the founder previously authorized from historical README at
commit `9e071f6143d616c7ecacb3e8096a4e115131ea5b`.

- Extract only the `CUSTOM_API_KEY` value directly into the gitignored `.env`.
- Never print, echo, screenshot, log, hash, commit, or paste the credential.
- Do not place it in PowerShell history or a command-line argument.
- Preserve/configure the non-secret custom base URL, provider, and model values
  expected by the guarded wrapper.
- Confirm `.env` is ignored and absent from `git status`.
- After evidence is committed, leave credential handling to the existing local
  secret policy; never add `.env` to Git.

## 4. Credit and runtime limits

Run exactly one foreground wrapper invocation with these bounds:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_test5_guarded.ps1 `
  -Workspace C:\test5-ws-attempt9 `
  -RunId test5-9-desktop `
  -MaxMinutes 45 `
  -StallSeconds 300 `
  -MaxLlmCalls 16 `
  -MaxInputTokens 120000 `
  -MaxNoDeliveryCalls 3
```

The wrapper performs the sole authorized eight-token probe before the turn.

- If the probe fails, the live turn must not start and no second probe is
  allowed.
- Do not rerun the wrapper for any reason.
- Do not raise caps while the run is active.
- The no-delivery breaker must cancel after 3 provider requests with no file.
- The request/input-token breaker, 300-second stall breaker, and 45-minute hard
  cap must remain active.
- Any cancellation or watchdog kill is final for Attempt 9.

Use a foreground console. Do not reintroduce `Start-Process` output redirection
for the bridge child. A PowerShell transcript may be started in a temporary
path and copied into the evidence directory afterward, provided output still
remains live in the console.

## 5. Active 30-second monitoring — mandatory

A human/desktop agent must actively inspect the live console, frames, outcome,
and workspace at least once every 30 seconds from wrapper start until exit.
The wrapper's own watchdog line is not sufficient proof of inspection.

Append one observation immediately at each interval to:

```text
bench-results\test5-9-desktop\monitor-30s.jsonl
```

Do not pre-create the run directory because the runner's freshness guard owns
its creation. If the first observation occurs while the probe is still running
and the directory does not yet exist, append that observation to a temporary
monitor file and move it verbatim into the run directory immediately after the
runner creates it.

Each line must contain the actual observation timestamp, elapsed seconds, child
liveness, latest frame type/time, `llm.request` count, `llm.response` count,
latest finish reason/incomplete flag, tool-call/result counts, workspace file
count/bytes/newest-write time, console tail actually inspected, approximate
input-token total, and operator action (`continue`, `cancel`, or `process
already exited`). Do not reconstruct or batch-generate this file after the run.
Consecutive live observations should normally be 25–45 seconds apart.

At every observation, specifically check:

1. Is `llm.response` emitted for every completed request?
2. If finish reason is `length`, `max_tokens`, or another output limit, did
   Pulse emit paired tool errors with **no mutation from that response**?
3. Did the paired rejection reach the next `llm.request`?
4. After any successful tool result, did request 2 begin without semantic-memory
   initialization or pending-stream warnings?
5. Are provider requests, input tokens, files, and bytes advancing safely?
6. Is the same incomplete/rejected call repeating without progress?

Cancel immediately and permanently if any of these occurs:

- a credential appears in output/evidence;
- a mutation escapes `C:\test5-ws-attempt9`;
- three requests occur with no delivered file;
- request/input-token cap is reached;
- the same rejected incomplete write repeats three times;
- stream-close/pending-generator warnings recur and no next request appears;
- no meaningful run/workspace/CPU activity reaches 300 seconds;
- evidence paths or preserved workspaces are modified;
- any behavior threatens remaining credits.

## 6. Runtime verdict

After the process exits, classify runtime independently. `RUNTIME_PASS`
requires all of the following:

- runner-owned `outcome.json` exists;
- terminal frame is `turn_done` with `completed=true`;
- no budget, no-delivery, operator-cancel, timeout, or watchdog stop;
- every provider request has a bounded response receipt;
- no incomplete-response tool call executed;
- if an incomplete call occurred, its paired rejection reached the immediate
  next provider request;
- successful tool results continued directly to the next provider decision;
- no pending async-generator/request-stream warning;
- all tool effects remain inside the fresh workspace.

Anything else is `RUNTIME_FAIL`. Preserve first-failure evidence; do not explain
it away and do not retry.

## 7. Independent product grading — no provider calls

Regardless of runtime verdict, copy the complete delivered workspace into:

```text
bench-results\test5-9-desktop\workspace-delivery\
```

Then grade the immutable delivered copy without editing it.

At minimum:

1. Inventory every file, byte length, and SHA-256.
2. Prove HTML/CSS/JS and shader sources are not truncated and have balanced
   structural endings/imports.
3. Confirm local Three.js/OrbitControls dependencies exist; no remote runtime
   dependency may substitute for required local files.
4. Start a basic local static server from the delivered copy.
5. Open the deterministic screenshot URL in a real browser.
6. Capture viewport screenshots and browser console/network logs.
7. Confirm no black/blank screen, unhandled console error, failed local asset,
   or shader compile/link error.
8. Exercise presets, representative live parameters, debug views 0–9,
   responsive/Retina behavior, persistence, and WebGL recovery where practical.
9. Inspect code and runtime evidence for the requested geodesic integration,
   event horizon, photon ring, multi-crossing disk, procedural starfield/Milky
   Way, Doppler/redshift/turbulence, bloom/ACES/vignette/grain/aberration,
   camera paths, telemetry, 21 parameters, three quality profiles, URL-driven
   deterministic mode, startup instructions, and optional audio behavior.

`PRODUCT_PASS` requires a complete executable product with the requested core
features and no critical runtime defect. A pretty screenshot alone is not a
pass. A static-code claim without successful browser execution is not a pass.
Record each acceptance item as PASS/FAIL/NOT_PROVEN with concrete evidence.

Stop the local server/browser after grading. Product grading must make zero
provider calls.

## 8. Evidence requirements

Commit all Attempt-9 evidence, including:

- preflight and freshness receipts;
- exact run command with secret redacted;
- complete foreground transcript/console log;
- `frames.jsonl`, `bridge_stderr.log`, and `outcome.json`;
- genuine `monitor-30s.jsonl` observations;
- request/response counts and finish metadata;
- safety, cancellation, budget, and watchdog receipts;
- the complete delivered workspace copy;
- file inventory and SHA-256 manifest;
- static analysis and browser server logs;
- console/network logs and screenshots;
- runtime and product grading JSON/Markdown;
- preserved-evidence before/after comparison;
- final evidence manifest with byte lengths/SHA-256;
- final `git status --short` and `git diff --check` result.

Mark the evidence path `-text` through the existing `bench-results/** -text`
attribute; do not normalize or rewrite raw logs after collection. Never commit
`.env`, credentials, dependency caches, browser profiles, or unrelated build
output.

## 9. Commit, push, and stop

After grading, confirm only `bench-results/test5-9-desktop/` is new/modified.
Commit and push all evidence even on failure:

```text
git add bench-results/test5-9-desktop/
git commit -m "evidence: record Test 5 Attempt 9"
git push origin HEAD:arena/01a03741-pulseairepo
```

Report:

- full evidence commit;
- provider request count split into the one probe plus bridge-turn requests,
  and approximate token usage;
- runtime verdict;
- product verdict;
- first failure boundary, if any;
- whether credits/caps/watchdogs fired.

Then STOP. Do not merge PR #9 or delete any branch. Arena must independently
verify the evidence before the founder makes a separate merge decision.

## 10. Preserve exactly

```text
C:\test5-ws-attempt6
C:\test5-ws-attempt8
C:\test5-ws-attempt9
bench-results\test5-5\
bench-results\test5-6\
bench-results\test5-8-desktop\
bench-results\test5-8-postmortem-validation\
bench-results\test5-stream-parity-validation\
bench-results\test5-stream-parity-validation-followup\
bench-results\test5-9-desktop\
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
```

`C:\test5-ws-attempt5` remains absent and must not be recreated.
