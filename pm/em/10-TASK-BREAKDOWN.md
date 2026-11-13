## W8 — Suite baseline classification (T-23 · added 2026-11-12)

### T-23 · Classify the full-suite baseline and qualify Linux CI
- **Objective:** establish one authoritative failure inventory, separate product defects from environment/test defects, and define the minimum work for a defensible T-18 green gate.
- **Method:** four read-only workers (inventory, CI validity, runtime, product regressions). 41 modules re-run individually at HEAD and at clean baseline `7e4bb7ad`; full-suite log parsed to 97%.
- **Measured totals:** **105 failures / 41 modules at HEAD** vs **100 failures / 40 modules at `7e4bb7ad`**. R2 accounts for **1** failure (`test_agent_cards`). The rest pre-date it.
- **Classification (module-level, evidence-backed):**

| Class | Modules | Failures (approx) | Notes |
| --- | --- | --- | --- |
| PRODUCT_BUG | 18 | ~55 | shell boundary (P1), write refusal (P5), prompt shape (P4), pricing/doctor/classifier/cards, `_tools_by_name` (fixed) |
| ENVIRONMENT_DEPENDENT | 8 | ~30 | uv-trampoline under restricted token (P2), no adb device, POSIX-only APIs |
| TEST_DEFECT | 6 | ~8 | stale patch targets, BOM'd file, deleted module, exact-float equality, changed copy |
| DEPENDENCY_OR_CONFIGURATION | 2 | ~2 | provider unset → `runtime_degraded` |
| UNRESOLVED | 2 | ~4 | bridge timeout under concurrent load; one runtime-evidence assertion |

- **Root-cause patterns:** P1 SafeToolNode terminal boundary (~15); P2 AppContainer × uv trampoline (~17); P3 SSRF loopback block (~8); P4 system-prompt shape drift (~11); P5 write_file over-refusal (~6); P6 POSIX-only assertions (3); P7 stale tests vs deleted/renamed code (~7); P8 no device / no provider (~20); P9 isolated product regressions (~18).
- **Ambiguous — needs founder decision:** P1. `run_terminal` is blocked by `_GRAPH_MUTATION_BLOCKED` **by design** (AGENTS.md F-03); the tests encode the T-10/T-12 target. Recommendation: `xfail(strict=True)` with a T-10 reference, **not** deletion and **not** re-enabling shell before T-11 (env scrub) + T-10 (containment).
- **CI findings:** workflow valid and tracked; no `permissions:` block; py3.11 vs repo `.python-version` 3.14 drift; no `pytest-timeout`; desktop parity modules **skip** on Linux because `desktop/vscode/node_modules` is absent (so they cannot gate PRs as the T-18 comment claims); 30-minute timeout marginal-to-insufficient.
- **Runtime:** only **one** session-scoped fixture in 339 modules; guarded-import probe spawns cold interpreters; `bench-results` (936 MB) is walked by tests; fixed ports 45780/45781 and 8931; guard scratch dirs are created inside the repo root — all block safe sharding.
- **Dependencies:** T-18 green gate; T-02 (shell + write paths).
- **Effort:** inventory ~3h (done). Fix waves estimated 3–5 days.

## Summary