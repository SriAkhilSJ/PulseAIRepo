# Desktop Agent Instructions — authorized OpenRouter Test 5 Attempt 10

**Updated:** 2026-08-25

**Branch:** `arena/01a03741-pulseairepo`

**Stream-parity implementation:** `b82381d36662e2f0dc9262bafafbedd8508318d6`

**Provider-agnostic probe repair:** `72dd56d910dd6b5707d17fca632b48ac5c44a23f`

**Prior Attempt-9 STOP evidence:** `47c02f9b0bfacf3b502e2191a200834e77127a2c`

> The founder explicitly authorized exactly one OpenRouter-backed Test 5 run
> using the OpenRouter key and exact model identifier already provided to the
> desktop agent under its secret-handling rules. Authorization includes one
> eight-token OpenRouter probe and one guarded turn. It does not authorize a
> second probe, retry, model substitution, cap increase, PR merge, branch
> deletion, source repair during the run, or Agentic UI work.

## 1. Fixed run identity

Use only the existing repository:

```text
D:\pulseAIagent\PulseAIRepo
```

Use exactly:

```text
Run ID:     test5-10-desktop
Workspace:  C:\test5-ws-attempt10
Evidence:   bench-results\test5-10-desktop\
Prompt:     scripts\test5_prompt.txt
Provider:   OpenRouter through Pulse's custom OpenAI-compatible provider
Base URL:   https://openrouter.ai/api/v1
Model:      exact OpenRouter model ID previously supplied to the desktop agent
```

The model ID is not a secret and must be recorded in preflight and final
receipts. Do not guess, use the repository default, or substitute another model.
If the desktop agent cannot unambiguously identify the previously supplied
model ID and secure key location, record `PRECONDITION_STOP` with zero provider
requests and stop. Never ask for or print the key.

Attempt 9's workspace/evidence are immutable failed-preflight evidence. Do not
reuse or modify them.

## 2. Preconditions — STOP before provider traffic if any fail

1. Confirm the checkout is clean and on `arena/01a03741-pulseairepo`.
2. Fetch and fast-forward to `origin/arena/01a03741-pulseairepo`. Never detach
   HEAD, reset, force-push, switch/create a branch, or create another clone.
3. Record the full run-parent commit and prove:

   ```text
   git rev-parse HEAD == git rev-parse origin/arena/01a03741-pulseairepo
   git merge-base --is-ancestor b82381d36662e2f0dc9262bafafbedd8508318d6 HEAD
   git merge-base --is-ancestor 72dd56d910dd6b5707d17fca632b48ac5c44a23f HEAD
   git merge-base --is-ancestor 47c02f9b0bfacf3b502e2191a200834e77127a2c HEAD
   ```

4. Confirm both are absent; never delete/reuse either:

   ```text
   C:\test5-ws-attempt10
   bench-results\test5-10-desktop
   ```

5. Confirm `scripts/test5_prompt.txt` is tracked and unchanged.
6. Parse `scripts/run_test5_guarded.ps1` with the PowerShell parser without
   executing it.
7. Run exactly this zero-provider preflight test once and capture output:

   ```text
   python -m pytest -q src/tests/test_test5_guarded_script.py
   ```

   It must collect and pass 4 tests, including the configured custom-provider
   probe contract. Failure is a pre-provider STOP; do not repair on desktop.
8. Record source commit, branch/status, Python/PowerShell/pytest versions,
   prompt/wrapper SHA-256, literal non-secret OpenRouter model ID, base URL,
   freshness, parser, and test results in a temporary receipt. Move it into the
   run directory after the runner creates that directory.
9. Record byte length/SHA-256 manifests for preserved Test-5 evidence before
   the run so after-run immutability can be proven.

If any precondition fails, create and commit a fresh Attempt-10
`PRECONDITION_STOP` receipt, push it, and stop with zero provider requests.

## 3. OpenRouter secret/configuration rules

Use only the OpenRouter key already available to the desktop agent in its
approved secure location. Do not use the expired Sarvam credential or recover a
key from README/Git history.

Configure the gitignored `.env` without exposing the key:

```text
LLM_PROVIDER=custom
LLM_MODEL=<exact previously supplied OpenRouter model ID>
CONTEXT_MODEL=<same exact model ID>
CUSTOM_BASE_URL=https://openrouter.ai/api/v1
CUSTOM_API_KEY=<secure OpenRouter key>
```

- Map the secure key into `CUSTOM_API_KEY` without printing, echoing,
  screenshotting, hashing, logging, or placing it in a command argument/history.
- Confirm `.env` is ignored and absent from `git status`.
- Record only key presence (`true`), never value/length/prefix/hash.
- Do not configure provider fallback or a second model.
- The wrapper's probe and live Pulse turn must read the same base URL/model/key.

## 4. One probe and one guarded turn

Run exactly one foreground invocation:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_test5_guarded.ps1 `
  -Workspace C:\test5-ws-attempt10 `
  -RunId test5-10-desktop `
  -MaxMinutes 45 `
  -StallSeconds 300 `
  -MaxLlmCalls 16 `
  -MaxInputTokens 120000 `
  -MaxNoDeliveryCalls 3
```

The wrapper performs the only authorized eight-token OpenRouter probe.

- Probe failure: live turn must not start; no second probe.
- Probe response must identify the exact configured model in non-secret output.
- Do not rerun the wrapper or raise caps.
- Three bridge requests without a file must cancel the turn.
- Request/input-token, 300-second stall, and 45-minute hard caps remain active.
- Any cancellation/watchdog kill is final.

Use a foreground live console. Do not redirect the bridge child through the
PowerShell 5.1 deadlock-prone path. A temporary PowerShell transcript is allowed
if output remains visible live and is copied to evidence afterward.

## 5. Active monitoring every 30 seconds

The desktop agent must actually inspect the console, frames, outcome, and
workspace at least once every 30 seconds from wrapper start through exit. The
wrapper watchdog is not proof of human/agent inspection.

Append each observation immediately to:

```text
bench-results\test5-10-desktop\monitor-30s.jsonl
```

Do not pre-create the run directory. If the first interval occurs during the
probe, append to a temporary monitor file and move it verbatim after the runner
creates the evidence directory.

Each line must record timestamp, elapsed seconds, liveness, latest frame/time,
`llm.request` and `llm.response` counts, finish reason/incomplete flag,
tool-call/result counts, workspace file count/bytes/newest write, inspected
console tail, approximate tokens, and operator action. Do not reconstruct or
batch-generate observations after the run. Live intervals should normally be
25–45 seconds apart.

At every observation verify:

1. each completed request receives `llm.response` metadata;
2. output-limit responses execute no tool and produce paired tool errors;
3. any paired rejection reaches the immediate next request;
4. successful tools continue directly without semantic-memory/stream stalls;
5. requests, tokens, files, and bytes progress within caps;
6. incomplete/rejected calls are not repeating without progress.

Cancel permanently on credential leakage, workspace escape, 3 no-file
requests, a credit cap, three repeated rejected writes, pending-stream warnings
without continuation, 300 seconds without meaningful activity, preserved
artifact mutation, or any threat to remaining OpenRouter credits.

## 6. Verdicts and product grading

`RUNTIME_PASS` requires runner-owned `outcome.json`, terminal `turn_done` with
`completed=true`, no breaker/cancel/watchdog, one response receipt per completed
request, no execution from an incomplete response, correct direct continuation,
no pending-stream warning, and all effects contained by the fresh workspace.
Anything else is `RUNTIME_FAIL`; do not retry.

Regardless of runtime outcome, copy the complete workspace to:

```text
bench-results\test5-10-desktop\workspace-delivery\
```

Grade that immutable copy with zero provider calls:

- inventory byte lengths/SHA-256 and detect truncation;
- verify local Three.js/OrbitControls and no forbidden remote dependency;
- serve it from a basic local static server;
- open its deterministic screenshot URL in a real browser;
- capture screenshots plus console/network/shader errors;
- reject black/blank output, failed assets, unhandled errors, or shader failure;
- exercise presets, representative parameters, debug 0–9, responsive/Retina,
  persistence, and WebGL recovery where practical;
- grade every requested rendering/control/quality/startup requirement as
  PASS/FAIL/NOT_PROVEN with concrete evidence.

`PRODUCT_PASS` requires a complete executable product with requested core
features and no critical runtime defect. A screenshot alone or static claim is
not sufficient.

## 7. Evidence, commit, and STOP

Commit all Attempt-10 evidence even on failure:

- preflight/freshness and exact non-secret provider/model configuration;
- exact command with key redacted;
- console transcript, frames, stderr, outcome, and genuine monitor log;
- probe count/status and bridge request/token counts separately;
- response finish metadata and tool lifecycle;
- complete delivered workspace;
- file hashes, static/browser logs, screenshots, and acceptance matrix;
- runtime/product verdict and first failure boundary;
- preserved-evidence before/after proof;
- receipt manifest with byte lengths/SHA-256;
- final status and diff check.

Confirm only `bench-results/test5-10-desktop/` is new/modified, then:

```text
git add bench-results/test5-10-desktop/
git commit -m "evidence: record OpenRouter Test 5 Attempt 10"
git push origin HEAD:arena/01a03741-pulseairepo
```

Report the evidence commit, exact model ID, one probe status, bridge request and
approximate token counts, runtime/product verdicts, first failure boundary, and
whether any cap fired. Then STOP. Do not merge PR #9 or delete branches; Arena
must independently grade the evidence first.

## 8. Preserve exactly

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

`C:\test5-ws-attempt5` remains absent and must not be recreated.
