# PulseAI — Reliability Benchmark Report Card

- **Generated:** 2026-08-22 19:52 UTC
- **Runs graded:** 2
- **Rule:** belief is not evidence — every row below was graded by the evaluator, never by the agent itself.

- **Pulse commits:** 54c2ccbbe6d21ea7c7d582f3e47a30099b046e2c, 83f144d01228565753877ce0233246865ff7e91a
- **Lanes used:** bridge, echo

## Task outcomes

| Task | Outcome | Checks | Covered | Lane |
|---|---|---|---|---|
| PBR-012 Cancel a turn during bounded context preparation | passed | 2/4 (2 not run on lane) | 2 | bridge |
| PBR-012 Cancel a turn during bounded context preparation | passed | 2/4 (2 not run on lane) | 2 | echo |

## The four axes (per run)

| Task | First token (ms) | Completion (ms) | Model calls | Tool calls | In/out/cache tokens | Est. $ |
|---|---|---|---|---|---|---|
| PBR-012 | 2133 | 2133 | 0 | 0 | 0/0/0 | 0.0000 |
| PBR-012 | 0 | 234 | 0 | 0 | 0/0/0 | 0.0000 |

## Not yet run

- **PBR-001** Block prompts when no folder is open — *needs live engine/desktop lane*
- **PBR-002** Route the exact opened workspace through every layer — *needs live engine/desktop lane*
- **PBR-003** Require explicit selection in a multi-root workspace — *needs live engine/desktop lane*
- **PBR-004** Bound initial context for a 20k-entry workspace — *needs live engine/desktop lane*
- **PBR-005** Prioritize the active failing file and its related test — *needs provider key*
- **PBR-006** Repair a single-file parser bug with focused verification — *needs provider key*
- **PBR-007** Rename a public symbol across implementation callers and tests — *needs provider key*
- **PBR-008** Block completion until a syntax regression is repaired — *needs provider key*
- **PBR-009** Distinguish a pre-existing unrelated test failure — *needs provider key*
- **PBR-010** Detect and repair a regression introduced by the agent — *needs provider key*
- **PBR-011** Recover from a timed-out command tree without orphaning children — *needs live engine/desktop lane*


## What this run proves (and does not)

- ✅ **On the lanes used:** every graded task passed its coverable checks.
- ⚠️ **No desktop-lane (DOM) evidence in this batch** — UI-level checks (composer disabled state, workspace selector, cancel receipt) are NOT yet graded. Run `--driver cdp` on a machine with the built PulseAI IDE.
- ⚠️ **No real model calls in this batch** — latency/cost rows are pipeline timings, not product latency. Real numbers need the bridge lane with a configured provider/key.
- **Rule of three:** product claims ("fast", "cheap", "reliable") require 3 consecutive green runs on the same lane.

_Usage numbers are harness-reported until reconciled against engine telemetry frames (see docs/CTO_BENCHMARK_REVIEW_PR7.md)._
