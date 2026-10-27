# Agent Core — implementation and verification handoff

**Updated:** 2026-10-27

**Implementation commit:** `f8108ccd9d3e1093fb464da9229bf8a83ea94d07`

**Status:** implementation and provider-free regressions complete; the latest full-stack live benchmark is still **failed**, and the new repair loop has not yet been provider-backed revalidated.

## Executive summary

Agent Core was strengthened after a bounded live build produced all required files but failed SQLite persistence. The important defect was not the generated application itself. The general Agent Core defect was that a concrete failed project check did not create a durable repair obligation: a later, different passing check could make verification look green without proving that the original failure was fixed.

The repair is intentionally task-, provider-, model-, filename-, framework-, and database-independent:

1. a concrete non-environment verification failure creates hashed verification debt;
2. Agent Core must land a successful file mutation before it can verify again;
3. after mutation, only verification tools are exposed;
4. only a successful rerun with the same check identity clears the debt;
5. a weaker or different passing command cannot authorize completion; and
6. CI monitoring is published in bounded, independently parseable, secret-redacted chunks.

This is a safety and completion-integrity improvement. It does **not** mean the failed application benchmark now passes.

## Evidence that triggered the work

The latest authorized full-stack evidence run was GitHub Actions run [`40576857348`](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40576857348), job `122445482482`.

| Measure | Observed result |
|---|---|
| Acceptance | **4/5 passed; run failed** |
| Exact failure | `test_04_crud_stats_and_sqlite_persistence` raised `sqlite3.OperationalError: no such table: tasks` |
| Required outputs | All five required files existed |
| Generated application size | 27,162 bytes |
| Provider requests | 12/12 returned successfully |
| Tool outcomes | 15 completed outcomes captured |
| Runtime | 104 seconds |
| Agent verdict | `completed=false`; `completion_evidence_ready=false` |
| Test integrity | Immutable tests remained unchanged |
| Credential privacy | Provider secret absent from generated files and `outcome.json` |
| Extra output | The grader detected an unexpected top-level file; the retrievable evidence did not preserve its name, so it is not guessed here |

The failure proves that API activity did not persist through the database selected by the required environment contract. More importantly for Agent Core, the failed acceptance check did not reliably drive a mutation followed by an exact recheck before termination.

Monitoring collection worked, but monitoring publication had a separate weakness. The complete sanitized ledger was assembled in ephemeral `outcome.json`; GitHub truncated the single annotation at exactly 4,096 characters, and Actions log retrieval returned `EOF`. The full tool sequence therefore cannot be reconstructed after the run and is not claimed as observed.

## What changed and why

| Before | After | Why |
|---|---|---|
| A failed executable check was only a recent status. | A non-environment failure creates identity-scoped verification debt from the execution trace. | Failed evidence must survive later edits and unrelated checks. |
| Any later passing static command could make the aggregate receipt look green. | `failed_checks` is a required completion domain, and only the same check identity passing removes its debt. | A narrow health check cannot erase a failed acceptance suite. |
| Verification repair exposed mutation and verification tools together. | Routing alternates structurally: failed check → mutation-only repair → check-only revalidation. | The model cannot repeatedly test unchanged code or claim a repair without changing a file. |
| Fresh delivery guidance suggested handling more files in later iterations. | Independent named files are explicitly batched as multiple complete file calls in the same response. | Bounded calls remain available for dependency installation, testing, diagnosis, and repair. |
| CI emitted the entire sanitized outcome as one annotation. | The runner emits separate summary, request-receipt, and tool-outcome JSON annotations, each capped at 3,500 characters. | Evidence stays parseable and retrievable below GitHub's 4,096-character limit. |
| Annotation fields trusted normal internal sizes. | Summary and event fields are independently bounded and defensively allowlisted/redacted. | Malformed or unexpectedly large fields cannot break the publication bound or disclose arguments/content. |

## Implementation details

### 1. Durable failed-check debt

`src/graphs/gates.py` now provides two internal contracts:

- `_verification_trace_key(item)` creates a stable identity for supported executable checks. Direct terminal aliases are canonicalized together, incidental command whitespace is normalized, and the identity is stored as a short SHA-256 digest rather than copied into completion metadata.
- `_unresolved_failed_verification_checks(state)` replays the ordered execution trace. It records failed checks, marks a repair only after a successful `write_file`, `edit_file`, or `copy_file`, and removes debt only when the exact check later succeeds.

Environment/tooling failures classified by the existing environment-failure policy do not create source-repair debt. Missing executables and PATH failures need a strategy pivot, not an arbitrary code edit.

The completion receipt now requires `failed_checks=true`. A different passing check can satisfy its own static domain, but completion remains blocked while any failed-check debt is unresolved.

### 2. Structural repair/recheck phases

`src/graphs/chat_graph.py` now derives two phases from state:

- `verification_repair_required`: exposes narrow source inspection and file mutation tools while withholding terminal and verifier tools;
- `verification_recheck_required`: after a successful mutation, withholds mutation and broad inspection while exposing check tools for revalidation.

A repeated failure resets the obligation back to mutation-required. Multiple debts remain until each exact identity passes. If a runtime profile lacks mutation tools, the graph no longer falls through and permits an unchanged recheck.

The exact-command requirement is completion-enforced through debt identity and reinforced in phase guidance. The current executor does not yet constrain arbitrary terminal arguments to one preapproved command hash; a real model can waste bounded recheck calls on weaker commands, but those commands cannot falsely clear debt or authorize completion.

### 3. Same-response delivery batching

Forced-delivery and missing-delivery guidance now asks for all independent named files in one response. This does not increase any call, token, or mutation cap. It makes legal use of existing parallel tool-call support and avoids knowingly spending one provider iteration per obvious file.

### 4. Retrievable monitoring

`scripts/run_bridge_turn.py` now builds GitHub annotations from an explicit allowlist:

- summary fields: schema, result, completion, counts, timing, omissions, and privacy contract;
- request fields: sequence, status, and duration;
- tool fields: sequence, tool name, status, duration, and bounded redacted result summary.

Prompts, tool arguments, commands, file bodies, IDs, and full results are not selected. Secret-like values and configured secret environment values are redacted. Every annotation is standalone JSON and defaults to at most 3,500 characters. Publication occurs only when `GITHUB_ACTIONS=true`; the local `outcome.json` contract remains available independently.

## Files changed in the implementation

| File | Purpose |
|---|---|
| `src/graphs/gates.py` | Failed-check identity, durable debt replay, and completion blocking |
| `src/graphs/chat_graph.py` | Mutation-only repair, check-only revalidation, and delivery batching |
| `scripts/run_bridge_turn.py` | Chunked, bounded, redacted GitHub monitoring annotations |
| `src/tests/test_attempt11_product_delivery_boundary.py` | Repair/recheck, weaker-check, exact-clear, environment, and batching regressions |
| `src/tests/test_autonomous_runtime_contract.py` | Forced-delivery batching contract |
| `src/tests/test_run_bridge_turn.py` | Annotation completeness, JSON parseability, size, privacy, and malformed-field bounds |
| `docs/CRUSOR_FULLSTACK_BENCHMARK.md` | Immutable live result and corrective analysis |

## Verification completed

### Provider-free checks

| Check | Result |
|---|---|
| Affected repair/routing/annotation files | **33 passed** |
| Earlier broader completion/routing/progress/runner gate | **181 passed** |
| Clean detached branch full suite | **2,801 passed, 25 failed, 26 skipped, 1 xfailed** |
| Clean detached `origin/main` full suite | **2,659 passed, 25 failed, 26 skipped, 1 xfailed** |
| New failing test identities vs. `main` | **0** |
| Changed-module Python compilation | Passed |
| Scoped `git diff --check` | Passed |
| Diff-aware Ruff | 0 findings on added lines; 49 historical findings remained in touched legacy modules |
| Production-diff provider-specific marker scan | 0 |
| Production-diff credential-pattern scan | 0 |

The clean branch and clean `origin/main` have the exact same set of 25 failing test identities. The branch adds 142 passing tests and introduces 0 new full-suite failures. An earlier run in the preserved dirty primary checkout reported 30 failures; five working-tree-dependent failures disappeared in the clean detached checkout and are not part of the merge baseline. The remaining failures are not hidden, but they are not attributed to this repair slice without separate evidence.

### Live evidence

The only live full-stack evidence for this stage is the failed 4/5 run described above. It predates the durable verification-debt repair. Provider-free tests prove deterministic routing and completion contracts; they do not prove that a live model will use the new bounded loop effectively.

## What still needs verification

### Required before claiming the full-stack benchmark passes

1. **A newly authorized bounded provider-backed run.** Reuse the immutable grader and strict call/token/time ceilings. Do not infer a pass from local tests.
2. **Functional acceptance:** all five tests must pass, including database creation, CRUD, stats, restart persistence, and use of the required environment-selected database.
3. **Output integrity:** all required files must exist, tests must remain byte-for-byte unchanged, no unexpected file/symlink may appear, and no credential may be persisted.
4. **Truthful completion:** `completed=true` is acceptable only when the completion receipt is ready. A functional failure must remain `completed=false`.
5. **Monitoring retrieval:** GitHub Checks must retain every independently parseable annotation; published request/tool counts must match the outcome summary, with no secret or full content present.

No additional provider-backed run is authorized by this document. It requires a fresh explicit user decision and must use the existing protected secret without printing or copying it.

### Required before calling the repair loop universally covered

1. Exercise a controlled live failure that requires an edit, then confirm the observable sequence is failed check → successful mutation → same check rerun.
2. Add explicit coverage for long-running asynchronous terminal verification (`start_terminal` / `check_terminal`) if those results are expected to create the same debt contract as direct terminal calls.
3. Expand command-recognition coverage for additional ecosystems only from real executable-check evidence; do not classify every failed shell command as a source verification failure.
4. If live traces show the model spending recheck calls on weaker commands, add argument-level exact-check enforcement or a deterministic replay mechanism rather than benchmark-specific prompting.

### Other repository verification still open

- The 25 clean full-suite baseline failures need their own owner/classification and should be rerun in the intended dependency/desktop environment.
- Native desktop integration, compiled Code OSS output, screenshots, and SQLite/log evidence belong in the desktop-agent handoff on a supported host. They were not claimed from this sandbox.
- The new chunked annotation publisher has provider-free tests but has not yet been observed in a subsequent GitHub Actions run.

## Recommended next validation order

1. Keep provider traffic at zero and rerun the affected 33-test gate after any further edit.
2. Run the broader completion/routing/progress/runner set.
3. Run the full provider-free suite and compare failures to the recorded baseline.
4. Validate desktop/runtime behavior through the desktop agent where the required host is available.
5. Only after explicit authorization, run one bounded live benchmark and collect the chunked annotations before making any success claim.

## Upstream agent comparison

The implementation was informed by source-level behavior in leading agents, not product marketing. The inspected pinned commits and takeaways are recorded in `docs/CRUSOR_FULLSTACK_BENCHMARK.md`. Repository heads were rechecked on 2026-10-27:

| Repository | Inspected evidence commit | Head observed during this documentation update |
|---|---|---|
| OpenCode | `caebbcc0807e630629725f320f35a09aa4a427be` | `f7d0ce133d77` |
| OpenHands software-agent SDK | `ded5fa5e76ff9b7b4ff622a8df2ed20335e10652` | `1fc146c4bd42` |
| Gemini CLI | `8080ea70a54cda947b6c4f38293f195241e45968` | `8080ea70a54c` |
| Cline | `775d0398039977ca5447ed39c1a7f178df69aa87` | `943d6284ccc4` |
| Codex | `b6ad8ea1fcd5562a7d3003887930be7d84824307` | `d93071fae87f` |

The head lookup is a freshness check, not a claim that every newer change was audited. Behavioral claims remain tied to the inspected commits.

## Non-goals and preserved boundaries

- No SprintBoard, SQLite, expected filename, model, or provider special case was added to Agent Core.
- No generated benchmark application was committed.
- No temporary provider workflow remains in the tree.
- No provider secret was printed, stored, or added to Git.
- No pull request, merge, preview, or deployment was created for this work.
- Existing generated desktop and diagnostics working-tree changes were excluded from the implementation commit and preserved.

## Documentation updated with this handoff

| Document | Update |
|---|---|
| `README.md` | Current failed live status, repair behavior, monitoring, test evidence, and navigation to this handoff |
| `AGENT_HANDOFF.md` | Marks the old CopilotKit handoff as historical and removes the obsolete claim that no live model call had run |
| `docs/AGENT_CORE_COMPLETION_DISCIPLINE.md` | Adds durable failed-check debt and the current provider-free receipt while preserving the original reserve evidence |
| `docs/AGENT_CORE_PERFORMANCE_EVIDENCE.md` | Scopes the earlier 6/6 debugging pass so it cannot be mistaken for the later full-stack result |
| `docs/AGENT_CORE_RUNTIME_EVIDENCE.md` | Documents chunked CI bridge-run publication and its privacy/acceptance boundary |
| `docs/CRUSOR_FULLSTACK_BENCHMARK.md` | Links the immutable run record to this current implementation handoff |
| `benchmarks/crusor_reliability_v1/README.md` | Separates reusable evaluator tests from provider-backed product acceptance and refreshes the gate to 102 passing tests |
| `ci/README.md` | Documents bounded Actions annotations and the fact that monitoring is not acceptance |

## Related documentation

- [`docs/CRUSOR_FULLSTACK_BENCHMARK.md`](docs/CRUSOR_FULLSTACK_BENCHMARK.md) — complete immutable benchmark history and evidence
- [`docs/AGENT_CORE_COMPLETION_DISCIPLINE.md`](docs/AGENT_CORE_COMPLETION_DISCIPLINE.md) — inclusive call budget and evidence-gated completion
- [`docs/AGENT_CORE_PERFORMANCE_EVIDENCE.md`](docs/AGENT_CORE_PERFORMANCE_EVIDENCE.md) — earlier successful bounded debugging task
- [`docs/AGENT_CORE_RUNTIME_EVIDENCE.md`](docs/AGENT_CORE_RUNTIME_EVIDENCE.md) — durable runtime evidence manifest contract
- [`AGENT_HANDOFF.md`](AGENT_HANDOFF.md) — historical CopilotKit/desktop handoff; superseded by this file for current Agent Core status
