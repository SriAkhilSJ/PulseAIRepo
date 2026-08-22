# Pulse Reliability Benchmark v1

**Suite id:** `pulse-reliability-v1` · **Manifest schema:** `pulse-benchmark-manifest/v1`

A machine-readable, evaluator-owned benchmark for PulseAI IDE. It measures whether Pulse
is a *trustworthy local engineering runtime* — correct workspace awareness, bounded
context, editable and verifiable work, safe lifecycle behavior — not whether it can
produce a plausible chat reply.

## Status: contract only (PR 1A)

This directory currently contains **only the contract**: the Pydantic schema
(`contract.py`), the task manifest (`manifest.json`), and their contract tests
(`src/tests/test_benchmark_contract.py`).

- No evaluator engine yet (planned: PR 1B).
- No fixture workspaces yet (planned: PR 1C — first six tasks).
- No model calls, no network, no process spawning, no desktop execution.
- No generated result data is committed; results belong in a separate, ignored location.

## Files

| Path | Purpose |
|---|---|
| `contract.py` | Strict Pydantic v2 models: `SuiteManifest`, `TaskManifest`, `BenchmarkResult`, check/claim/usage/timing/leak records. Import-safe; no I/O at import. `load_suite()` validates a manifest; `write_json_schemas()` emits JSON Schemas (explicit developer action). |
| `manifest.json` | 12 task definitions (`PBR-001` … `PBR-012`), ordered by id, validated by `SuiteManifest`. |
| `__init__.py` | Package marker (directory name uses underscores so Python can import it; the public suite id keeps hyphens: `pulse-reliability-v1`). |
| `src/tests/test_benchmark_contract.py` | Deterministic contract tests for the manifest and result model invariants. |

## Validate

```bash
python -m pytest src/tests/test_benchmark_contract.py -q
```

or, from the repository root:

```bash
python -c "from benchmarks.pulse_reliability_v1.contract import load_suite; s = load_suite('benchmarks/pulse_reliability_v1/manifest.json'); print(len(s.tasks), 'tasks validated')"
```

## Task inventory (v1)

| Id | Category | Risk | Title |
|---|---|---|---|
| PBR-001 | workspace | read-only | Block prompts when no folder is open |
| PBR-002 | workspace | read-only | Route the exact opened workspace through every layer |
| PBR-003 | workspace | read-only | Require explicit selection in a multi-root workspace |
| PBR-004 | context | read-only | Bound initial context for a 20k-entry workspace |
| PBR-005 | context | read-only | Prioritize the active failing file and its related test |
| PBR-006 | editing | workspace-write | Repair a single-file parser bug with focused verification |
| PBR-007 | editing | workspace-write | Rename a public symbol across implementation callers and tests |
| PBR-008 | verification | workspace-write | Block completion until a syntax regression is repaired |
| PBR-009 | verification | workspace-write | Distinguish a pre-existing unrelated test failure |
| PBR-010 | verification | workspace-write | Detect and repair a regression introduced by the agent |
| PBR-011 | lifecycle | process | Recover from a timed-out command tree without orphaning children |
| PBR-012 | lifecycle | read-only | Cancel a turn during bounded context preparation |

Each task declares: platform support, timeout, whether model calls are allowed,
a network policy, a workspace fixture reference, the prompt, allowed/forbidden
capabilities, evaluator-owned checks, and hard-failure categories (workspace
escape, secret disclosure, unapproved network, false success claims, orphaned
processes, …).

## Design rules

1. **Evaluator-owned checks.** A task passes only when *its* checks say so — never
   because the agent claimed success. `false_success_claim` is a hard failure.
2. **Everything is bounded.** Timeouts, budgets, process ownership and shutdown
   requirements are declared in the manifest, not discovered mid-run.
3. **Classification, not just pass/fail.** Outcomes distinguish functional,
   verification, safety, harness, cancellation and environment failures;
   checks distinguish new vs pre-existing failures.
4. **No hidden work.** Any watcher, indexer, model call or subagent needs an
   owner, budget, timeout, cancellation path and shutdown path.
5. **Results never enter Git.** Run artifacts, screenshots and logs stay out of
   history. Only the manifest and contract are versioned here.

## Roadmap

- **PR 1A (this PR):** contract + manifest + contract tests.
- **PR 1B:** deterministic evaluator core (isolated fixture root, baseline
  hashes, process registry, normalized result JSON, Markdown report).
- **PR 1C:** first six fixtures (PBR-001 … PBR-006) and end-to-end runs on the
  founder machine with CDP proof; no shared workspace cloning.
