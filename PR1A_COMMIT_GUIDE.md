# PR 1A commit guide — Pulse Reliability Benchmark v1 contract

**What this is:** engine-side (Lane B) contract work. The desktop agent only codes
desktop contribution files + CDP tests — it must **not** author or modify these
files. If it acts as a pure git courier (apply + push only, zero editorial edits),
that is acceptable, but the repository owner is the one who verifies.

**Patch:** `PR1A_benchmark_contract.patch` — 6 new files only, applies to repo root
at `main`. Verified: applies clean on a fresh tree; `13 passed` contract tests;
no generated files inside the patch.

## Files added by this PR

| Path | Purpose |
|---|---|
| `benchmarks/__init__.py` | Empty package marker |
| `benchmarks/pulse_reliability_v1/__init__.py` | Empty package marker |
| `benchmarks/pulse_reliability_v1/contract.py` | Pydantic v2 strict models (manifest + result), import-safe |
| `benchmarks/pulse_reliability_v1/manifest.json` | 12 tasks `PBR-001`…`PBR-012`, ordered, validated |
| `benchmarks/pulse_reliability_v1/README.md` | Suite documentation, task inventory, design rules |
| `src/tests/test_benchmark_contract.py` | 13 deterministic contract tests (no network/model/fixtures) |

Note: directory uses underscores (`pulse_reliability_v1`) because hyphenated
directories are not Python-importable; the public suite id keeps hyphens
(`pulse-reliability-v1`).

## Steps (in the repo checkout, on freshly fetched `main`)

```powershell
# 1. Start clean
git fetch origin
git checkout main
git status                 # must show no unrelated changes; do not touch README.md / pulseAI.css
git create branch benchmark/reliability-v1-contract   # (use: git switch -c benchmark/reliability-v1-contract)

# 2. Apply the patch (copy PR1A_benchmark_contract.patch into the repo root first)
git apply --check --verbose PR1A_benchmark_contract.patch
git apply PR1A_benchmark_contract.patch

# 3. Contract test run BEFORE staging (repo python: D:\pulseAIRepo\.venv\Scripts\python.exe)
python -m pytest src/tests/test_benchmark_contract.py -q
# expect: 13 passed in ~0.1s

# 4. Stage ONLY the six new paths (never git add -A)
git add -- benchmarks src/tests/test_benchmark_contract.py

# 5. Prove the stage is exactly the six files
git status --short              # 6× A (added), nothing else
git diff --cached --stat        # 6 files; NO __pycache__, NO .pyc, NO .pytest_cache

# 6. Commit
git commit -m "docs(quality): define Pulse Reliability Benchmark v1"

# 7. Push + PR
git push -u origin benchmark/reliability-v1-contract
```

## PR body (paste as-is)

```markdown
# Pulse Reliability Benchmark v1 — contract (PR 1A)

Contract-only PR: no evaluator (PR 1B), no fixtures (PR 1C), no model calls,
no network, no process spawning, no desktop execution, no committed results.

- `benchmarks/pulse_reliability_v1/contract.py` — strict Pydantic v2 models
  (`SuiteManifest`, `TaskManifest`, `BenchmarkResult`, check/claim/usage/timing/
  process-leak records). Import-safe: no I/O, no side effects on import.
- `benchmarks/pulse_reliability_v1/manifest.json` — 12 tasks PBR-001…PBR-012,
  ordered, validated by the contract.
- `benchmarks/pulse_reliability_v1/README.md` — task inventory + design rules.
- `src/tests/test_benchmark_contract.py` — 13 deterministic contract tests:
  13 passed in 0.12s (no external deps beyond Pydantic v2).

Design rules: evaluator-owned checks (never agent self-report),
bounded everything (timeouts/budgets/process ownership), outcome classification
(functional/verification/safety/harness/cancellation/environment),
no hidden background work, results never enter Git.
```

## Hard rules (repository-wide)

- Never `git add -A` / `git add .` / `git reset --hard` / `git clean`.
- `README.md` and `pulseAI.css` are user-owned files; never stage, restore,
  reset, stash or commit them unless the owner explicitly asks.
- No CDP scripts, screenshots, traces, logs or generated outputs in Git.
- Desktop contribution stays under `desktop/vscode/src/vs/workbench/contrib/pulseai/`.
- Engine/benchmark work stays out of desktop PRs and vice versa.
