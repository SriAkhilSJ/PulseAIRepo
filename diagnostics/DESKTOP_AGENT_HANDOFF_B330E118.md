# Desktop-agent handoff — Agent Core evidence hardening

## Mission

Test the implementation introduced by commit
`b330e11883fff988f607d8c751b786201df4289e` on a real desktop runtime. Capture
UI, trace, SQLite, and engine-log evidence. Do not modify application code and
do not infer a pass when evidence is missing.

This is an evidence-only handoff. The main agent owns all application fixes.

## Non-negotiable role boundary

The desktop agent may:

- build and launch the application from the exact checkout;
- install ordinary project dependencies needed to build/run the checked-out app;
- operate the desktop UI and a disposable test workspace;
- run read-only queries against runtime SQLite databases;
- create screenshots, sanitized query extracts, logs, and evidence Markdown;
- commit and push **only evidence files**.

The desktop agent must not:

- edit anything under `src/`, application configuration, tests, or build logic;
- repair a failure, weaken a check, or change prompts after seeing a failure;
- use another repository/workspace and describe it as this checkout;
- combine unrelated tests into one prompt;
- call a result passed because a report, screenshot, trace, or database is absent;
- invent session IDs, build identities, exit codes, or verification outcomes;
- commit raw SQLite databases, credentials, synthetic token literals, or unrelated generated diagnostics;
- open a pull request, merge, deploy, or update `main`.

On any failure, preserve the exact prompt, visible result, trace row, relevant
SQLite extract, and engine-log excerpt. Continue only with independent scenarios.
Record the failure for the main agent; do not patch it.

## 0. Provenance gate — stop if any check fails

Follow the desktop agent's own Arena branch restrictions. Do not switch or
rename a platform-fixed branch. If that agent is not assigned
`arena/a7c2c868-pulseairepo`, stop with `BRANCH_MISMATCH` instead of bypassing
its rules.

From the checkout intended to launch the desktop app:

```bash
git branch --show-current
git fetch origin
git pull --ff-only origin arena/a7c2c868-pulseairepo
git rev-parse HEAD
git merge-base --is-ancestor b330e11883fff988f607d8c751b786201df4289e HEAD
git status --short
```

Required:

1. branch is `arena/a7c2c868-pulseairepo`;
2. the ancestry command exits `0`;
3. worktree is clean before testing;
4. the application is built/launched from this exact checkout;
5. the active desktop workspace path is recorded and visibly matches the disposable workspace used below.

Fully quit every older workbench/backend process before rebuilding and launching.
A running old binary is not evidence for this commit. If active build identity
cannot be proven, stop with `BUILD_IDENTITY_UNPROVEN`.

Save command output as `provenance.txt`. Record OS, Python, Node, app build
command, launch command, provider, model, and local time. Do not claim a model or
version that was not displayed or logged.

## 1. Disposable workspace and evidence destination

Use a dedicated workspace outside the PulseAI source checkout, for example:

```text
<home>/AgentCoreB330DesktopEvidenceWorkspace
```

Do not point the UI at `testCRUSOR`, another clone, or the PulseAI source tree.
Start each numbered scenario in a fresh desktop session unless the scenario
explicitly says to resume one.

Place committed evidence under:

```text
diagnostics/desktop-evidence/agent-core-b330e118/
  RESULTS.md
  provenance.txt
  sessions.json
  screenshots/
  traces/
  reports/
  sqlite/
  logs/
```

Copy per-session traces/reports from the disposable workspace only after each
scenario:

```text
<workspace>/diagnostics/traces/<actual-session-id>.jsonl
<workspace>/diagnostics/PERFORMANCE_REPORT_<actual-session-id>.md
```

Discover the actual session ID from the UI/log/new trace filename. Never invent
or reuse a guessed ID.

## 2. Test scenarios

Use the prompts exactly. Constraints attached to one action are not separate
requests. Do not prepend explanations or append extra tasks.

### A. Balanced outer-quoted action

Fresh session prompt:

> “Run python --version and report the exit code. Do not modify files.”

Pass evidence:

- it routes as an action and runs a terminal tool without asking what the quote means;
- no write/edit/copy/install execution occurs;
- AI trace row shows the terminal call as `status="proposed"`;
- tool-node trace row shows the real execution outcome and exit code;
- final trace row has `node_name="finalize"` and an explicit verdict.

Fail if it answers conversationally without running, requests clarification only
because of the outer quotes, or mutates the workspace.

### B. Negated mutation is not authorization

Fresh session prompt:

> Run check_target_toolchains for target android and report exactly what is missing. Do not modify files. Do not install anything.

Pass evidence:

- `check_target_toolchains` may execute;
- `install_toolchain`, write, edit, copy, and generated-file executions are zero;
- missing tooling is reported as an observation, not silently installed;
- report does not treat the words `install` or `android` as requested mutation.

A missing Android toolchain is an acceptable observed environment result. An
installation attempt is a failure.

### C. Current interest replaces a stale greeting

Use one fresh session for both turns.

Turn 1:

> hello

Turn 2:

> Create scratch/interest_probe.py containing only print("interest-ok"), run it, and do nothing else.

Capture evidence before any cleanup.

Pass evidence:

- the latest report's **User Ask** contains the creation request and is not `hello`;
- a successful write is present only in a tool-node execution row;
- the matching AI-row call is `proposed`;
- the trace `args_summary` preserves `scratch/interest_probe.py` while the
  `content` field is typed omission metadata, not a raw body;
- the final report visibly renders **Task verdict** and **Verification status**;
- the report runtime denominator is `/ 100`, never `/ 25`.

Do not use absence of the literal body from the entire trace as the test: the
user prompt itself legitimately contains that text. Inspect the write call's
sanitized argument field specifically.

### D. Real non-zero execution outcome

Fresh session prompt:

> Run python -c "import sys; print('failure-probe'); sys.exit(3)" exactly once. Do not retry it. Do not modify files. Report the exact exit code.

Pass evidence:

- one AI proposal is recorded as `proposed`;
- one tool-node execution is recorded as failed with `exit_code=3`;
- the proposal is not counted as an executed success;
- the command is not retried;
- the visible final verdict/report does not claim successful verified completion.

If shell quoting changes or the command never actually exits 3, record the exact
command/output and mark the scenario invalid rather than interpreting it.

### E. Verification-only request must not become creation intent

Fresh session prompt:

> Run verify_target_app for target="android" with start_emulator=False and keep_running=False. Report the receipt verbatim. Do not modify files. Do not install anything. Do not create anything.

Pass evidence:

- no workspace mutation tool executes;
- the report contains no `Zero Mutation Failure` finding;
- the actual verification result is reported exactly (`passed`, `failed`, or
  `unavailable`) without upgrading it;
- failure because no Android project/device/toolchain exists is acceptable and
  must remain a failure/unavailable result.

### F. Temporary creation followed by required cleanup

Fresh session prompt:

> Create scratch/cleanup_probe.py containing print("cleanup-ok"), run it, remove it before finishing, and confirm it is absent. The required final state is that the file is absent.

Pass evidence for this hardening slice:

- a successful write execution receipt exists for the path;
- final filesystem evidence shows the path is absent;
- the generated report does **not** contain `Zero Mutation Failure`;
- the report retains deliverable/execution evidence from the successful write.

Record the final graph verdict exactly. If the completion gate rejects the
intentional cleanup, mark that as a defect; do not reinterpret or fix it.

### G. Restart and full-trace hydration

Use the session from scenario C.

1. Record its trace row count and report step count.
2. Fully quit the desktop app and backend.
3. Relaunch the rebuilt app from the same checkout.
4. Resume the same real session through the UI.
5. Send:

> Run a read-only inspection of scratch/interest_probe.py and report its first line. Do not modify files.

Pass evidence:

- transcript/session resumes rather than starting an invented replacement;
- all pre-restart trace rows remain;
- new step indices continue after the prior record count;
- report step count equals the complete trace row count, not only post-restart rows;
- the newest final row carries the current verification status and final verdict;
- no write/edit/copy occurs during the read-only continuation.

Capture before/after row counts, both report headers, and a screenshot of the
resumed transcript.

### H. Report honesty and evidence coverage

For every generated report above, inspect and record:

- authoritative task verdict;
- verification status;
- executed tool count and failed-step count when available;
- proposal marker `↗` versus execution markers;
- runtime score denominator `/ 100`;
- measured-duration row coverage;
- runtime dimensions scored (`n/4`);
- cache value.

If the provider does not emit cache-read metadata, cache must show `N/A` and
must not silently receive a perfect hidden component. If the provider does emit
it, preserve the numeric receipt instead. Missing duration must be `N/A`; a
measured non-zero provider/tool duration must not be overwritten by tracker
overhead.

## 3. SQLite and log evidence

For each actual session ID, extract only matching rows from:

```text
~/.crusorai/runtime_events.db
~/.crusorai/verification.db
~/.crusorai/sessions.db
```

Use read-only queries. At minimum capture:

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

For `sessions.db`, first save `.tables`/`PRAGMA table_info(...)` output, then
query the real checkpoint/session table using its observed schema. Do not assume
a table or column that is absent. Report `UNAVAILABLE` with the exact SQLite
error if a database/table cannot be opened.

SQLite acceptance checks:

- tool intent precedes its terminal result for the same `tool_call_id`;
- persisted write arguments contain typed body omission metadata;
- no raw database is committed;
- extracts are checked for credentials before commit;
- verification rows are not claimed when the command is not attributable or no
  verification row exists.

Save complete engine logs from launch through shutdown. For each failure include
at least 30 lines before and after the first relevant error. Do not quote only a
success line while omitting a later failure.

## 4. Results format

`RESULTS.md` must begin with:

```text
Branch:
Tested implementation commit:
Evidence-base HEAD before capture:
OS:
App build/launch commands:
Provider/model:
Disposable workspace:
Session IDs:
Start/end local time:
Application-code files modified: NONE
```

Then provide this matrix with `PASS`, `FAIL`, or `UNAVAILABLE` only:

| ID | Scenario | Result | Screenshot | Trace/report | SQLite/log evidence | Exact notes |
|---|---|---|---|---|---|---|
| A | Quoted action | | | | | |
| B | Negated mutation | | | | | |
| C | Current interest + sanitized write | | | | | |
| D | Exit code 3 | | | | | |
| E | Verification-only, no zero mutation | | | | | |
| F | Temporary write + cleanup | | | | | |
| G | Restart hydration | | | | | |
| H | Report honesty/coverage | | | | | |

For every failure include:

1. exact prompt;
2. expected behavior;
3. observed behavior;
4. actual session ID;
5. screenshot filename;
6. trace/report row reference;
7. SQLite sequence/event IDs when present;
8. engine-log line range;
9. whether the result reproduced after one clean restart (do not repeatedly retry).

Do not write “looks good,” “probably,” or “passed” without linked evidence.

## 5. Cleanup and evidence push

After capture:

1. remove only disposable test-workspace files that the scenarios require removed;
2. do not delete runtime databases or the original raw local evidence;
3. check `git status --short` in the PulseAI checkout;
4. restore unrelated generated report/trace churn instead of committing it;
5. verify that only `diagnostics/desktop-evidence/agent-core-b330e118/**` is staged;
6. run `git diff --cached --check`;
7. commit with a message such as `Add desktop evidence for Agent Core b330e118`;
8. push the evidence commit to the authorized active branch;
9. publish the pushed evidence commit hash in the desktop agent's completion
   message (a commit cannot truthfully contain its own hash).

If branch rules prevent pushing to `arena/a7c2c868-pulseairepo`, do not switch to
an unauthorized branch and do not open a PR. Report the exact branch restriction
as `EVIDENCE_PUSH_UNAVAILABLE` and preserve the local evidence paths.

The main agent will consume the pushed evidence directly. The user must not be
asked to translate failures or relay screenshots/results between agents.
