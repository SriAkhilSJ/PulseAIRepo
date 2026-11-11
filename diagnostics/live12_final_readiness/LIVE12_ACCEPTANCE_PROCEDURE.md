# LIVE12 Acceptance Procedure (prepared, not executed)

**Do not run until a separate written authorization names the ceiling.**

Current status: preparation only. No Electron session, submission, reservation
or provider call has been made.

## 1. Preconditions

- HEAD is the final readiness commit; `BUILD_MANIFEST.json` records the exact
  desktop source commit (`7d4a4cc5`) and it is an ancestor of HEAD.
- Exact prompt (the only copy that exists):

  ```text
  diagnostics/generation_boundary/live_acceptance/live11_20261108/prompt.txt
  ```

  SHA-256 `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8`
  (876 bytes).

  The path `diagnostics/live11_20261108/prompt.txt` named in the authorization
  text does not exist. The verified file above is used instead; the bytes are
  not modified.

- Fresh workspace, fresh `CRUSORAI_HOME`, fresh Electron session; no stale
  CrusorAI process.
- Authorized ceiling: **₹1.00 total**; auxiliary expected **₹0.00** because
  titling is disabled. A titling-enabled run is **not** authorized.

## 2. Environment

```powershell
$env:CRUSORAI_TASK_BUDGET_INR            = "1.00"
$env:CRUSORAI_AUX_BUDGET_INR             = "0.00"
$env:CRUSORAI_AUX_TOKEN_BUDGET           = "0"
$env:CRUSORAI_AUX_MAX_TOKENS             = "64"
$env:CRUSORAI_MAX_GENERATION_RECOVERIES  = "1"
$env:CRUSORAI_SUBMISSION_REPLAY_WINDOW_S = "600"
$env:CRUSORAI_NEW_SESSION_REPLAY_WINDOW_S= "60"
$env:CRUSORAI_AUTOTITLE                  = "off"
$env:CRUSORAI_MEMORY                     = "off"
$env:CRUSORAI_BRIDGE_DIAGNOSTICS         = "1"
```

The harness sets `CRUSORAI_ACCEPTANCE_*`, turn/session budget, and reserve. It
does **not** add `CRUSORAI_AUTOTITLE`, so the exported `off` survives into the
Electron child, worker and Python bridge (dotenv uses `override=False`).

## 3. Command (one session, one submission)

```powershell
.\.venv\Scripts\python.exe -m benchmarks.crusor_desktop_acceptance `
  --live-turn `
  --prompt-file "diagnostics\generation_boundary\live_acceptance\live11_20261108\prompt.txt" `
  --evidence-dir "diagnostics\live12_run_<unique_run_id>" `
  --budget-inr 1.00 `
  --max-dispatches 5 `
  --turn-timeout 900
```

No `--stop-before-submit` session first. Exactly one Enter.

## 4. Immediate abort conditions

- second session or turn;
- second submission gesture / duplicate `session_create`;
- replay of a completed/pending submission;
- active or silently unresolved reservation at terminal reconciliation;
- dispatched call released as free;
- missing/fabricated usage;
- spend above ₹1.00;
- task beyond 900 s;
- failed artifacts/tests/smoke;
- any hidden provider invocation;
- any `session_titling` invocation while autotitle is off;
- the historical reservation `res_d7990e4d3dc3` entering scope.

The harness must independently confirm one logical submission. A second
session/turn is immediate failure.

## 5. Reconciliation

Check:

- guard claims == physical invocations;
- each invocation has one reservation/invocation id/usage/cost/settlement;
- no duplicate settlement;
- no active/uncertain reservation in the new workspace;
- **zero** `session_titling` records and zero auxiliary spend;
- task aggregate equals ledger sum;
- artifacts/tests/smoke.

## 6. Harness gates and verdict mapping

The acceptance harness is `benchmarks/crusor_desktop_acceptance/live_acceptance.py`.
It emits its historical verdict strings, and the acceptance report maps them:

| Harness verdict | LIVE12 verdict |
|---|---|
| `P0.6.9_ACCEPTANCE_PASSED` | `LIVE12_ACCEPTANCE_PASSED` |
| `P0.6.9_ACCEPTANCE_FAILED` | `LIVE12_ACCEPTANCE_FAILED` |
| `P0.6.9_ACCEPTANCE_BLOCKED` | `LIVE12_ACCEPTANCE_FAILED` |
| missing/unreconciled evidence | `LIVE12_INCONCLUSIVE` |

Titling-off classification is stricter than "skip the title gate":

- `autotitle.disabled = true` is captured at finalisation;
- the run passes only when there are **zero** `session_titling` records;
- any title invocation fails the run as an unauthorized auxiliary dispatch;
- the empty session title is expected and is not a failure;
- the 90 s auxiliary accounting wait is short-circuited.

Titling-enabled runs keep the original requirement: at least one settled title
invocation with positive cost, model and provider, and a non-empty session
title.

## 7. Evidence

The run writes its full package under `diagnostics/live12_run_<run_id>/`.
Raw logs, provider records and test output are preserved; no evidence is
replaced by a summary. `abort_or_completion_report.md` carries the final
LIVE12 verdict and its mapping to the harness verdict.

Mid-turn visual samples (panel DOM counts + screenshots) are recorded in
`evidence.json` under `visual` and `screenshots/turn-*.png`. They are how the
run answers whether tool-call cards actually rendered; see
`VISUAL_EVIDENCE.md`.

P0.6.9 remains `P0.6.9_ACCEPTANCE_FAILED`. No live acceptance is claimed by this
document.
