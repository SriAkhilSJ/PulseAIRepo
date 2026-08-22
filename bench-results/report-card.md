# PulseAI — Reliability Benchmark Report Card

- **Generated:** 2026-08-22 15:13 UTC
- **Runs graded:** 7
- **Rule:** belief is not evidence — every row below was graded by the evaluator, never by the agent itself.

- **Pulse commits:** e1927c0c2ac0d25459eb0e2c0275018fd3244c95
- **Lanes used:** cdp, echo

## Task outcomes

| Task | Outcome | Checks | Covered | Lane |
|---|---|---|---|---|
| PBR-001 Block prompts when no folder is open | failed_functional | 1/3 | 3 | cdp |
| PBR-001 Block prompts when no folder is open | failed_functional | 1/3 | 3 | cdp |
| PBR-003 Require explicit selection in a multi-root workspace | failed_functional | 1/3 | 2 | cdp |
| PBR-003 Require explicit selection in a multi-root workspace | failed_functional | 1/3 | 2 | cdp |
| PBR-012 Cancel a turn during bounded context preparation | failed_functional | 2/4 | 2 | echo |
| PBR-012 Cancel a turn during bounded context preparation | failed_functional | 2/4 | 2 | echo |
| PBR-012 Cancel a turn during bounded context preparation | failed_functional | 2/4 | 2 | echo |

## The four axes (per run)

| Task | First token (ms) | Completion (ms) | Model calls | Tool calls | In/out/cache tokens | Est. $ |
|---|---|---|---|---|---|---|
| PBR-001 | 0 | 0 | 0 | 0 | 0/0/0 | 0.0000 |
| PBR-001 | 0 | 0 | 0 | 0 | 0/0/0 | 0.0000 |
| PBR-003 | 0 | 0 | 0 | 0 | 0/0/0 | 0.0000 |
| PBR-003 | 0 | 0 | 0 | 0 | 0/0/0 | 0.0000 |
| PBR-012 | 0 | 313 | 0 | 0 | 0/0/0 | 0.0000 |
| PBR-012 | 0 | 262 | 0 | 0 | 0/0/0 | 0.0000 |
| PBR-012 | 0 | 321 | 0 | 0 | 0/0/0 | 0.0000 |

## Not yet run

- **PBR-002** Route the exact opened workspace through every layer — *needs live engine/desktop lane*
- **PBR-004** Bound initial context for a 20k-entry workspace — *needs live engine/desktop lane*
- **PBR-005** Prioritize the active failing file and its related test — *needs provider key*
- **PBR-006** Repair a single-file parser bug with focused verification — *needs provider key*
- **PBR-007** Rename a public symbol across implementation callers and tests — *needs provider key*
- **PBR-008** Block completion until a syntax regression is repaired — *needs provider key*
- **PBR-009** Distinguish a pre-existing unrelated test failure — *needs provider key*
- **PBR-010** Detect and repair a regression introduced by the agent — *needs provider key*
- **PBR-011** Recover from a timed-out command tree without orphaning children — *needs live engine/desktop lane*


## What this run proves (and does not)

- ✅ Desktop-lane evidence from the **live app** (DOM checks graded).
- ⚠️ **No real model calls in this batch** — latency/cost rows are pipeline timings, not product latency. Real numbers need the bridge lane with a configured provider/key.
- ❌ **Failed/unverified tasks:** PBR-001, PBR-001, PBR-003, PBR-003, PBR-012, PBR-012, PBR-012 — investigate before any claim.
- **Rule of three:** product claims ("fast", "cheap", "reliable") require 3 consecutive green runs on the same lane.

_Usage numbers are harness-reported until reconciled against engine telemetry frames (see docs/CTO_BENCHMARK_REVIEW_PR7.md)._
