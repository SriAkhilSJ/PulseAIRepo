# PR 1B commit guide - Pulse Reliability Benchmark v1 evaluator core

**What this is:** engine-side (Lane B) work. Apply + push only; no editorial edits.
Do **not** modify `contract.py` / `manifest.json` (merged in PR 1A) or anything
under `desktop/`.

**Patch:** `PR1B_evaluator.patch` - exactly 2 new files, applies to repo root at `main`.
Verified: apply check OK; 70/70 tests pass after applying PR 1B + PR 1C in sequence.

## Files this PR adds

| Path | Change |
|---|---|
| `benchmarks/pulse_reliability_v1/evaluator.py` | NEW - deterministic evaluator core: `RunRecord` schema, 8 check-type handlers, hard-failure detection (workspace escape, secret disclosure, unapproved network, orphaned processes, false success claims, checkpoint/tamper flags), new/pre-existing/environmental failure classification vs an optional baseline run, outcome decision, `BenchmarkResult` + Markdown report, explicit CLI |
| `src/tests/test_benchmark_evaluator.py` | NEW - 35 deterministic tests (synthetic in-memory records only; no network/process/fixtures) |

The suite README is updated in PR 1C (which includes fixtures) so the two
patches stay conflict-free regardless of merge order.

## Steps (repo checkout, freshly fetched `main`)

```powershell
# 1. Start clean
git fetch origin
git checkout main
git status                              # no unrelated changes; do not touch README.md / pulseAI.css
git switch -c benchmark/reliability-v1-evaluator

# 2. Apply the patch (copy PR1B_evaluator.patch into repo root first)
git apply --check --verbose PR1B_evaluator.patch
git apply PR1B_evaluator.patch

# 3. Test run BEFORE staging (repo venv)
D:\pulseAIRepo\.venv\Scripts\python.exe -m pytest src/tests/test_benchmark_contract.py src/tests/test_benchmark_evaluator.py -q
# expect: 48 passed in <1s

# 4. Stage ONLY the two new paths (never git add -A)
git add -- benchmarks/pulse_reliability_v1/evaluator.py src/tests/test_benchmark_evaluator.py

# 5. Prove the stage is exactly the two paths
git status --short                  # 2x A, nothing else
git diff --cached --stat            # 2 files; no __pycache__, no .pyc, no .pytest_cache

# 6. Commit + push
git commit -m "feat(quality): add deterministic benchmark evaluator"
git push -u origin benchmark/reliability-v1-evaluator
```

## PR body (paste as-is)

```markdown
# Pulse Reliability Benchmark v1 - evaluator core (PR 1B)

Deterministic, evaluator-owned grading for the v1 suite. PR 1A (contract +
manifest) is merged; this PR adds the engine that grades runs. No desktop
execution, no model calls, no fixtures, no committed results.

- `benchmarks/pulse_reliability_v1/evaluator.py`
  - `RunRecord` schema (harness output; validated, never committed).
  - Handlers for all eight check types declared in the manifest
    (command, changed-files, dom, event, process, protocol, context-ranking,
    workspace-hash).
  - Hard-failure detection: workspace escape, secret disclosure, unapproved
    network (deny / localhost-only / allowlist), orphaned processes,
    duplicate mutation, concurrent-edit overwrite, checkpoint failure,
    evaluator tampering, false success claims.
  - Failure classification with an optional baseline run: new vs
    pre-existing vs environmental.
  - Outcome decision (passed / failed_functional / failed_verification /
    failed_safety / failed_harness / environment_unavailable), normalized
    `BenchmarkResult` JSON, Markdown report, explicit CLI.
- `src/tests/test_benchmark_evaluator.py` - 35 deterministic tests on
  synthetic in-memory records; no network, no processes, no fixtures.

Evidence: 48/48 tests pass (13 contract + 35 evaluator) in ~0.2s.
CLI smoke: synthetic PBR-001 run - outcome `passed`, JSON + Markdown written.

Design rules preserved: evaluator-owned checks only; bounded everything;
classification not a bare boolean; results never enter Git.
```

## Hard rules (unchanged)

- Never `git add -A` / `git add .` / `git reset --hard` / `git clean`.
- Never touch repo-root `README.md` / `pulseAI.css` / anything under `desktop/`.
- No generated outputs in Git (no `__pycache__`, `.pyc`, `.pytest_cache`,
  screenshots, logs, run records).
