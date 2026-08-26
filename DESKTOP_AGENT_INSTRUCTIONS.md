# Desktop Agent Instructions — One-Shot Windows Revalidation R3

**Updated:** 2026-08-26

**Required branch:** `arena/01a03741-pulseairepo`

**Repair under validation:** `0370515cce811dd4d86d14379dd2729a94e640b1`

**Prior failed evidence:** `b90cb579eb72b363491f53e2a014fd073e795552`

**Open PR:** #9 — do not merge

## Authorized task

R2 correctly stopped at `fixture_detection`: the runner did not add the
repository root to `sys.path`. R3 fixes that runner-only defect.

Run exactly one provider-free Windows validation using the checked-in fail-fast
script. The script performs the 183 focused tests, three fixture findings, seven
protocol tests, protocol generation, compilation, diff check, heartbeat,
summary, and hashes. It never retries and never overwrites evidence.

No provider probe/request, live Pulse turn, dependency installation, source or
test edit, cap increase, full suite, PR merge, branch deletion, or Agentic UI
work is authorized.

## Required checkout

Use only:

```text
D:\pulseAIagent\PulseAIRepo
```

Do not use another clone, an old checkout, an Arena path, or any generated
workspace. Do not modify historical Attempt-5 through Attempt-11 evidence or
`C:\test5-ws-attempt11`.

## Execute

From the existing checkout:

```powershell
$ErrorActionPreference = 'Stop'
cd D:\pulseAIagent\PulseAIRepo

if ((git branch --show-current) -ne 'arena/01a03741-pulseairepo') {
  throw 'Wrong branch — STOP'
}
if (git status --porcelain=v1) {
  throw 'Checkout is not clean — preserve it and STOP; do not reset or clean'
}

git fetch origin arena/01a03741-pulseairepo
git pull --ff-only origin arena/01a03741-pulseairepo
if ($LASTEXITCODE -ne 0) { throw 'Fast-forward failed — STOP' }

$python = if (Test-Path '.venv\Scripts\python.exe') {
  (Resolve-Path '.venv\Scripts\python.exe').Path
} else {
  'python'
}

& $python scripts\validate_attempt11_product_delivery_windows.py
$validationExit = $LASTEXITCODE
```

Do not rerun the script for any reason. It creates:

```text
bench-results\test5-11-product-delivery-repair-validation-windows-r3\
```

If the command exits nonzero, preserve its `DETERMINISTIC_FAIL` evidence. Do not
repair, retry, overwrite, or substitute another command.

## Commit evidence only

```powershell
git status --short
```

Only the new R3 evidence directory may be untracked. If anything else changed,
preserve it and STOP without reset/clean.

```powershell
git add -f bench-results/test5-11-product-delivery-repair-validation-windows-r3
git commit -m "test: revalidate Attempt 11 delivery repair on Windows"
git push origin arena/01a03741-pulseairepo
```

Commit and push the evidence even when `$validationExit` is nonzero.

## Final report

Report:

1. repository, branch, validation head, and repair commit;
2. `DETERMINISTIC_PASS` or `DETERMINISTIC_FAIL` and exact counts;
3. fixture findings;
4. `first_failed_boundary` exactly as recorded;
5. provider probes/requests (both zero);
6. evidence directory and commit; and
7. `STOPPED — no live attempt authorized`.

Then stop. Do not run Attempt 12 or any provider-backed command.
