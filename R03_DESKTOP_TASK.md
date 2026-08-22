# R0.3 - optimized build proof + CDP acceptance (desktop agent lane)

This is the **desktop agent's** task. It modifies **no repository code**. It
performs a build, verifies it, and runs CDP acceptance against a real Electron
instance. Evidence files (logs, screenshots, traces) stay in `D:\pulse-res\...`
and are **never committed**.

Do not touch engine/benchmark files; they belong to the remote agent's lane.

## Prerequisites

- Local repo at merged `main`: `1e8a306` (PR #2) .. latest (PR #3 merged).
  `git fetch origin && git switch main && git merge --ff-only origin/main`.
- Do **not** push anything. If a fix is genuinely needed in contribution code,
  report it - do not commit without separate approval.

## Acceptance criteria (all must pass; capture evidence for each)

1. **Optimized build from merged main**
   - Optimized desktop build succeeds (`yarn gulp vscode-win32-x64` or the
     exact equivalent used previously; record the command).
   - Worker bundle exists at the expected optimized path
     (`out/vs/workbench/contrib/pulseai/node/pulseAIWorkerMain.js` in the
     optimized output).
   - Literal launch log contains:
     `moduleId: vs/workbench/contrib/pulseai/node/pulseAIWorkerMain`
   - Confirm the worker module id literal in source + build configs:
     `pulseAIWorkerService.ts`, `buildfile.ts`, `build/next/index.ts`.

2. **Protocol v2 reaches `Pulse ready`**
   - Bridge + worker start; protocol v2 handshake completes; UI shows the
     ready state. Record the relevant log lines.

3. **Real non-echo tiny turn completes**
   - A tiny prompt returns a real provider response (not an echo).
   - Record: prompt text, first-token time, completion time, terminal type.

4. **Large-workspace turn degrades safely**
   - Open a generated 20k-entry workspace (generated externally by the
     benchmark fixture generator - do NOT generate inside the repo).
   - Turn completes with a bounded-context/degradation receipt; UI stays
     responsive. Record the receipt fields.

5. **Cancellation passes (target < 2 s to terminal)**
   - Prompt `sleep 20`, poll at 100 ms, click Stop.
   - Capture per trial: ack latency, protocol terminal latency, DOM terminal
     latency. Three fresh trials on the same build. Expected: all under 2 s.
   - Post-Stop counters all zero: requests_started_after_stop,
     retries_started_after_stop, failovers_started_after_stop,
     tool_starts_after_stop, mutations_after_stop.

6. **Shutdown leaves zero owned processes**
   - After closing the app: 0 `PulseAI.exe` processes, 0 bridge processes
     (`python -m src.bridge`), ports 5999 and 9222 free.
   - Record `Get-CimInstance Win32_Process` filtered output + `Get-NetTCPConnection
     -State Listen | Where-Object LocalPort -in 5999,9222` -> no entries.

7. **Fresh dark-theme screenshots** (this build only; save, do not commit).

## Evidence layout (save under `D:\pulse-res\r03-<timestamp>\`)

```
build.log                     - build command + result
launch.log                    - moduleId literal + Pulse ready + protocol v2 lines
turn-tiny.log / turn-large.log
cancel-trials.csv or .md       - three trials, latencies, counters
shutdown.txt                  - process/port check output
provenance.txt                - blob hashes of src/bridge/__main__.py, chat_graph.py,
                                llm/factory.py, runtime/turn_control.py vs git rev-parse HEAD:
```

## Report format (back to founder)

```
R0.3 PASS/FAIL per criterion (1-7), exact numbers, evidence dir path,
git status (must show no changes), and any deviation with justification.
```

## Hard rules

- No code edits, no commits, no pushes without explicit approval.
- No screenshots/logs/traces in Git; no cloning of shared research space.
- Pre-existing test failures (WinError 5 on `D:\`, env-limits) must be
  reported as environmental, never hidden or 'fixed' by touching code.
