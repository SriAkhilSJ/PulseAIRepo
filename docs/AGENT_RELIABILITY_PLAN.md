# Agent reliability repair plan before VS Code Agent UI work

**Date:** 2026-08-25  
**Evidence:** desktop Test-5 run `test5-5`, Hermes Agent comparison at `e5032945cbebb64b8a819b66ec831c1906297b81`

## Honest status

The agent is not reliable enough to move directly into Agent UI design. Test 5 exhausted 20 model calls and delivered zero files. The local Git checkout was clean at the start of this repair, but the cumulative PR is large, the failed product workspace is empty, and the IDE/workspace experience still needs a separate cleanup pass. UI design should not hide runtime failures.

## Attempt-5 causal timeline

Four model calls were spent before execution (classification, plan, validation, correction). The execution loop then:

1. rediscovered an empty workspace repeatedly;
2. sent POSIX `ls`, `pwd`, `find`, and `head` shapes to Windows `cmd.exe`;
3. ran verification repeatedly before a project existed;
4. paid KEEP/REPLAN classifier calls for deterministic local/no-op outcomes;
5. reached dependency acquisition without a landed baseline;
6. ended at the 20-call circuit breaker with no files.

The direct `curl -sL ... -o ...` command in the sanitized report is already considered safe by the current `SafetyGuard` and Windows-dialect preflight. Therefore this repair does **not** broadly allowlist downloads or weaken safety based on an imprecise “blocked by safety” label. The exact tool-result frame is needed to distinguish a phase-policy denial from a different command shape. The supported safe strategy remains `web_fetch(url) -> write_file(path, content)`, preferably inside one `execute_code` batch.

## Applicable Hermes patterns

Hermes does not rely only on prompt intelligence. Its runtime:

- hashes canonical tool arguments and tracks repeated failures;
- detects idempotent calls returning unchanged results;
- warns early and can block/halt bounded no-progress loops;
- uses deterministic guardrail decisions rather than paying a model to classify known policy outcomes;
- gives typed, actionable recovery feedback;
- distinguishes platform/tool availability before execution;
- keeps large-call recovery bounded and requires a changed strategy.

Pulse already has fragments of these controls, but Attempt 5 proved gaps between them: the Windows detector listed commands it never rejected, unavailable typechecks were classified as failures, and no cross-tool pre-delivery cap stopped varied inspection calls.

## Repair phases

### Phase A — stop zero-delivery loops (implemented in this change)

1. State the actual terminal platform and `cmd.exe` dialect in every Windows model iteration.
2. Reject all listed POSIX-only verbs before spawning, including the exact Attempt-5 shapes.
3. Hide `typecheck_workspace` until `tsconfig.json` exists.
4. Treat unavailable typechecks as no-op/unavailable, not failures or progress heartbeats.
5. Skip paid KEEP/REPLAN classification for deterministic policy/platform outcomes.
6. Warn after two main-agent iterations without a required file delivery.
7. After four such iterations, temporarily expose only file-delivery tools plus `execute_code`; restore normal tools after a file lands.
8. Keep direct download safety unchanged and pin the exact reported curl command as non-destructive.

Acceptance: deterministic replay cannot spend the remaining execution budget on varied reads, shell discovery, or phantom verification while delivering zero files.

### Phase B — evidence-led replay, no paid provider

Build a sanitized deterministic fixture from Attempt-5 tool/result shapes. Assert:

- no subprocess is spawned for POSIX commands on Windows;
- no replan-model call occurs for unavailable checks or policy denials;
- verification is unavailable before setup and cannot count as progress;
- forced delivery activates by the configured threshold;
- one baseline write restores the normal capability set;
- safety remains fail-closed for destructive/sensitive operations.

### Phase C — workspace and branch hygiene

The first full-suite run appeared stuck at 57%. A timed traceback proved it was
not a lock: `ChunkIndex(..., embedder=None)` unexpectedly entered Hugging Face
model download retries because explicit BM25-only `None` and an omitted lazy
embedder shared the same value. Those constructor modes are now distinct. The
previously stuck test completes in about 0.1 seconds, and the language/index/
context selection completes with 92 passed and 1 skipped without that network
retry path.

Before UI work:

- inventory PR #9 against `main` by purpose, not only file count;
- separate current runtime fixes from historical/stale documentation where safe;
- keep generated benchmark evidence and build output untracked;
- verify the desktop checkout, generated test workspace, and Git working tree independently;
- do not delete preserved failed-run evidence.

### Phase D — controlled live evaluation

No new paid attempt is authorized yet. If deterministic replay passes and the founder approves another run, use a fresh workspace/run ID with a lower early no-delivery stop in addition to the existing hard credit cap. Runtime pass still does not imply product pass.

### Phase E — VS Code Agent UI

Only after runtime behavior and workspace hygiene are reviewed, move to the first-party Pulse workbench UI. The UI phase should expose—not conceal—plan cost, platform, tool denials, no-progress warnings, mutation receipts, verification state, and budget stops.
