# PR 1C commit guide - first six benchmark fixtures

**What this is:** engine-side (Lane B) work. Apply + push only; no editorial edits.
PR 1B (evaluator) may be merged before or after this PR - the two patches are
conflict-free (1C touches only the suite README region that 1B does not).

**Patch:** `PR1C_fixtures.patch` - 4 files (3 new + README update), applies to repo
root at `main`. Verified: apply check OK; 70/70 tests pass after applying PR 1B +
PR 1C in sequence.

## Files this PR changes

| Path | Change |
|---|---|
| `benchmarks/pulse_reliability_v1/fixtures.json` | NEW - fixture manifest (`pulse-benchmark-fixtures/v1`): PBR-001 .. PBR-006, ordered, validated |
| `benchmarks/pulse_reliability_v1/fixtures.py` | NEW - deterministic generator: `FixtureManifest` / `FixtureSpec` / `GeneratedTree` models, `resolve_files()`, `build_fixture(spec, absolute_target_root)`, `hash_tree()`. ASCII-only, LF endings, import-safe |
| `src/tests/test_benchmark_fixtures.py` | NEW - 22 deterministic tests (build into pytest tmp dirs only; the 20k-entry build runs once per session) |
| `benchmarks/pulse_reliability_v1/README.md` | MODIFIED - status/files/validate/roadmap now cover evaluator + fixtures |

Fixture content: PBR-001 no-folder intent marker; PBR-002 workspace_proof.py +
notes + csv; PBR-003 two roots (root_a, root_b) with markers; PBR-004 generated
20k-entry tree + README (20,001 entries, built at run time - never committed);
PBR-005 failing test + implementation (read-only context task); PBR-006
intentional parser bug + failing test + unrelated stable util.

## Steps (repo checkout, freshly fetched `main`; if PR 1B is merged first, still branch from fresh `main`)

```powershell
# 1. Start clean
git fetch origin
git checkout main
git status                              # no unrelated changes; do not touch README.md / pulseAI.css
git switch -c benchmark/reliability-v1-fixtures

# 2. Apply the patch (copy PR1C_fixtures.patch into repo root first)
git apply --check --verbose PR1C_fixtures.patch
git apply PR1C_fixtures.patch

# 3. Test run BEFORE staging (repo venv; needs PR 1B merged, or apply both patches first)
D:\pulseAIRepo\.venv\Scripts\python.exe -m pytest src/tests/test_benchmark_contract.py src/tests/test_benchmark_evaluator.py src/tests/test_benchmark_fixtures.py -q
# expect: 70 passed (fixture suite ~5s: builds the 20k-entry workspace once)

# 4. Stage ONLY the four paths (never git add -A)
git add -- benchmarks/pulse_reliability_v1/fixtures.py benchmarks/pulse_reliability_v1/fixtures.json src/tests/test_benchmark_fixtures.py benchmarks/pulse_reliability_v1/README.md

# 5. Prove the stage is exactly the four paths
git status --short                  # 3x A + 1x M, nothing else
git diff --cached --stat            # 4 files; no __pycache__, no .pyc, no .pytest_cache

# 6. Commit + push
git commit -m "test(quality): add first six reliability fixtures"
git push -u origin benchmark/reliability-v1-fixtures
```

## PR body (paste as-is)

```markdown
# Pulse Reliability Benchmark v1 - first six fixtures (PR 1C)

Fixture generation for PBR-001 .. PBR-006 only. Nothing here executes Pulse:
generated workspaces are produced into an explicit absolute target root at run
time and never enter the repository. Desktop CDP execution is a separate lane.

- `benchmarks/pulse_reliability_v1/fixtures.json` - fixture manifest
  (`pulse-benchmark-fixtures/v1`), first six tasks, ordered by task id,
  validated by `FixtureManifest`.
- `benchmarks/pulse_reliability_v1/fixtures.py` - deterministic generator:
  `resolve_files()` (fixed content), `build_fixture(spec, absolute_root)`,
  `hash_tree()` (sorted sha256 map). ASCII-only, LF endings on every
  platform, import-safe, no execution side effects.
- `src/tests/test_benchmark_fixtures.py` - 22 deterministic tests:
  exact file sets, PBR-004 20,001 entries, byte-identical builds across
  roots, unsafe-path rejection, ASCII-only + no-secret hygiene,
  first-six-only scope guard.
- `benchmarks/pulse_reliability_v1/README.md` - updated for the fixtures.

Fixture content:
- PBR-001 no-folder: intent marker only (harness must open no folder).
- PBR-002 exact-workspace: workspace_proof.py identity marker.
- PBR-003 multi-root: root_a / root_b with distinct markers.
- PBR-004 large-20k: 20,000 generated entries + README (built at run time).
- PBR-005 context-relevance: failing test + implementation (read-only turn).
- PBR-006 single-file-bug: intentional parser bug + failing test + stable util.

Evidence: 70/70 tests pass (13 contract + 35 evaluator + 22 fixture) in ~5s.
No generated workspace, result data or logs are committed.
```

## Hard rules (unchanged)

- Never `git add -A` / `git add .` / `git reset --hard` / `git clean`.
- Never touch repo-root `README.md` / `pulseAI.css` / anything under `desktop/`.
- No generated outputs in Git. Fixture generation runs only against
  external target roots (temp/evidence dirs).
