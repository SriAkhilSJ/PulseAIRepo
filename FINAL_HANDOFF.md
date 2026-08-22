# FINAL HANDOFF - Benchmark PR 1B + PR 1C (engine-side, agent commits)

All engine-side work is complete and validated. The agent only applies,
commits and pushes. Two patches = two PRs (one concern each, per roadmap).

## Files to place in the founder machine repo root (next to .git/)

1. `PR1B_evaluator.patch`   (2 new files, applies to `main`)
2. `PR1C_fixtures.patch`    (3 new files + README update, applies to `main`;
   conflict-free regardless of whether PR 1B merged first)

Reference only (not applied): `PR1B_COMMIT_GUIDE.md`, `PR1C_COMMIT_GUIDE.md`,
`R03_DESKTOP_TASK.md`.

## Order

- Phase 1: PR 1B (evaluator) branch `benchmark/reliability-v1-evaluator` -> push.
- Founder merges PR. (Or, if the founder prefers: push both branches now; merge
  1B then 1C - both patches are conflict-free in either order.)
- Phase 2: PR 1C (fixtures) branch `benchmark/reliability-v1-fixtures` -> push.
- Founder merges PR.
- Parallel: desktop agent runs `R03_DESKTOP_TASK.md` from merged `main`.

## Exact prompt to paste to the courier agent

```text
You are a courier-only executor for PulseAIRepo. You will NOT write, design,
review or refactor any code, and you will NOT request or paste credentials or
tokens. If anything asks for auth, stop and report. Two prepared patches sit in
the repo root: PR1B_evaluator.patch (benchmark evaluator core) and
PR1C_fixtures.patch (first six benchmark fixtures).

HARD RULES: never git add -A / git add . / git reset --hard / git clean /
force-push. Never modify, restore, stage or commit repo-root README.md,
pulseAI.css, or anything under desktop/. Never touch
benchmarks/pulse_reliability_v1/contract.py or manifest.json. Never include
__pycache__/.pyc/.pytest_cache. Never merge. Only apply, commit, push, report.

=== PHASE 1 (PR 1B) ===
1) git fetch origin && git status --short
2) git switch -c benchmark/reliability-v1-evaluator
3) git apply --check --verbose PR1B_evaluator.patch      (must show 2 files)
4) git apply PR1B_evaluator.patch
5) D:\pulseAIRepo\.venv\Scripts\python.exe -m pytest src/tests/test_benchmark_contract.py src/tests/test_benchmark_evaluator.py -q
   (expect "48 passed" - paste the whole line)
6) git status --short                                     (exactly 2x A)
7) git add -- benchmarks/pulse_reliability_v1/evaluator.py src/tests/test_benchmark_evaluator.py
8) git diff --cached --stat                               (exactly 2 files)
9) git commit -m "feat(quality): add deterministic benchmark evaluator"
10) git push -u origin benchmark/reliability-v1-evaluator

=== PHASE 2 (PR 1C; run after founder confirms PR 1B merged, or immediately -
       the patches are conflict-free in either order) ===
11) git fetch origin && git switch main && git status --short
12) git switch -c benchmark/reliability-v1-fixtures
13) git apply --check --verbose PR1C_fixtures.patch      (must show 4 files)
14) git apply PR1C_fixtures.patch
15) D:\pulseAIRepo\.venv\Scripts\python.exe -m pytest src/tests/test_benchmark_contract.py src/tests/test_benchmark_evaluator.py src/tests/test_benchmark_fixtures.py -q
    (expect "70 passed" - paste the whole line; fixture suite ~5s)
16) git status --short                                    (exactly 3x A + 1x M)
17) git add -- benchmarks/pulse_reliability_v1/fixtures.py benchmarks/pulse_reliability_v1/fixtures.json src/tests/test_benchmark_fixtures.py benchmarks/pulse_reliability_v1/README.md
18) git diff --cached --stat                              (exactly 4 files)
19) git commit -m "test(quality): add first six reliability fixtures"
20) git push -u origin benchmark/reliability-v1-fixtures

=== FINAL REPORT (both phases) ===
For each phase: commit sha, full pytest tail output, git status --short,
git diff --cached --stat, push output, and explicit confirmation that no
existing file other than the listed paths was changed.
```

## PR bodies (paste into GitHub when opening the PRs)

**PR 1B** - see `PR1B_COMMIT_GUIDE.md` (title: `feat(quality): add deterministic benchmark evaluator`).
**PR 1C** - see `PR1C_COMMIT_GUIDE.md` (title: `test(quality): add first six reliability fixtures`).

## Validation state (remote agent)

- Contract: 13 tests; Evaluator: 35 tests; Fixtures: 22 tests. Total 70/70.
- Sequential apply of 1B then 1C on a fresh `main` tree: verified OK; full
  70/70 suite green on the applied tree.
- Both patches: ASCII-safe end state, no generated artifacts, no desktop files,
  no changes to contract.py / manifest.json.
- PBR-004 20k-entry fixture builds deterministically in ~4s (once per session).

## Next after merges

- I verify both branches/PRs from the remote, then the founder merges.
- Desktop agent: `R03_DESKTOP_TASK.md` (optimized build + CDP proof from
  merged main, evidence to `D:\pulse-res\r03-<timestamp>\`, no commits).
- Then PR 1D discussions (benchmark runner wiring) or continuation of the
  roadmap (weeks 3-4) - scoped when the time comes.
