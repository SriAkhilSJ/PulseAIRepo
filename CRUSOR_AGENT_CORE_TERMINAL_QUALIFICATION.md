# Real-Provider Terminal Qualification — Results

**Date:** 2026-11-12
**Provider:** `custom` / `z-ai/glm-5.3-flash` (`https://velona.in/v1`)
**Harness:** `%TEMP%\CrusorLiveE2E\backend_qual.py` → `stream_agent(..., canonical_runtime=True)`, approval policy `workspace_session`, one thread for A/B/C.
**Fixture:** `mini_math` (add/subtract/multiply, 9 passing tests).
**Spend:** ₹0.4207 total (UI attempt ₹0.2392 + terminal ₹0.1815) against the ₹50 cap. No paid call exceeded the cap; no retries in the engineering dispatches.

## Results

| Test | Requests | In / Out | Latency | Cost ₹ | Files changed | Suite | Verdict |
|---|---:|---|---:|---:|---:|---|---|
| A — `divide()` | 1 | 3,061 / 169 | 3.24 s | 0.0173 | 0 | 9 pass (unchanged) | **FAILED** |
| B — `clamp()` | 3 | 9,668 / 3,669 | 1.7 / 16.4 / 26.9 s | 0.1125 | 0 | 9 pass (unchanged) | **FAILED** |
| C — repair `multiply()` | 1 | 3,200 / 1,990 | 9.71 s | 0.0516 | 0 | 4 fail → 4 fail | **BLOCKED** |

Terminal-only: **5 requests, 15,929 input, 5,828 output, ₹0.1815**.

Ledger rows (all `settled`, real tokens, measured latency):

```
inv-77270a27585f427d  node_task_tests_test_ops      3061/169   3242 ms  ₹0.0173
inv-c8a6dc8389dc4c43  node_task_req_001_module      3245/122   1737 ms  ₹0.0172
inv-af4678ac14e44789  node_task_req_003_module      3327/188  16381 ms  ₹0.0189  (15 cached)
inv-55861437cae84d67  node_task_tests_test_ops      3096/3359 26905 ms  ₹0.0765
inv-6247e036e4b64c2f  node_task_main                3200/1990  9709 ms  ₹0.0516
```

## What passed

- Authentication and dispatch through the configured provider.
- Real usage extraction (provider-reported tokens; zero fabricated usage).
- FinOps reserve→settle on every call; uncertain path not exercised.
- Measured `latency_ms` now present (the defect fixed in this pass).
- `turn_id` correct (`turn-A/B/C`); invocation identity consistent.
- Honest terminal outcomes: `FAILED`, `FAILED`, `BLOCKED` — nothing claimed success.

## What failed

1. **Test A** planned only `task_tests_test_ops` (no source node). The reply was rejected by `extract_generated_source`: *"Malformed Markdown code fence in model output for 'tests/test_ops.py'"*. Fail-closed is correct; no bounded recovery ran.
2. **Test B** created `src/req_001_module.py`, `src/req_003_module.py`, `tests/test_req_001_module.py` — requirement-ID-named targets — instead of editing `mini_math`. The plan reported 4/4 completed; the delivery verdict was `FAILED`.
3. **Test C** planned one `task_main` node and returned `BLOCKED`; it never ran the failing tests, so it could not diagnose or repair. The injected regression remains (4 failing).
4. **No tool calls** occur on the engineering path. The planner guesses targets from requirement IDs; it never lists, reads or searches the workspace.

## Root cause

`ModelExecutionAdapter`/`EngineeringExecutionOrchestrator` bind no tools. The chat path binds tools (`chat_graph.py:2322,2675,2786`); the engineering path only generates file bodies and routes the final content through the mutation broker. "Understand → inspect → plan → act → observe → repair" cannot occur without inspection or test execution.

## Phase 2 scope (next, not implemented)

1. Bind a bounded read-only tool set (list/read/search) before planning; feed discovered files into `_requested_files`/planner.
2. Persist the discovered package layout into the contract so targets are real paths, not `req_*_module.py`.
3. Add one bounded fence/format recovery on `SourceExtractionError` (re-prompt once with the failure, metered separately).
4. Give the orchestrator a bounded test-diagnose-repair loop using the existing verification evidence, still through the broker and approval gateway.
5. Keep `EngineeringExecutionOrchestrator` as the owner; no second lifecycle.

## Git status

```
HEAD:        fb5bd528 (no commit/reset/clean/checkout)
dirty:       247 entries; 173 untracked; 0 deletions
changed:     src/orchestration/model_adapter.py (latency_ms)
             CRUSOR_AGENT_CORE_ENGINEERING_QUALIFICATION.md
             CRUSOR_AGENT_CORE_TERMINAL_QUALIFICATION.md (this file)
```
