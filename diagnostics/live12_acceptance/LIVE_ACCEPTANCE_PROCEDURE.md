# LIVE12 Acceptance Procedure (prepared, not executed)

**Do not run this until a separate written authorization names the spending
ceiling.** This document is a procedure only.

---

## 1. Preconditions

- Starting HEAD: `128fbc56fdf6dc16d98880c0d883087e30d8c22f` (or a verified
  descendant containing the Live11 repair).
- Branch: `feat/prompt-cache-stabilization`.
- Working tree: unrelated changes understood and not staged.
- Exact prompt:
  `diagnostics/generation_boundary/live_acceptance/live11_20261108/prompt.txt`
  SHA-256 `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8`.
- Fresh Electron session; no leftover CrusorAI processes.
- Authorized ceiling: **₹1.20** (₹1.00 task + ₹0.20 auxiliary) unless the
  authorizer specifies otherwise.
- Title policy: **`CRUSORAI_AUTOTITLE=off` recommended** (removes the known
  `_engine_build` terminal delay). If title is enabled, accept the documented
  delay risk and use the full ₹1.20 ceiling.

---

## 2. Environment

```powershell
$env:CRUSORAI_TASK_BUDGET_INR       = "1.00"
$env:CRUSORAI_AUX_BUDGET_INR        = "0.20"
$env:CRUSORAI_AUX_TOKEN_BUDGET      = "4000"
$env:CRUSORAI_AUX_MAX_TOKENS         = "64"
$env:CRUSORAI_MAX_GENERATION_RECOVERIES = "1"
$env:CRUSORAI_SUBMISSION_REPLAY_WINDOW_S = "600"
$env:CRUSORAI_NEW_SESSION_REPLAY_WINDOW_S = "60"
$env:CRUSORAI_AUTOTITLE             = "off"   # recommended; see title audit
$env:CRUSORAI_MEMORY                = "off"
$env:CRUSORAI_BRIDGE_DIAGNOSTICS     = "1"
```

The harness sets:

```text
CRUSORAI_ACCEPTANCE_RUN_ID
CRUSORAI_ACCEPTANCE_MAX_DISPATCHES=5
CRUSORAI_ACCEPTANCE_EVIDENCE_PATH
CRUSORAI_TURN_COST_BUDGET_INR=1.20
CRUSORAI_SESSION_COST_BUDGET_INR=1.20
CRUSORAI_RESERVE_BUDGET_INR=0.50
```

---

## 3. One-session command

```powershell
.\.venv\Scripts\python.exe -m benchmarks.crusor_desktop_acceptance `
  --live-turn `
  --prompt-file "diagnostics\generation_boundary\live_acceptance\live11_20261108\prompt.txt" `
  --evidence-dir "diagnostics\live12_acceptance\live12_run_<runid>" `
  --budget-inr 1.20 `
  --max-dispatches 5 `
  --turn-timeout 900
```

Exactly one Electron session and one harness `Enter`. No `--stop-before-submit`
session first; the one authorized session submits.

---

## 4. Observation checklist

Before submission:

- renderer workbench belongs to CrusorAI;
- composer enabled and engine ready;
- prompt typed SHA matches the exact value above;
- acceptance guard in-app reports max 5, attempts 1, used 0.

At submission:

- `ui_submission.method` is `enter` (or one explicit send click);
- composer clears;
- exactly **one** turn manifest appears;
- the bridge submission ledger has exactly one record for the new
  `submission_id`;
- no second `session_create` / `session_info` minted a new session.

During/after:

- source, tests, and optional title calls each have a unique reservation,
  invocation id, usage receipt, cost and settlement;
- `TASK_DELIVERED` reaches a truthful verdict;
- pytest and independent smoke results are recorded;
- `IMPLEMENTATION_DONE` / `CROSS_FILE_VALIDATED` are present.

After app stop:

- guard claims == physical invocation records;
- reservations: 0 active, 0 uncertain (or a truthful uncertain with a durable
  reason; cannot pass as balanced);
- no duplicate settlement;
- no hidden invocation;
- total settled spend ≤ authorized ceiling;
- submission ledger: one submission, terminal state, no second turn.

---

## 5. Immediate failure conditions

Any one of these fails LIVE12:

- a second session or turn appears;
- a second `session_create` mints a new session;
- a completed/pending submission is replayed into a new turn;
- an active reservation remains after terminal reconciliation;
- a dispatched call is released as free;
- usage or cost is missing/fabricated;
- total spend exceeds the authorized ceiling;
- the task reports completion with missing artifacts, failed tests, or failed
  smoke;
- the harness records a second submission gesture.

A normal complete generation must **not** be presented as generation recovery.
Recovery is proven only by a genuine truncated response followed by a genuine,
separately reserved/settled recovery invocation and a complete artifact.

---

## 6. Evidence

Write under:

```text
diagnostics/live12_acceptance/live12_run_<runid>/
```

Preserve prompt, SHA, screenshots, manifests, journals, provider ledger, FinOps
reservations/settlements, submission ledger, generated artifacts, test reports,
smoke output, acceptance matrix, and SHA256SUMS. Do not modify Live9/Live10/Live11
evidence.

---

## 7. Verdicts after the run

- **`LIVE12_DUPLICATE_AND_FINANCIAL_LIVE_PASSED`** only if exactly one
  submission/session/turn occurred, all financial invariants pass, and the task
  verification passes.
- **`LIVE12_NORMAL_PATH_ONLY`** if the run is clean but generation completed
  normally (no recovery).
- **`LIVE12_LIVE_RECOVERY_PROVEN`** only if a genuine truncation and genuine
  recovery occurred, separately accounted, and the task passed.
- **`LIVE12_LIVE_ACCEPTANCE_FAILED`** for any mandatory failure above.

P0.6.9 remains `P0.6.9_ACCEPTANCE_FAILED` regardless.
