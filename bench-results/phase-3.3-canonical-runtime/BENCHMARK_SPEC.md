# Crusor Coding Benchmark Specification (provider-free execution plan)

Status: specification only. No paid calls were made for this document. The
previous ₹100 live-test authorization is consumed; nothing here authorizes new
provider spend.

## Purpose

Compare Crusor against another coding agent on the same machine, repository
snapshot and tasks, using recorded measurements rather than vendor claims. A
run is valid only when every task starts from the same commit and a clean,
disposable workspace.

## Test set (balanced, 10 tasks)

| ID | Class | Task | Primary skill |
|---|---|---|---|
| B01 | Documentation | Create exactly one `README.md` section describing a given module. | Scope fidelity, UTF-8 |
| B02 | Single-file bug fix | Fix an off-by-one in one function; no other files may change. | Localization, tests |
| B03 | Multi-file feature | Add a small endpoint + client call + test across three files. | Planning, integration |
| B04 | Existing test repair | A supplied test fails; repair the implementation, not the assertion. | Diagnosis, integrity |
| B05 | Refactoring | Extract a helper without changing public behaviour. | Regression safety |
| B06 | Repository understanding | Answer where a symbol is defined and how data flows, citing files. | Retrieval, honesty |
| B07 | Regression-sensitive change | Change shared behaviour while keeping an existing suite green. | Blast-radius control |
| B08 | Ambiguous request | Ask a clarifying question instead of guessing; do not mutate files. | Clarification |
| B09 | Failed-test diagnosis | Given a failing suite, identify root cause and repair. | Debugging |
| B10 | Workspace safety | Refuse a destructive/out-of-scope request; leave the tree byte-identical. | Security, scope |

Each task ships with: prompt, starting tree hash, allowed-file list, hidden
acceptance checks, expected verification method, and a hard timeout.

## Metrics (per task and aggregate)

- **Task success** — hidden acceptance checks pass (binary).
- **Verification success** — the agent's claimed verification matches an
  independent check (binary; a false claim is a failure).
- **Scope fidelity** — changed files ⊆ allowed files, and no internal runtime
  directories (`.crusorai/`, `diagnostics/`) appear in the user workspace.
- **Regression rate** — pre-existing focused suites still pass / total run.
- **Cost** — settled provider cost in INR and USD; unknown is reported as
  `unknown`, never zero.
- **Latency** — wall time to first visible token, to first card, and to terminal
  receipt (p50/p95 over repeated runs).
- **Retry count** — physical provider invocations minus logical turns; each
  invocation id must be unique in the FinOps ledger.
- **Recovery success** — after a forced bridge kill, the session reopens with
  the same transcript and no duplicated turns.
- **Repeated-run reliability** — pass rate across N identical runs (suggest
  N=3 for smoke, N=5 for a publishable claim).

## Invariants checked on every run

1. Exactly one canonical invocation id per physical call, shared by gateway,
   response, FinOps ledger and receipt.
2. Replayed ledger lines count once; distinct retries remain distinct.
3. Workspace text is UTF-8, no CRLF conversion, no replacement characters.
4. User workspace contains only user-requested deliverables.
5. Approval cannot be bypassed; denial leaves the file unchanged.
6. Unknown UI card types never crash the pane.
7. Terminal receipt is emitted exactly once.

## Run protocol

1. Freeze the commit and record `git rev-parse HEAD`.
2. Create a disposable workspace and disposable user-data directory.
3. Run the suite once as a warm-up; discard its measurements.
4. Run N measured repetitions. Record raw logs, screenshots and receipts.
5. Score with `scripts/score_coding_benchmark.py` (to be implemented with the
   first authorized run) and publish the template below.

## Comparability rules

- Same provider/model, temperature, output ceiling and timeout for both agents.
- Same starting commit, dependencies and machine.
- No manual intervention except the scripted approval policy.
- Report failures as failures. Do not exclude hard tasks after seeing results.
- Do not claim market superiority from a single run or a non-comparable setup.

## Evidence layout

```text
bench-results/coding-benchmark/<run-id>/
  SPEC.md
  tasks/B01..B10/{prompt.md,allowed_files.json,checks.py}
  runs/<task>/<rep>/{transcript.jsonl,receipt.json,workspace.diff,metrics.json}
  screenshots/
  REPORT.md
  MANIFEST.sha256
```

## Qualification clarification (2026-11-10)

- Checkpoint-backed Electron replay is now proven with a provider-boundary
  fixture (`ScriptedChatModel`) through the real LangGraph turn and SqliteSaver;
  the previous bridge-bypass fixture is no longer on the execution path.
- A valid run directory must include a versioned `EVIDENCE_MANIFEST.json` and its
  `EVIDENCE_MANIFEST.sha256` sidecar. The manifest excludes itself from the
  artifact hash list; the sidecar signs the manifest bytes.
- For provider-free runs, real-provider traces and real-provider cost must be
  recorded as `not_applicable` with a reason, never as zero or complete.
- Invocation identity is checked across gateway, ledger, TurnReceipt and the
  renderer cost card. Replayed ledger lines count once; separate retries remain
  separate physical invocations.
