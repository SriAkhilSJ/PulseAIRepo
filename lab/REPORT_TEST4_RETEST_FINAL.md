# Test 4 Retest — Final Evidence Report

**Date:** 2026-08-14  
**Provider/model:** Sarvam / `sarvam-105b-conversations`  
**Workspace:** `/home/user/test4_ws_retest`  
**Artifact bundle:** `lab/test4_final_artifacts/`

## Honest verdict

| Dimension | Verdict |
|---|---|
| Final four-page deliverable | **PASS** |
| Final TypeScript verification | **PASS — 0 errors** |
| Four-route real browser verification | **PASS — 4/4** |
| Video playback readiness | **PASS — readyState 4 on every route** |
| Screenshot visual-quality gate | **PASS — 4/4** |
| UI/UX quality | **PASS** |
| Provider call target | **PASS at boundary — 11 agent calls; 12 including preflight** |
| Known token target | **PASS at boundary — 99,270 agent tokens** |
| Latency target | **FAIL** |
| One uninterrupted autonomous run | **FAIL** |
| Zero evaluator intervention | **FAIL** |
| **Overall autonomous benchmark** | **PARTIAL** |
| **Final product/evidence** | **PASS** |

The final application is real and browser-proven, but it must not be described as a clean autonomous agent pass. The agent produced the scaffold, theme data, shared component, dynamic route, index, and base CSS. Its run ended unverified after a malformed/truncated write and exhausted turn budget. The evaluator then applied deterministic repairs, localized the videos, and ran the existing composite verifier without additional provider calls.

## Provider accounting

### Readiness preflight

```text
Status: PASS
Latency: 1,072 ms
HTTP: 200
Response received: true
```

### Agent phases

| Phase | Calls | Prompt | Completion | Total | Estimated cost |
|---|---:|---:|---:|---:|---:|
| Scaffold + shared data/component | 2 | 13,626 | 1,564 | 15,190 | $0.015190 |
| Remaining delivery/typecheck/browser attempt | 9 | 80,301 | 3,779 | 84,080 | $0.084080 |
| No-op continuation | 0 | 0 | 0 | 0 | $0 |
| **Agent total** | **11** | **93,927** | **5,343** | **99,270** | **$0.099270** |

Including the tiny readiness preflight gives **12 provider requests**. Its token usage was not returned through PulseAgent accounting and is excluded from 99,270. No provider call was used for the final deterministic repairs or final browser verification.

## Monitoring

### Initial phase

| Time | AI turns | Tool calls | Source files | Screenshots |
|---:|---:|---:|---:|---:|
| 30s | 1 | 1 | 4 | 0/4 |
| 60s | 1 | 1 | 4 | 0/4 |
| 90s | 1 | 1 | 4 | 0/4 |
| 120s | 1 | 1 | 4 | 0/4 |
| 150s | 1 | 1 | 4 | 0/4 |
| 180s | 2 | 3 | 6 | 0/4 |

The watchdog stopped this phase too aggressively at 180s even though the bounded delivery batch had just landed. Durable receipts preserved both files.

### Completion phase

| Time | AI turns | Tool calls | Source files | Screenshots |
|---:|---:|---:|---:|---:|
| 30s | 0 | 0 | 6 | 0/4 |
| 60s | 0 | 0 | 6 | 0/4 |
| 90s | 1 | 2 | 7 | 0/4 |
| 120s | 1 | 2 | 7 | 0/4 |
| 150s | 1 | 2 | 7 | 0/4 |
| 180s | 2 | 4 | 7 | 0/4 |
| 210s | 2 | 4 | 7 | 0/4 |
| 240s | 7 | 10 | 7 | 0/4 |
| 270s | 8 | 11 | 7 | 0/4 |

The phase exited 0 but correctly reported `Ended unverified`; process exit was not treated as benchmark success.

## Final browser evidence

| Route | Snapshot text | Video attributes | readyState | Screenshot | Visual gate |
|---|---|---|---:|---:|---|
| `/nature` | Living Landscapes | autoplay/muted/loop/playsInline, metadata preload | 4 | 1,365,669 B | **PASS** |
| `/still-life` | Quiet Objects | autoplay/muted/loop/playsInline, metadata preload | 4 | 1,149,424 B | **PASS** |
| `/materials` | Tactile Surfaces | autoplay/muted/loop/playsInline, metadata preload | 4 | 1,124,931 B | **PASS** |
| `/metal-parts` | Machined Motion | autoplay/muted/loop/playsInline, metadata preload | 4 | 1,236,863 B | **PASS** |

Visual metrics:

| Route | Dominant ratio | Luma stddev | Edge density |
|---|---:|---:|---:|
| Nature | 0.0916 | 40.00 | 0.0862 |
| Still Life | 0.0978 | 43.78 | 0.0834 |
| Materials | 0.0983 | 39.19 | 0.0766 |
| Metal Parts | 0.0843 | 42.76 | 0.0922 |

All captures are meaningful, high-variation 1280×800 browser screenshots—not generated imagery.

## Final design assessment

- Cohesive editorial identity: **Form / Motion**.
- Strong shared navigation and active-route indication.
- Distinct theme labels, headlines, supporting copy, CTAs, and film numbering.
- Full-screen responsive video composition with readable gradient treatment.
- Local optimized video assets eliminate third-party playback failures.
- Reduced-motion behavior pauses video while retaining poster/fallback art direction.
- No external web fonts required.

## Runtime findings fixed during the retest

1. Phase-specific binding successfully eliminated post-scaffold inspection calls.
2. Bounded delivery produced exactly two source mutations per response.
3. Durable receipts preserved progress after watchdog termination.
4. `stream_agent(initial_plan=None)` was fixed so a continuation no longer wipes a persisted plan.
5. Typecheck and composite-verifier failures now classify as failed tool receipts.
6. Named multi-file steps now require matching paths, not unrelated write counts.
7. Generated `LayoutProps` normalization moved into scaffold ownership.
8. Remote media availability was the browser failure; final local videos reached readyState 4.

## Final classification

```text
FINAL PRODUCT: PASS
BROWSER/UI/UX: PASS
STATIC VERIFICATION: PASS
CALL/TOKEN PERFORMANCE: PASS AT LIMIT
LATENCY: FAIL
AUTONOMOUS ONE-RUN BENCHMARK: PARTIAL / NOT A CLEAN PASS
```
