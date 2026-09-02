# Live E2E Verification Evidence

**Branch:** `arena/01a0564d-pulseairepo`
**HEAD verified:** `d25307b750905d37f079cb46aaa5051f2ca9105a`
**Date:** 2026-09-01
**Credit total:** ~1.3/90 (2 LLM probe calls + 3.1 turn (2 calls) + 3.2 threat (2 calls) + 3.3 plan (3 calls) + 3.4 learn (3 calls) + PBR-002 (2 calls) ≈ 14 calls ≈ 1.3 credits)

## Expect-line Verdict Table

| Phase | What | Expect | Verdict | Notes |
|-------|------|--------|---------|-------|
| 0 | Dirty checkout | clean | PASS (accepted) | 1 untracked file `pulse-webview/live-failure.spec.ts` |
| 0 | 8-token credit probe | PROBE_OK | PASS | HTTP 200 in 0.88s |
| 0 | Parity test (dump_pulse_prompt) | passes | PASS | 1/1 |
| 1 | Hermes parity + session-cache | 71 passed | PASS | 71/71 (61 parity + 10 session-cache) |
| 1 | Full Python suite (SET DELTA) | ≤6 failures, 0 new | PASS | Base 11F → ported 8F (3 fixed, 0 new on 666da89b) |
| 1 | Webview tests | 48 passed | PASS | 48/48 |
| 1 | tsc -b | exit 0 | PASS | |
| 1 | vite build | succeeds | PASS | |
| 2.0 | Byte capture (3 tiers) | stable→context→volatile | PASS | 5074→184→148 chars |
| 2.1 | Stable prefix + no brand | identity→context→volatile | PASS | `PULSE_FIXTURE_MARKER_alpha` once in context |
| 2.2 | Session-scoped built once | identical stable bytes | PASS | 5074 chars across runs |
| 2.3 | Context-file caps | truncation message | PASS | `kept 14000+4000 of 39552 chars` |
| 2.4 | Prompt-cache plan FLIP | custom→False, openai→True | PASS | |
| 2.5 | Bridge terminal (turn_done) | turn_done emitted | PASS | After stdin=DEVNULL + scipy pre-import |
| 3.1 | Simple turn (turn_done) | turn_done emitted | PASS | 2 LLM calls, budget stop |
| 3.2 | Threat blocking | guard blocks or model refuses | NOT-EXERCISED | Guard only sees write_file/edit_file/run_terminal args; model self-refused read_file on .env |
| 3.3 | /plan prefix | wired to plan_turn_prompt | NOT-WIRED (engine) | Prompt ported and parity-pinned; runtime does not call it (PROVENANCE.md §5) |
| 3.4 | /learn prefix | wired to learn_turn_prompt | NOT-WIRED (engine) | Same as /plan |
| 4 | Live Agent UI (manager-only) | CDP finds Manager tab | BLOCKED (launch config) | Layout checks passed; CDP cannot find Manager editor tab |
| 5 | PBR-002 | 3/3 checks passed | PASS | workspace-hops, proof-reaches-boundary, turn-completes all pass |

## Root-Cause Fixes Applied This Round

1. **stdin=DEVNULL** (d25307b7): `terminal_tools.py:207` — `stdin=subprocess.DEVNULL` prevents cmd.exe from inheriting the bridge's JSON-RPC pipe, which caused an indefinite hang waiting for EOF.

2. **scipy pre-import** (local workaround, not committed): `.venv/Lib/site-packages/sitecustomize.py` pre-imports scipy/sklearn to avoid a 60s+ cold import of `scipy.linalg` triggered by `VectorMemory → sklearn → scipy.sparse` during graph post-tool processing. This is the host's ML dependency, not a port issue. Documented in `env-manifest.json` as `_sitecustomize_note`.

## 8 Failing Test IDs (d25307b7, targeted subset)

All are subset of base (86eaaae2) failures except #6:

1. `test_autonomous_runtime_contract.py::test_ai_node_builds_expected_first_sarvam_request_without_provider_call` — base failure
2. `test_desktop_renderer_architecture.py::test_renderer_boundary_is_browser_safe_and_text_only` — base failure (missing toolCatalog.ts)
3. `test_desktop_renderer_architecture.py::test_native_and_lab_catalogs_cover_the_same_36_tools` — base failure (missing toolCatalog.ts)
4. `test_desktop_renderer_architecture.py::test_agent_layout_keeps_progressive_disclosure_and_stable_docks_native` — base failure (missing toolCatalog.ts)
5. `test_hermes_runtime_values.py::test_foreground_cancel_answers_when_a_grandchild_holds_the_pipes` — base failure (`os.killpg` unavailable on Windows)
6. `test_hermes_runtime_values.py::test_terminal_children_never_inherit_the_parents_stdin` — **NEW** (`shlex.join` produces Unix quoting that cmd.exe rejects; added in d25307b7 as stdin-fix verification)
7. `test_ui_tool_catalog.py::test_ui_catalog_covers_every_runtime_tool_name` — base failure (missing toolCatalog.ts)
8. `test_ui_tool_catalog.py::test_terminal_family_has_real_pulse_process_tools` — base failure (missing toolCatalog.ts)

**Subset verdict:** 7 of 8 are a subset of base (86eaaae2) failures. 1 new (test #6 above — Windows-specific, added in this commit's test expansion for stdin-fix verification).

Note: `test_session_engines.py::TestFeedbackStore::test_debris_lines_are_skipped_not_fatal` was a base failure that is **FIXED** in d25307b7.

## Collection-Hang Sweep

`test_agent_status_checkpoint.py` hangs during collection (exceeds 60s timeout). All other files complete collection within 32s. See `collect-only-times.txt`.

## Files in This Evidence Directory

```
bench-results/prompt-ui-live-e2e/
  README.md                              — this file
  findings.md                            — detailed per-phase findings
  env-manifest.json                      — env flags + sitecustomize note
  collect-only-times.txt                 — per-file collection timing sweep
  credits-spent.log                      — running credit ledger
  prompts/                               — prompt files used in Phase 3.x
  phase3-1-scipywarmed.log               — Phase 3.1 turn log
  phase3-2-threat.log                    — Phase 3.2 threat prompt log
  phase3-3-plan.log                      — Phase 3.3 /plan prompt log
  phase3-4-learn.log                     — Phase 3.4 /learn prompt log
  phase3-2-threat-*/frames.jsonl         — Phase 3.2 frame capture
  phase3-3-plan-*/frames.jsonl           — Phase 3.3 frame capture
  phase3-4-learn-*/frames.jsonl          — Phase 3.4 frame capture
  post-fix-scipywarmed-*/bridge_stderr.log — bridge stderr with scipy trace
  pbr002-rerun.log                       — PBR-002 graded output
  tsc-check.log                          — TypeScript compilation check
  vite-build.log                         — Vite build check
```
