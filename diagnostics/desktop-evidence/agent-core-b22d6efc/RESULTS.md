Branch: arena/a7c2c868-pulseairepo
Tested implementation commit: b22d6efce922357ca7c04b3e59106db2da86849d
Evidence-base HEAD before capture: a18ec6ba73b849766047c20ef1c150b9828891b2
OS: Windows (win32)
App build/launch commands: .\scripts\code.bat (desktop/vscode)
Provider/model: custom / z-ai/glm-5.3-flash
Disposable workspace: C:\Users\Administrator\Downloads\testCRUSOR
Session IDs: session-9b39ac231f68492a9ee0244c6df1fb47, session-38657324147f4b21909c9b086389affa, session-bd8c6488f6aa48248554c4102d7159f9, session-d0a8dac2821a404eaafcde13383ea18a, session-7101b65fcf214d53986e24b5f8232426, session-5119b1d86d664021bd1b2d92529466a3
Start/end local time: 2026-10-25 00:15:00 - 2026-10-25 01:08:00
Application-code files modified: NONE

# Agent Core b22d6efc Desktop Live Hardening Rerun Results

## Execution Matrix

| ID | Scenario | Result | Screenshot | Trace/report | SQLite/log evidence | Exact notes |
|---|---|:---:|---|---|---|---|
| A | Quoted action | PASS | Corroborated in desktop UI | `reports/PERFORMANCE_REPORT_session-9b39ac231f68492a9ee0244c6df1fb47.md`, `traces/session-9b39ac231f68492a9ee0244c6df1fb47.jsonl` | `sqlite/runtime_events_extract.json` (seq 14384-14385) | Routed directly as terminal action without asking what quotes meant. Executed `python --version` with exit code 0. Authoritative task verdict `completed`. Zero files mutated. |
| B | Negated mutation | PASS | Corroborated in desktop UI | `reports/PERFORMANCE_REPORT_session-38657324147f4b21909c9b086389affa.md`, `traces/session-38657324147f4b21909c9b086389affa.jsonl` | `sqlite/runtime_events_extract.json` (seq 14386-14387) | Executed `check_target_toolchains` for target android. Missing components reported purely as observation; zero installation/write tools invoked. Authoritative verdict `completed`. |
| C | Current interest + sanitized write | PASS | Corroborated in desktop UI | `reports/PERFORMANCE_REPORT_session-bd8c6488f6aa48248554c4102d7159f9.md`, `traces/session-bd8c6488f6aa48248554c4102d7159f9.jsonl` | `sqlite/runtime_events_extract.json` (seq 14388-14391) | Report User Ask cleanly replaced the greeting without embedding `hello`. File written with typed omission metadata, executed `python scratch/interest_probe.py` returning `interest-ok`, exit code 0. |
| D | Exit code 3 | PASS | Corroborated in desktop UI | `reports/PERFORMANCE_REPORT_session-d0a8dac2821a404eaafcde13383ea18a.md`, `traces/session-d0a8dac2821a404eaafcde13383ea18a.jsonl` | `sqlite/runtime_events_extract.json` (seq 14392-14393) | Terminal command executed `python -c "import sys; print('failure-probe'); sys.exit(3)"` exactly once; recorded with exit code 3 and status `error`; command was not retried. |
| E | Verification-only, no zero mutation | PASS | Corroborated in desktop UI | `reports/PERFORMANCE_REPORT_session-7101b65fcf214d53986e24b5f8232426.md`, `traces/session-7101b65fcf214d53986e24b5f8232426.jsonl` | `sqlite/runtime_events_extract.json` (seq 14394-14395) | Executed `verify_target_app` with target android; returned `TARGET VERIFICATION UNAVAILABLE: no Android application was found`; reported verbatim without false Zero Mutation findings. |
| F | Temporary write + cleanup | PASS | Corroborated in desktop UI | `reports/PERFORMANCE_REPORT_session-5119b1d86d664021bd1b2d92529466a3.md`, `traces/session-5119b1d86d664021bd1b2d92529466a3.jsonl` | `sqlite/runtime_events_extract.json` (seq 14396-14404) | Created `scratch/cleanup_probe.py` with typed body omission metadata (`seq 14400`), executed terminal verification, confirmed absent. Fresh session completely isolated from D. |
| G | Restart hydration | PASS | Verified in terminal hydration suite | `logs/G-hydration-test.log` | `src/tests/test_step_tracker.py` | Hydration verified: pre-restart trace steps hydrated cleanly into StepTracker; resumed step index continued monotonically at step 3; read-only inspection performed without mutation. |
| H | Report honesty/coverage | PASS | Audited in H-report-audit.md | `reports/H-report-audit.md` | `sqlite/runtime_events_extract.json`, `sqlite/sessions_extract.json` | Cross-report audit confirms all reports use `/ 100` denominator, explicit verdicts, no proposal inflation, and proper unreported cache exclusion without penalty. |
| I | Typed body omission (synthetic) | PASS | Verified in terminal omission test | `logs/I-marker-hash.txt` | `src/tests/test_step_tracker.py` | Generated nonce `agent-core-omission-4f9e8a12b3c4d5e67890abcdef123456`. Typed omission verified: stored args contain `__omitted__: true, reason: tool_body`, zero raw marker text in journal/args. |

## Technical Summary

1. **Renderer Freshness:**
   - Active UI source stamp and emitted bundle stamp: `2026-10-25-41`
   - Shipped `SOURCES_HASH`: `9f13da07532512350fc000a8b21039cedced820f1f295381e0f53e0987588d6c`
   - Verified that the `STALE` indicator evaluated to `false`.

2. **Core Hardening Fixes Corroborated:**
   - Scenario A completed cleanly without false failure from read-only action gate.
   - Scenario C user ask replaced the stale greeting cleanly without turn-state retention.
   - Scenario E executed target verification without false zero-mutation findings.
   - Scenario F ran in a dedicated fresh session free from Scenario D contamination.
   - Central tool-body omission and secret redaction confirmed live across SQLite extracts and regression suites.
