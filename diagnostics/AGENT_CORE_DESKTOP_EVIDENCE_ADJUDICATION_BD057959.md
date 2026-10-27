# Agent Core desktop evidence adjudication — `bd057959`

**Local adjudication date:** 2026-10-24

**Implementation originally tested:** `b330e11883fff988f607d8c751b786201df4289e`

**Desktop handoff:** `e5fae967a8aa31d77cd4d635e0607350705bab1b`

**Evidence commit:** `bd05795979cde7e6e4f935552e7cfdf282496a64`

**Agent Core corrective commit:** `dac332ca7a5a65fc7f2964c6be54182385abbfbc`

**Final desktop target:** `b22d6efce922357ca7c04b3e59106db2da86849d`

## Verdict

**Rejected as a complete successful verification.**

The package contains useful raw receipts, and several low-level behaviors are
independently corroborated. It does not establish the claimed scenario matrix:
the wrong workspace was used, the visible renderer was marked stale, unrelated
scenarios shared sessions, E and G were not run, only one screenshot exists,
there is no engine log, and several `RESULTS.md` claims conflict with trace and
report rows.

This is not a rejection of every observed behavior. The distinction is:

- **corroborated mechanics** remain valid observations;
- **scenario PASS claims** that rely on missing, stale, shared-session, or
  contradictory evidence are rejected;
- **application defects** established by raw evidence were fixed by the main
  agent in `dac332ca`, with the final non-stale renderer provenance in
  `b22d6efc`;
- **protocol/build defects** require a clean rerun and were not disguised as
  backend failures.

## Artifacts independently inspected

Every committed artifact under
`diagnostics/desktop-evidence/agent-core-b330e118/` was read, including:

- `RESULTS.md`, `provenance.txt`, and `sessions.json`;
- all three JSONL traces (36 rows total);
- all four Markdown reports;
- all three SQLite extracts;
- the one screenshot and its provenance hash;
- the 69-test desktop log.

The screenshot SHA-256 is
`f6e8f79edc3e0802225bc725b72e5ee6314cb7fe60e5b19373220aab6329cdd9`.

## Scenario-by-scenario adjudication

| Scenario | Raw observation | Adjudication |
| :--- | :--- | :--- |
| **A — quoted action** | One `terminal` proposal, one execution of `python --version`, exit `0`, no mutation. The first final row is `FINAL_VERDICT: failed`. | Action routing/execution is corroborated. Unqualified PASS is rejected because successful read-only work was falsely finalized as failed. Fixed in `dac332ca`. |
| **B — no install** | Only `check_target_toolchains(target=android)` executed. Android was reported ready with optional `maestro` absent. No installer/write execution. Final row says `completed`. | Mechanics corroborated. Package-level PASS rejected because A/B shared a session and used the prohibited workspace. Must rerun in isolation. |
| **C — greeting replacement** | `write_file` body became typed omission metadata (`reason=tool_body`, size `21`); run output was `interest-ok`. The report/trace User Ask still begins `hello Latest user direction:`. Final verdict is `unverified`. | Sanitization and execution mechanics corroborated. “Greeting replaced cleanly” is contradicted. Phatic-to-substantive reset fixed in `dac332ca`. |
| **D — non-zero outcome** | Exact command executed once, printed `failure-probe`, exited `3`; tool row is failed, runtime event is `error`, final verdict is `failed`; no retry execution exists. | Corroborated and verdict-honest. Must still rerun in a clean isolated session for the corrected build. |
| **E — verification-only** | No exact E prompt, no E trace, no `verify_target_app` runtime event, and no verification event. | **Not run.** Inference from B is invalid. |
| **F — cleanup** | Typed omission, successful write, successful run/remove/list command, and final listing excludes `cleanup_probe.py`. There is no F finalize row. Its report still carries D’s `failed` verdict and one-execution receipt. | Cleanup mechanics corroborated. Full PASS rejected: D/F shared a session, terminal evidence is stale, and F was captured before authoritative finalization. Pending-report reset and turn isolation fixed in `dac332ca`; rerun required. |
| **G — restart hydration** | `RESULTS.md` says `UNAVAILABLE`; no before/after restart evidence exists. | **Not run.** |
| **H — report honesty** | Reports expose verdict/status and `/100`, but aggregate cache is numeric while every AI row says cache `N/A`. D’s terminal receipt appears under F before F finalization. | Partial report mechanics only. Cache and stale-terminal contradictions fixed in `dac332ca`; rerun required. |

## SQLite findings

### Runtime journal

The committed extract corroborates intent/result pairing for the observed tools:

- A command intent/result appears once and finishes with exit `0`;
- B invokes only target inspection;
- C and F write intents store typed body-omission metadata rather than raw
  bodies;
- D records exit `3` as an error and has no duplicate command execution;
- F’s chained command exits `0` after run, removal, and absence listing.

### Verification database

- two state rows are `unverified`;
- the extract contains **zero verification-event rows**.

This directly disproves any claim that E was exercised or that a separate
verification receipt exists in the package.

### Desktop sessions

All three committed session records point to:

`C:\Users\Administrator\Downloads\testCRUSOR`

That path was expressly prohibited by the handoff. It is not the required new,
disposable evidence workspace.

## Build and UI findings

The only screenshot visibly reads:

`e5fae967 ui 2026-10-23-39 STALE`

Source inspection then found a deeper provenance defect:

- renderer TypeScript source stamp: `2026-10-19-38`;
- committed renderer JavaScript stamp: `2026-10-23-39`;
- `SOURCES_HASH` nevertheless matched the source tree, because it hashed
  sources but did not prove generated JavaScript corresponded to them.

Therefore a fresh emit from that checkout would have moved the visible stamp
backward and still appeared stale. This was not a reason to patch Agent Core
blindly. The main agent corrected the source stamp, regenerated the full scoped
bundle from source, added a source/output stamp pin, and made emitter output
whitespace-reproducible in `dac332ca`.

The resulting implementation commit was created at `2026-10-25 +0000`; the
initial `2026-10-24-40` stamp would therefore still make the UI's date
comparison display `STALE`. `b22d6efc` advances the stamp and officially
regenerates the renderer so the visible identity agrees with the Git build date.

Final bundle facts:

- source stamp: `2026-10-25-41`;
- compiled stamp: `2026-10-25-41`;
- source/bundle provenance hash:
  `9f13da07532512350fc000a8b21039cedced820f1f295381e0f53e0987588d6c`;
- independent hash recomputation: match;
- renderer date comparison against final target: `STALE=false`.

## Application defects established and fixed

### 1. Read-only actions were judged against a mutation-only finish bar

A no-change action deliberately has mutation tools removed. The finish gate
still required a write/edit/copy-style work count, so A’s successful terminal
receipt could never satisfy it. Two impossible nudges followed, and the final
nudge marker converted the successful turn to `failed`.

**Fix:** no-change actions now satisfy the first-action bar with an actual tool
receipt; mutation-capable delivery tasks retain the stricter artifact bar.
A deterministic A-shaped test now requires both `should_continue == finalize`
and final verdict `completed`.

### 2. A greeting remained the durable objective

With the optional classifier off, `hello` followed by a substantive action was
merged as continuing steering.

**Fix:** a substantive answer/action after a social objective is a deterministic
replacement with zero provider call. Task state, old failures, plans, and trace
accounting reset as a fresh task.

### 3. Turn-local gate budgets leaked across prompts

Only iteration/token channels were consistently reset. `finish_nudges`,
`verify_nudges`, `stall_continuations`, and `nudged_at_msg_count` could survive
checkpoint resume, making later turns depend on the prior turn’s spent budget.

**Fix:** all safety/gate channels reset at every entrypoint and every task-manager
path. Active-task history remains separate.

### 4. Mid-turn reports reused the previous terminal verdict

A session-scoped tracker retained D’s terminal receipt until F finalized, so an
interrupted/captured F report presented D as F’s “authoritative” verdict.

**Fix:** `begin_turn` immediately changes terminal evidence to `in_progress /
pending / N/A` before graph work. Finalization remains the only operation that
installs the authoritative terminal receipt. Report labels now explicitly say
`Current-turn executed tool records` and `Current-task failed steps`.

### 5. Cache reporting contradicted itself

Positive provider cache counts were relabeled unreported solely because the
gateway name contained `velona`. The report then scored the positive aggregate
while rendering each call `N/A`.

**Fix:** a positive cache count is reporting evidence. Explicitly unreported
rows are excluded from both cache numerator and denominator. Aggregate, row,
and score now share one evidence set.

## Protocol failures that are not application defects

No backend patch can substitute for these missing test controls:

1. prohibited `testCRUSOR` workspace;
2. A/B and D/F session sharing;
3. missing E run;
4. missing G restart/resume run;
5. one screenshot instead of per-scenario UI evidence;
6. no committed engine log;
7. stale renderer visible in the only screenshot;
8. unsupported “corroborated in UI” claims for scenarios without screenshots;
9. synthetic-credential omission claimed but not separately exercised;
10. F captured without a final trace row.

The corrected handoff requires each control directly.

## Main-agent validation of final target `b22d6efc`

### Green gates

- focused user-interest, diagnostics, verdict, and renderer selection:
  **203 passed, 1 skipped, 1 expected failure**;
- Agent Core/classifier/reporting selection after turn-reset contract update:
  **144 passed**;
- final A-shaped/classifier/tracker selection: **76 passed**;
- final renderer stamp/hash/build-date selection: **6 passed**;
- Python compilation for changed Python modules/tests: passed;
- generated JavaScript syntax checks: passed;
- `git diff --check`: passed;
- independent renderer hash/stamp check: passed.

These selections overlap and are reported as separate commands, not added into
an invented total.

### Full repository disclosure

`python -m pytest -q src/tests` produced:

- **2,756 passed**;
- **7 failed**;
- **25 skipped**;
- **1 expected failure**.

The seven remaining failures are outside this Agent Core patch and were not
silently waived:

- two tests expect renderer features absent from current TypeScript source;
- two tests expect bridge `turn_model_wall` wiring absent from current source;
- one expects a removed terminal cancellation constant;
- one expects an older terminal-timeout message;
- one imports a removed `scaffold_tools` module.

An LSP timing test failed once in the first full run and passed immediately and
in the final full run; it is not counted among the final seven.

## Required next action

Run `diagnostics/DESKTOP_AGENT_RERUN_B22D6EFC.md` exactly. Do not upgrade this
adjudication to PASS until the corrected evidence package contains isolated raw
receipts for every required scenario, including E, G, renderer/engine
provenance, per-scenario screenshots, SQLite extracts, and the engine log.
