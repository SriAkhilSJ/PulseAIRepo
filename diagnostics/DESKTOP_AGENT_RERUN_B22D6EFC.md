# Direct desktop-agent rerun — Agent Core `b22d6efc`

## Mission

Directly test the corrected Agent Core implementation at
`b22d6efce922357ca7c04b3e59106db2da86849d` in a real desktop runtime. Capture
complete UI, trace, report, SQLite, and engine-log evidence. This protocol
supersedes `DESKTOP_AGENT_HANDOFF_B330E118.md` for the rerun.

This is an evidence-only assignment. The main agent owns application code. The
desktop agent reports what the runtime actually did and pushes evidence to the
existing authorized branch; it does not ask the user to relay results.

## Non-negotiable role boundary

The desktop agent may:

- fetch the existing authorized branch;
- install ordinary project dependencies needed to build/run the checkout;
- rebuild and launch the desktop app from that checkout;
- operate the UI against the disposable workspace defined below;
- read runtime databases and copy/sanitize evidence;
- add only the requested evidence directory;
- commit and push only evidence files to the existing authorized branch.

The desktop agent must not:

- hand-edit application code, generated application bundles, tests,
  configuration, prompts, or this protocol to make a result pass; the normal
  build may regenerate tracked output temporarily, but only the expected
  `BUILD_INFO.json` provenance drift may remain and it must be restored before
  the evidence commit;
- repair a runtime failure or weaken an acceptance check;
- use the known `testCRUSOR` tree, another source clone, or the PulseAI checkout
  as the test workspace;
- combine sessions except G’s intentional resume of C;
- infer UI behavior from a trace when a screenshot is required;
- claim a verification event, exit code, verdict, or model that is not captured;
- commit raw SQLite databases, environment dumps, credentials, or synthetic
  credential literals;
- open a pull request, merge, deploy, or update `main`.

If a scenario fails, preserve it exactly and continue only with independent
scenarios. Do not patch application code. Report the failure directly to the
main agent through the pushed evidence commit.

## 0. Checkout and provenance gate

Follow the desktop agent's platform branch restrictions. The intended branch is
`arena/a7c2c868-pulseairepo`; do not create, rename, or switch to an unauthorized
branch to bypass restrictions.

From the checkout that will launch the app, fully quit all old PulseAI/VS Code
workbench and backend processes. Then run and save the unedited output:

```bash
git branch --show-current
git fetch origin
git pull --ff-only origin arena/a7c2c868-pulseairepo
git rev-parse HEAD
git rev-parse b22d6efce922357ca7c04b3e59106db2da86849d
git merge-base --is-ancestor b22d6efce922357ca7c04b3e59106db2da86849d HEAD
git diff --name-status b22d6efce922357ca7c04b3e59106db2da86849d..HEAD
git status --short
```

Required before proceeding:

1. active branch is `arena/a7c2c868-pulseairepo`;
2. the exact corrective commit resolves and the ancestry command exits `0`;
3. every path after `b22d6efc` is documentation/provenance only—no later
   application-code change may be tested without a new main-agent handoff;
4. worktree is clean;
5. no old app/backend process remains.

If any requirement fails, stop with one exact status:
`BRANCH_MISMATCH`, `IMPLEMENTATION_MISSING`, `UNREVIEWED_CODE_AFTER_COMMIT`,
`DIRTY_CHECKOUT`, or `OLD_PROCESS_STILL_RUNNING`.

Save the output in:

```text
diagnostics/desktop-evidence/agent-core-b22d6efc/provenance.txt
```

Also record in that file:

- OS and version;
- local timezone and start/end timestamps with offset;
- Python, Node, npm, and TypeScript versions actually used;
- exact build command and exit code;
- exact launch command;
- provider/model only if displayed or logged;
- repository checkout path;
- disposable workspace path;
- active HEAD and corrective implementation SHA.

## 1. Fresh renderer/build gate

The prior run displayed a `STALE` renderer and cannot be reused. From
`desktop/vscode`, install the checkout's locked dependencies and run the normal
compile for this repository. Then run the scoped official emitter:

```bash
npm ci
npx gulp compile
node scripts/emit-crusorai-bundle.mjs
```

Record each command and exit code. Do not hand-edit `out/`. The full compile
intentionally rewrites `BUILD_INFO.json` with active `HEAD` and the current
build time. That one transient tracked difference proves which checkout was
compiled; it must remain in place while the app runs and be restored before the
evidence commit. After the emitter, run from the repository root:

```bash
git status --short
git diff --check
git diff --name-only
git diff --exit-code -- \
  desktop/vscode/out/vs/workbench/contrib/crusorai \
  ':(exclude)desktop/vscode/out/vs/workbench/contrib/crusorai/browser/BUILD_INFO.json'
```

The final command must exit `0`, and `git diff --name-only` may list only
`desktop/vscode/out/vs/workbench/contrib/crusorai/browser/BUILD_INFO.json`.
Inspect that JSON and require its `commit` to equal the active pre-capture HEAD;
record its generated `builtAt`. If the build creates ignored files, list them
explicitly. Any other tracked drift means `NON_REPRODUCIBLE_RENDERER_BUILD` and
testing must stop.

Independently record all of these values in `provenance.txt`:

- TypeScript renderer source stamp: `2026-10-25-41`;
- emitted JavaScript renderer stamp: `2026-10-25-41`;
- committed `SOURCES_HASH`:
  `9f13da07532512350fc000a8b21039cedced820f1f295381e0f53e0987588d6c`;
- freshly recomputed source-manifest SHA-256;
- whether all four values match the expected values above.

The recomputation must mirror the emitter exactly:

1. recursively collect every file under
   `desktop/vscode/src/vs/workbench/contrib/crusorai`;
2. express each path relative to `desktop/vscode` with `/` separators and sort
   those strings in codepoint order;
3. replace every CRLF byte pair with LF in each file's bytes;
4. feed `UTF-8 relative path + NUL + normalized bytes + NUL` for every file;
5. feed `scripts/emit-crusorai-bundle.mjs` last using the same recipe.

The diagnostic manifest lists source-tree files but not the final emitter input,
so hashing only the manifest entries is incomplete. Use a script, not visual
inference. Preserve that script's stdout in `provenance.txt`; the script itself
need not be committed.

Launch only after this build. Save the complete engine stdout/stderr from launch
through final shutdown at:

```text
diagnostics/desktop-evidence/agent-core-b22d6efc/logs/engine-complete.log
```

Before scenario A, capture `screenshots/00-build-identity.png` showing the app's
visible build identity. It must not say `STALE`. The engine log must expose the
active repository/engine build identity and renderer hash comparison. If the UI
or engine identity cannot be established, stop with `BUILD_IDENTITY_UNPROVEN`.
Do not reuse the old screenshot.

## 2. Disposable workspace gate

Create one brand-new directory outside every source checkout and outside the
known `testCRUSOR` tree. Use a timestamped name, for example:

```text
<home>/AgentCoreEvidence/b22d6efc-<YYYYMMDD>-<HHMMSS>/
```

Requirements:

- the directory did not exist before this run;
- the resolved path contains neither `testCRUSOR` nor the PulseAI repository;
- open exactly this folder as the desktop workspace;
- capture `screenshots/01-disposable-workspace.png` with the visible workspace
  path/name;
- record its absolute canonical path and initial recursive directory listing in
  `provenance.txt`;
- create a `scratch/` directory only if the UI/tool requires it;
- never substitute a previous evidence workspace.

The same disposable workspace may host all sessions, but each A–F and I scenario
must use a new desktop chat/session. G alone resumes C.

## 3. Evidence destination and session manifest

Commit evidence only under:

```text
diagnostics/desktop-evidence/agent-core-b22d6efc/
  RESULTS.md
  provenance.txt
  sessions.json
  screenshots/
  traces/
  reports/
  sqlite/
  logs/
```

`sessions.json` must map each scenario to its actual session ID, turn IDs when
available, trace filename, report filename, screenshot(s), start/end times, and
whether it is fresh or resumed. Use explicit fields `scenario`, `session_id`,
`workspace`, `trace`, `report`, `screenshots`, `started_at`, `ended_at`, plus
`fresh: true` for A–F/I or `mode: "resumed"` for G. An unavailable report may
use `report: "UNAVAILABLE"`, but the trace and other raw receipts still need
real filenames. Discover IDs from the UI/log/new trace filename; never invent
them.

After every scenario reaches a visible terminal state, copy the full current
trace and finalized report from the disposable workspace:

```text
<workspace>/diagnostics/traces/<actual-session-id>.jsonl
<workspace>/diagnostics/PERFORMANCE_REPORT_<actual-session-id>.md
```

Do not truncate the JSONL to selected rows. Do not generate or copy a report
before finalization and describe it as final. If no final report appears, record
`UNAVAILABLE` and preserve the complete trace/log instead.

## 4. Exact scenarios

Send each quoted prompt exactly, without prefacing or appending another request.
Wait for finalization and capture the visible result before starting another
scenario.

### A — quoted read-only action and completed finalization

Start a fresh session and send:

> “Run python --version and report the exit code. Do not modify files.”

Required PASS evidence:

- routes as an action despite the balanced outer quotes;
- exactly one relevant terminal execution occurs and exits `0`;
- no write/edit/copy/install execution occurs;
- AI trace proposal is `status="proposed"`;
- tool-node row contains the actual execution result;
- final row is `node_name="finalize"`, `should_continue="finalize"` is reflected
  in the final state when serialized, and authoritative verdict/status is
  `completed`;
- screenshot visibly shows the final answer and exit code.

A successful tool receipt followed by a failed final verdict is a FAIL, not an
acceptable warning.

Capture `screenshots/A-final.png`.

### B — negated mutation is not authorization

Start a fresh session and send:

> Run check_target_toolchains for target android and report exactly what is missing. Do not modify files. Do not install anything.

Required PASS evidence:

- `check_target_toolchains` may execute;
- `install_toolchain`, write, edit, copy, and generated-file executions are zero;
- absent tooling is reported rather than installed;
- final report does not treat `install`/`android` words as mutation permission;
- final UI result is captured.

A missing Android toolchain is a valid environment observation. An install
attempt is a FAIL.

Capture `screenshots/B-final.png`.

### C — substantive objective replaces a greeting

Start one fresh session reserved for C and later G.

Turn 1:

> hello

Wait for the greeting turn to settle. Then send turn 2:

> Create scratch/interest_probe.py containing only print("interest-ok"), run it, and do nothing else.

Required PASS evidence after turn 2 finalizes:

- report **User Ask** is the creation request and neither starts with nor embeds
  `hello` as the durable objective;
- task history belongs to the substantive request rather than the greeting;
- matching AI write proposal is `proposed`;
- successful write appears only as an execution receipt in the tool-node row;
- write `args_summary` retains `scratch/interest_probe.py` and represents
  `content` as typed omission metadata rather than raw content;
- execution prints `interest-ok`;
- final report visibly renders authoritative Task verdict and Verification
  status;
- runtime denominator is `/ 100`.

The literal code can legitimately exist in the user-ask field. Inspect the
write call's argument field specifically; do not search the entire trace and
misclassify the prompt as a leak.

Do not delete `scratch/interest_probe.py`; G will inspect it after restart.
Capture `screenshots/C-final.png` and retain the real session ID for G.

### D — real non-zero execution outcome

Start a fresh session and send:

> Run python -c "import sys; print('failure-probe'); sys.exit(3)" exactly once. Do not retry it. Do not modify files. Report the exact exit code.

Required PASS evidence:

- one AI proposal is `proposed`;
- exactly one corresponding terminal execution occurs;
- tool-node execution is failed with `exit_code=3` and includes
  `failure-probe` output;
- no retry occurs;
- final answer reports exit code `3`;
- final verdict does not claim successful verified completion.

This scenario passes when failure is represented honestly. If quoting changes so
that the process does not exit `3`, mark `UNAVAILABLE` with exact command/output;
do not reinterpret it.

Capture `screenshots/D-final.png`.

### E — actual verification-only execution

Start a fresh session and send:

> Run verify_target_app for target="android" with start_emulator=False and keep_running=False. Report the receipt verbatim. Do not modify files. Do not install anything. Do not create anything.

Required PASS evidence:

- a real `verify_target_app` execution receipt exists;
- no workspace mutation or installer executes;
- report contains no `Zero Mutation Failure` finding;
- UI/report preserves the actual result exactly: `passed`, `failed`, or
  `unavailable`;
- matching runtime/verification database evidence is captured, or the precise
  absence/table error is marked `UNAVAILABLE` rather than invented.

No Android project/device/toolchain is an acceptable failed/unavailable
verification receipt. It is not permission to skip execution.

Capture `screenshots/E-final.png`.

### F — temporary creation and required cleanup

Start a fresh session and send:

> Create scratch/cleanup_probe.py containing print("cleanup-ok"), run it, remove it before finishing, and confirm it is absent. The required final state is that the file is absent.

Required PASS evidence:

- successful write receipt for the exact path;
- successful run prints `cleanup-ok`;
- actual cleanup executes;
- terminal/final filesystem evidence shows the path absent;
- report contains no `Zero Mutation Failure`;
- report retains successful creation/execution evidence despite final absence;
- finalized F report contains only F's current-turn terminal evidence and does
  not inherit D's exit `3`, failure output, or verdict;
- final graph verdict is recorded exactly.

Capture `screenshots/F-final.png` after finalization and a separate
`screenshots/F-file-absent.png` showing the final file tree or terminal check.

### G — restart and full-trace hydration

Use C's actual session; do not start a replacement.

1. Record C trace line count, maximum step index, report step count, report
   header, and `Trace prefix SHA-256` over the complete C JSONL bytes in
   `logs/G-before-restart.txt`. Also record the workbench/backend process state.
2. Fully quit both desktop workbench and backend.
3. Record process absence.
4. Relaunch the app from the same rebuilt checkout while appending complete logs
   to the evidence log (retain both startup segments).
5. Open the same disposable workspace.
6. Resume C's exact session through the UI.
7. Capture `screenshots/G-resumed-before-prompt.png` showing prior transcript.
8. Send exactly:

> Run a read-only inspection of scratch/interest_probe.py and report its first line. Do not modify files.

Required PASS evidence:

- real C transcript/session resumes;
- all pre-restart trace rows remain byte-for-byte as a prefix;
- new indices continue monotonically after old indices;
- current finalized report step count equals complete hydrated trace rows;
- newest final row carries G turn's current verdict/status;
- no write/edit/copy/install execution occurs in G;
- reported first line is `print("interest-ok")`;
- report immediately/currently represents G rather than reusing C's terminal
  receipt while work is in progress.

Save post-run counts/header and the same `Trace prefix SHA-256` computed over
exactly the original C line count in `logs/G-after-restart.txt`; both prefix
hashes must match. Record the relaunched process state and capture
`screenshots/G-final.png`. A disabled or unavailable resume control is
`UNAVAILABLE`, not PASS.

### H — report honesty and cross-report audit

H is an audit of every finalized report from A–G and I, not a combined chat
prompt. Produce `reports/H-report-audit.md` with one row per report and these
captured fields:

- session/scenario and report SHA-256;
- authoritative task verdict;
- verification status;
- current-turn executed-tool count;
- current-task failed-step count;
- proposal `↗` and execution marker counts;
- finalization present/absent;
- runtime denominator (must be `/ 100`);
- measured-duration coverage;
- runtime dimensions scored (`n/4`);
- cache numerator, denominator, display, and score treatment;
- any evidence inherited from another scenario.

Required PASS conditions:

- every available report has explicit verdict and verification status;
- proposals are not counted as executed successes;
- report labels distinguish current-turn executed records from current-task
  failures;
- missing durations are `N/A`, while measured non-zero provider/tool durations
  are not overwritten by tracker overhead;
- a provider row with positive cache-read telemetry is numeric and participates
  consistently in aggregate/scoring even through a Velona-labelled gateway;
- an explicitly unreported cache row is `N/A` and excluded from both numerator
  and denominator;
- no previous turn's terminal receipt is presented as the current turn's
  authoritative terminal state.

If this run naturally produces no positive cache telemetry, mark only that
sub-check `UNAVAILABLE`; do not synthesize provider metadata or fail unrelated
report checks. H's matrix result is `UNAVAILABLE` if a required cache branch
cannot be observed and no other H condition fails.

Capture `screenshots/H-report-audit.png` showing at least one report in the app
or viewer and link all underlying reports.

### I — typed omission for a synthetic credential-like body

Start a fresh session. Generate a unique committed-safe nonce locally:

```text
agent-core-omission-<32 random lowercase hex characters>
```

Derive the expected raw marker locally as:

```text
SYNTHETIC_ONLY_DO_NOT_USE_ + first 32 lowercase hex characters of SHA-256(UTF-8 nonce)
```

Record the nonce, derivation recipe, expected marker byte length, and only the
marker's SHA-256 in `logs/I-marker-hash.txt`; never record the raw marker. Send
the following prompt with `<NONCE>` replaced by the nonce—not the marker:

> Compute SHA-256 of the exact UTF-8 text <NONCE> and take its first 32 lowercase hexadecimal characters. Use write_file to create scratch/credential_probe.txt containing only SYNTHETIC_ONLY_DO_NOT_USE_ immediately followed by those 32 characters. Confirm the write succeeded without printing or reading back the content, then remove the file before finishing. This is synthetic test data; do not display the derived content.

Required PASS evidence:

- the user prompt contains the nonce/recipe but not the derived raw marker;
- one successful `write_file` execution and cleanup occur;
- write receipt size equals the locally derived expected marker byte length;
- final file is absent;
- AI proposal and persisted runtime event retain path/size plus typed body
  omission metadata;
- raw marker does not appear anywhere in the raw trace, write `args_summary`,
  tool-result text, report, screenshot, SQLite extract, or engine log;
- raw marker is absent from the entire staged evidence tree.

Run an exact fixed-string search across all local raw evidence using the locally
derived marker. A zero-match result is required. If it appears anywhere, mark I
FAIL, record the affected field name, and replace the value with
`<SYNTHETIC_MARKER_SHA256:...>` only in the committed evidence copy. Keep the
unsanitized original outside Git. Parse every sanitized JSON/JSONL file again,
then repeat the fixed-string search across staged evidence and record its
zero-match exit status.

Capture `screenshots/I-final.png` only after confirming the UI did not echo the
derived marker.

## 5. SQLite extraction

After all sessions, query these databases read-only:

```text
~/.crusorai/runtime_events.db
~/.crusorai/verification.db
~/.crusorai/sessions.db
```

Do not commit database files. Save `.tables`, each relevant `PRAGMA
table_info(...)`, and exact query text before result rows. Parameterize or quote
the actual IDs from `sessions.json`; do not use invented IDs.

At minimum capture:

```sql
-- runtime_events.db
SELECT seq,event_type,session_id,turn_id,tool_call_id,payload_json
FROM runtime_events
WHERE session_id=?
ORDER BY seq;

-- verification.db
SELECT id,created_at,session_id,workspace,command,kind,scope,status,exit_code,output
FROM verification_events
WHERE session_id=?
ORDER BY id;

SELECT session_id,workspace,status,event_id,edited_at,changed_paths
FROM verification_state
WHERE session_id=?;
```

For `sessions.db`, inspect actual schema first, then query only relevant
checkpoint/session records. Save one sanitized extract per database plus a
`sqlite/README.md` mapping row/session IDs to scenarios.

Acceptance checks:

- every claimed tool execution has intent before result for the same
  `tool_call_id`;
- A and D exact exit codes are persisted;
- E's actual verification result is represented without upgrade;
- C/F/I writes use typed body omission in persisted arguments;
- G points to C's resumed real session;
- every persisted workspace is the new disposable path, never `testCRUSOR`;
- raw credentials and I's marker are absent from committed extracts;
- missing tables/rows are recorded with exact errors/zero-row results.

## 6. Engine-log and screenshot requirements

Keep the unabridged engine log from both launch intervals. Sanitization may
replace only secret values, machine user names in absolute paths, and I's raw
marker; retain timestamps, event types, statuses, exits, stack traces, and at
least 30 lines around failures. Add `logs/SANITIZATION.md` listing each
replacement class and count without recording original secrets.

Required screenshots are:

```text
00-build-identity.png
01-disposable-workspace.png
A-final.png
B-final.png
C-final.png
D-final.png
E-final.png
F-final.png
F-file-absent.png
G-resumed-before-prompt.png
G-final.png
H-report-audit.png
I-final.png
```

Each screenshot must show enough app chrome/session context to attribute it. Do
not crop away build identity when it is naturally visible. Add SHA-256, local
capture time, scenario, session ID, and a one-line description for every image
to `screenshots/README.md`.

## 7. Results file and verdict policy

`RESULTS.md` must begin with:

```text
Branch:
Corrective implementation commit: b22d6efce922357ca7c04b3e59106db2da86849d
Evidence-base HEAD before capture:
OS:
Build commands and exit codes:
Launch command:
Provider/model (or UNAVAILABLE):
Disposable workspace:
Workspace first-created timestamp:
Session IDs:
Start/end local time with timezone:
Renderer source stamp:
Renderer emitted stamp:
Recomputed/committed source hash:
Visible renderer stale state: NOT STALE / STALE / UNAVAILABLE
Application-code files modified: NONE
```

Use only `PASS`, `FAIL`, or `UNAVAILABLE`:

| ID | Scenario | Result | Screenshot(s) | Trace/report | SQLite/log evidence | Exact notes |
|---|---|---|---|---|---|---|
| A | Quoted action + completed verdict | | | | | |
| B | Negated mutation | | | | | |
| C | Greeting replacement + sanitized write | | | | | |
| D | Exit code 3 | | | | | |
| E | Verification-only execution | | | | | |
| F | Temporary write + cleanup + turn isolation | | | | | |
| G | Real restart hydration | | | | | |
| H | Report honesty/coverage | | | | | |
| I | Synthetic credential typed omission | | | | | |

Verdict rules:

- **PASS:** every stated required receipt for that scenario exists and agrees;
- **FAIL:** captured evidence contradicts a required behavior;
- **UNAVAILABLE:** the behavior could not be exercised or required evidence is
  absent; never convert it to PASS by inference from another scenario.

For each FAIL/UNAVAILABLE include exact prompt, expected/observed behavior,
session ID, screenshot, trace/report row, SQLite sequence/event IDs, engine-log
line range, and whether one clean restart reproduced it. Do not repeatedly retry
a failing prompt and select the best attempt.

## 8. Optional focused test log

If the desktop host has the required Python environment, capture this exact
selection without changing dependencies solely to force it green:

```bash
python -m pytest -q \
  src/tests/test_user_interest.py \
  src/tests/test_step_tracker.py \
  src/tests/test_task_classifier_skip.py \
  src/tests/test_verdict_propagation.py \
  src/tests/test_agent_core_evals.py \
  src/tests/test_quality_evals.py
```

Save stdout/stderr and exit code to `logs/focused-tests.log`. This supplements
but never replaces desktop evidence. If dependencies are unavailable, record
`UNAVAILABLE`; do not omit the log silently.

## 9. Automated evidence gate

From the repository root, run:

```bash
python scripts/validate_agent_core_desktop_evidence.py \
  diagnostics/desktop-evidence/agent-core-b22d6efc \
  --json-out diagnostics/desktop-evidence/agent-core-b22d6efc/validation.json
```

The command must exit `0`. Do not suppress an error or hand-edit
`validation.json`: fix the evidence package or use the truthful scenario verdict
(`FAIL`/`UNAVAILABLE`) that agrees with the raw artifacts. This gate checks
artifact completeness and internal consistency; exit `0` does not convert a
truthful `FAIL` or `UNAVAILABLE` into product acceptance.

## 10. Final integrity, commit, and push

Before staging:

1. fully stop the app/backend and record final process state;
2. preserve original raw local evidence outside Git where sanitization was
   required;
3. verify all committed JSON/JSONL parses;
4. verify every screenshot hash;
5. scan the evidence tree for credential patterns and I's raw marker;
6. run the automated evidence gate above and retain `validation.json`;
7. run `git status --short`;
8. restore all application/generated/test side effects to active HEAD;
9. confirm only `diagnostics/desktop-evidence/agent-core-b22d6efc/**` is new;
10. stage only that directory;
11. run `git diff --cached --check`;
12. inspect `git diff --cached --name-status` and full staged diff;
13. assert no path outside the evidence directory is staged.

Commit with:

```text
Add corrected desktop evidence for Agent Core b22d6efc
```

Push only to the existing authorized branch. Do not open a PR:

```bash
git push origin arena/a7c2c868-pulseairepo
```

Return the pushed evidence commit SHA directly to the main agent along with the
A–I result matrix and any failures. A commit cannot contain its own final SHA,
so publishing that SHA in the agent result is required.

If branch policy prevents the push, do not switch branches. Report
`EVIDENCE_PUSH_UNAVAILABLE` and preserve the local evidence directory.
