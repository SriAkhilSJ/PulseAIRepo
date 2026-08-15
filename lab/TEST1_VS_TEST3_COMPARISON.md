# PulseAgent Lab Comparison — Test 1 vs Test 3

**Date:** 2026-08-14  
**Evidence policy:** Only preserved files/logs are treated as fact. Missing Test-1 metrics are marked unavailable rather than reconstructed from memory.

## Executive table

| Dimension | Test 1 — Calculator repair | Test 3 — React/Three component integration |
|---|---|---|
| Task | Repair deliberate bugs in calculator utilities (`add`, `subtract`, `multiply`, `divide`, `fib`) | Scaffold Next.js/TS/Tailwind, install Three dependencies, copy two provided TSX files byte-for-byte, typecheck, and obtain visual proof |
| Preserved workspace | `lab/workspace_a/` | Runtime workspace: `/home/user/test3_ws_believe/`; commit-safe evidence copy: `lab/test3_believe_artifacts/` |
| Final component/code artifacts | `lab/workspace_a/calc.py` exists and contains corrected calculator behavior | Both `hero-futuristic.tsx` (7,025 B) and `demo.tsx` (6,468 B) exist in `src/components/ui/` |
| Byte identity requirement | Not applicable | **PASS** — both destination SHA-256 hashes exactly match `_provided` sources |
| Dependency/scaffold requirement | Not applicable | **PASS** — Next.js 16.3.1, TS/Tailwind, `three`, `@react-three/drei`, `@react-three/fiber` |
| Static verification | No preserved Test-1 verification transcript found | **PASS** — final `npx tsc --noEmit` returned 0 errors |
| Browser/UI verification | Not applicable | Browser tools ran and screenshot exists, but screenshot is mostly blank and only visibly shows `Scroll to explore`; **not acceptable as full UI/UX proof** |
| Autonomous continuity | Historical lab notes say the calc lab crashed on every resume before the later F2 guard; exact final run record is not preserved | Core phase exited 0; focused visual phase exited 0; an earlier visual attempt was OOM-killed, and evaluator simplified `page.tsx` before the successful screenshot phase |
| Known calls | **Unavailable in preserved Test-1 artifacts** | Successful core + visual phases: **32 calls known minimum** (22 + 10); actual total is higher because a failed visual attempt has no completed JSON report |
| Known tokens | **Unavailable in preserved Test-1 artifacts** | Successful phases: **336,722 known tokens** (242,681 + 94,041); actual total is higher |
| Known wall time | **Unavailable in preserved Test-1 artifacts** | Successful phases: **335.65s** (241.28s + 94.37s); excludes failed visual attempt |
| Human/evaluator intervention | Exact amount unavailable | Yes — monitoring, browser/runtime fixes, and a page simplification between core and visual phases |
| Honest verdict | **INCONCLUSIVE as an end-to-end run** — corrected artifact exists, but preserved run metrics/verification are insufficient | **PARTIAL** — component delivery and typecheck pass; autonomous full UI/UX proof does not pass |

## Test 3 artifact evidence

| Artifact | Size | SHA-256 | Result |
|---|---:|---|---|
| `_provided/demo.tsx` | 6,468 B | `cf8e41c97ef8df5280e2803ba0231e6faa4009a3a8609016a2b9993467041543` | Source |
| `src/components/ui/demo.tsx` | 6,468 B | `cf8e41c97ef8df5280e2803ba0231e6faa4009a3a8609016a2b9993467041543` | Exact match |
| `_provided/hero-futuristic.tsx` | 7,025 B | `f66c4f9cc10f4e1b81713b25fe360626f3684287a063859a4ed88191ee9ddd00` | Source |
| `src/components/ui/hero-futuristic.tsx` | 7,025 B | `f66c4f9cc10f4e1b81713b25fe360626f3684287a063859a4ed88191ee9ddd00` | Exact match |
| `screenshots/retest-visual-proof.png` | 7,111 B | `9fe763dedb0cf86469ce2e57cd5a74ba753ebe222f74374c3240b9b3211c5af0` | Authentic browser capture, weak UI/UX evidence |

## Test 3 monitoring summary

| Phase | 30s | 60s | 90s | 120s/final | Outcome |
|---|---|---|---|---|---|
| Core integration | 2 calls; files absent | 7 calls; both files present | scaffold running | continued to 241.28s | Exit 0; files/deps/typecheck completed |
| Focused visual proof | 1 call; no screenshot | 6 calls; screenshot present | 8 calls; screenshot present | 10 calls; exit at 94.37s | Browser tool captured PNG and snapshot text |

## Final interpretation

Test 1 demonstrates that a corrected code artifact can exist even when durable run evidence is incomplete. Test 3 demonstrates materially stronger delivery and verification machinery: deterministic copies, hash identity, compiler verification, monitored execution, and real browser-tool calls. But Test 3 must **not** be described as a clean UI/UX success: the screenshot does not visually prove the intended Three.js scene, and the successful visual phase followed evaluator intervention.

The defensible project claim is:

> PulseAgent can complete and compiler-verify the Test-3 component integration, but reliable autonomous visual/UI validation remains unfinished.
