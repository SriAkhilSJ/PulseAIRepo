# LIVE12 Acceptance Procedure (prepared, not executed)

**Do not run until a separate written authorization names the ceiling.**

## 1. Preconditions

- HEAD is the final readiness commit; artifact `BUILD_MANIFEST.json` matches it.
- Exact prompt:
  `diagnostics/generation_boundary/live_acceptance/live11_20261108/prompt.txt`
  SHA-256 `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8`.
- Fresh workspace and fresh Electron session; no stale CrusorAI processes.
- Authorized ceiling: **₹1.00** with `CRUSORAI_AUTOTITLE=off`; **₹1.20** if
  title is enabled.

## 2. Environment

```powershell
$env:CRUSORAI_TASK_BUDGET_INR              = "1.00"
$env:CRUSORAI_AUX_BUDGET_INR               = "0.20"
$env:CRUSORAI_AUX_TOKEN_BUDGET             = "4000"
$env:CRUSORAI_AUX_MAX_TOKENS                = "64"
$env:CRUSORAI_MAX_GENERATION_RECOVERIES     = "1"
$env:CRUSORAI_SUBMISSION_REPLAY_WINDOW_S    = "600"
$env:CRUSORAI_NEW_SESSION_REPLAY_WINDOW_S   = "60"
$env:CRUSORAI_AUTOTITLE                     = "off"
$env:CRUSORAI_MEMORY                        = "off"
$env:CRUSORAI_BRIDGE_DIAGNOSTICS             = "1"
```

The harness sets `CRUSORAI_ACCEPTANCE_*`, turn/session budget, and reserve.

## 3. Command (one session, one submission)

```powershell
.\.venv\Scripts\python.exe -m benchmarks.crusor_desktop_acceptance `
  --live-turn `
  --prompt-file "diagnostics\generation_boundary\live_acceptance\live11_20261108\prompt.txt" `
  --evidence-dir "diagnostics\live12_final_readiness\live12_run_<runid>" `
  --budget-inr 1.00 `
  --max-dispatches 5 `
  --turn-timeout 900
```

No `--stop-before-submit` session first. One Enter only.

## 4. Immediate abort conditions

- second session or turn;
- second submission gesture / duplicate `session_create`;
- replay of a completed/pending submission;
- active or silently unresolved reservation at terminal reconciliation;
- dispatched call released as free;
- missing/fabricated usage;
- spend above the authorized ceiling;
- failed artifacts/tests/smoke;
- any hidden provider invocation.

The harness must independently confirm one logical submission. A second
session/turn is immediate failure.

## 5. Reconciliation

Check:

- guard claims == physical invocations;
- each invocation has one reservation/invocation id/usage/cost/settlement;
- no duplicate settlement;
- no active/uncertain reservation in the new workspace;
- auxiliary title count is 0 with autotitle off;
- task aggregate equals ledger sum;
- artifacts/tests/smoke.

## 6. Verdicts

- `LIVE12_DUPLICATE_AND_FINANCIAL_LIVE_PASSED` — one submission/session/turn,
  all financial invariants, task verification passed.
- `LIVE12_NORMAL_PATH_ONLY` — clean run, normal generation (no recovery).
- `LIVE12_LIVE_RECOVERY_PROVEN` — genuine truncation + genuine recovery, all
  accounted, task passed.
- `LIVE12_LIVE_ACCEPTANCE_FAILED` — any mandatory failure.

P0.6.9 remains failed. No live acceptance is claimed by this preflight.
