# Test 3 — Lab Metrics Report

**Date:** 2026-08-14  
**Agent:** PulseAgent  
**Provider/model:** Sarvam custom endpoint / `sarvam-105b-conversations`  
**Core thread:** `lab-test3-believe-final`  
**Visual thread:** `lab-test3-believe-visual-proof-2`  
**Evidence:** `report_test3_believe.json`, `report_test3_believe_visual2.json`, event logs, and `test3_believe_artifacts/MANIFEST.sha256`

## Final verdict

| Area | Verdict | Evidence |
|---|---|---|
| Component delivery | **PASS** | Both destination TSX files exist and match source hashes exactly |
| Scaffold and dependencies | **PASS** | Next.js/TypeScript/Tailwind plus Three, Drei and React Three Fiber |
| TypeScript | **PASS** | Final `tsc --noEmit` completed with 0 errors |
| Browser-tool execution | **PASS** | Agent called navigate, snapshot and screenshot; PNG persisted |
| Intended UI/UX proof | **NOT PASS** | PNG is mostly blank and visibly shows only `Scroll to explore`; it does not prove the intended visual scene |
| Overall | **PARTIAL** | Engineering artifact passed; full autonomous visual acceptance did not |

## Headline metrics

| Metric | Core integration | Focused visual phase | Known combined total |
|---|---:|---:|---:|
| Process exit | 0 | 0 | Both recorded phases exited 0 |
| Wall time | 241.28 s | 94.37 s | **335.65 s (5m 35.65s)** |
| API calls | 22 | 10 | **32 known minimum** |
| Prompt tokens | 240,197 | 93,221 | **333,418** |
| Completion tokens | 2,484 | 820 | **3,304** |
| Total tokens | 242,681 | 94,041 | **336,722 known minimum** |
| Estimated API cost | $0.242681 | $0.094041 | **$0.336722 known minimum** |
| Execution-trace entries | 23 | 5 | 28 recorded |
| Recovery attempts | 0 | 0 | 0 recorded |
| Replans | 0 | 0 | 0 recorded |
| Recorded failures | 0 | 0 | 0 recorded |

> “Known minimum” is intentional: an earlier visual attempt was OOM-killed before it produced a final JSON report. Its calls, tokens, cost and wall time are not included. Reporting 32 calls / 336,722 tokens as the absolute total would be misleading.

## Latency with terminal/tool deduction

Durations below were reconstructed from paired `tool.call` → `tool.result` timestamps. Parallel intervals are merged for the “tool occupied wall time” calculation; unresolved final calls are excluded.

| Latency measurement | Core | Visual | Combined |
|---|---:|---:|---:|
| Gross wall time | 241.28 s | 94.37 s | **335.65 s** |
| Terminal-like execution | 80.45 s | 5.02 s | **85.47 s** |
| Wall minus terminal-like execution | 160.83 s | 89.35 s | **250.18 s** |
| All known tool occupied wall time (parallel intervals merged) | 99.04 s | 9.06 s | **108.10 s** |
| Estimated non-tool/orchestration/API wait | 142.24 s | 85.31 s | **227.55 s** |

### Terminal-like duration breakdown

| Operation | Duration |
|---|---:|
| `scaffold_nextjs` (includes create/install subprocesses) | 46.87 s |
| Core `typecheck_workspace` calls | 33.55 s |
| Core explicit `run_terminal` (`mkdir`) | 0.03 s |
| Visual `start_terminal` + readiness wait | 5.02 s |
| **Total terminal-like** | **85.47 s** |

Browser execution consumed another **4.04 s** (`navigate` 3.82s, `snapshot` 0.04s, `screenshot` 0.17s). It is not counted as terminal time.

## Performance indicators

| Indicator | Value | Interpretation |
|---|---:|---|
| Gross wall / API call | **10.49 s/call** | Includes terminal, compiler, browser and orchestration time |
| Terminal-adjusted wall / API call | **7.82 s/call** | Approximate API/orchestration cost after terminal-like deduction |
| Estimated non-tool time / API call | **7.11 s/call** | Uses merged known tool intervals |
| Total tokens / call | **10,522.6 tokens/call** | Prompt replay dominates |
| Prompt tokens / call | **10,419.3** | High static/history overhead |
| Completion tokens / call | **103.3** | Tool-driven short outputs |
| Prompt share | **99.02%** | Primary efficiency concern |
| Components delivered by watchdog checkpoint | **60 s** | Both named files were present at the second monitor check |
| Screenshot delivered by visual checkpoint | **60 s** | Agent screenshot existed by the second visual monitor check |

## Durability

| Durability property | Result | Notes |
|---|---|---|
| Named artifacts persisted after process exit | **PASS** | Files and hashes preserved |
| Copy-first delivery before expensive setup | **PASS** | Components were present by 60s |
| Byte integrity across phases | **PASS** | Source and destination SHA-256 values match |
| Watchdog visibility every 30s | **PASS** | Both phases emitted 30-second status records |
| Automatic recovery from process/OOM failure | **NOT PASS** | An earlier visual process was OOM-killed and required evaluator action/new focused phase |
| Same-session resume | **NOT PROVEN** | Visual proof used a new thread against the same workspace, not a durable same-thread resume |
| No external intervention | **NOT PASS** | Browser/runtime fixes and page simplification occurred between phases |
| Durable verification evidence | **PARTIAL** | Compiler and screenshot evidence persist; screenshot quality is insufficient for UI/UX acceptance |

**Durability assessment: PARTIAL.** Artifact durability is strong; autonomous process durability under browser/compile memory pressure remains unfinished.

## API and token accounting

| Item | Value |
|---|---:|
| Known API calls | **32** |
| Known prompt tokens | **333,418** |
| Known completion tokens | **3,304** |
| Known total tokens | **336,722** |
| Engine-estimated cost | **$0.336722** |
| Unreported failed-attempt usage | **Unknown; excluded** |

## Artifact manifest

| Artifact | Bytes | SHA-256 | Result |
|---|---:|---|---|
| `_provided/demo.tsx` | 6,468 | `cf8e41c97ef8df5280e2803ba0231e6faa4009a3a8609016a2b9993467041543` | Source |
| `src/components/ui/demo.tsx` | 6,468 | `cf8e41c97ef8df5280e2803ba0231e6faa4009a3a8609016a2b9993467041543` | Exact match |
| `_provided/hero-futuristic.tsx` | 7,025 | `f66c4f9cc10f4e1b81713b25fe360626f3684287a063859a4ed88191ee9ddd00` | Source |
| `src/components/ui/hero-futuristic.tsx` | 7,025 | `f66c4f9cc10f4e1b81713b25fe360626f3684287a063859a4ed88191ee9ddd00` | Exact match |
| Browser screenshot | 7,111 | `9fe763dedb0cf86469ce2e57cd5a74ba753ebe222f74374c3240b9b3211c5af0` | Authentic but weak visual proof |

## Engineering deductions

1. **Delivery correctness is solved for this task:** deterministic copying, hash equality and TypeScript verification all hold.
2. **Latency is not dominated by terminal work alone:** after subtracting 85.47s of terminal-like execution, approximately 250.18s remains. Provider/orchestration latency and repeated prompt construction are substantial.
3. **Prompt efficiency is poor:** 99.02% of tokens are prompt tokens, and each API call carries about 10.4k prompt tokens.
4. **Browser tooling functions, but visual acceptance needs semantic image checks:** “PNG exists” is insufficient. Future gates must detect blank/near-blank captures and verify expected visual regions/text.
5. **Exit code 0 is not the verdict:** the final classification must combine artifact, compiler, browser and intervention evidence. For this run, that classification is **PARTIAL**.
