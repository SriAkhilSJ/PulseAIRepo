# Test 4 — Video Hero Showcase Benchmark

**Date:** 2026-08-14  
**Provider/model:** Sarvam custom endpoint / `sarvam-105b-conversations`  
**Workspace:** `/home/user/test4_ws_video_heroes`  
**Verdict:** **FAIL**

## Acceptance summary

| Requirement | Result | Evidence |
|---|---|---|
| Four themed video hero pages | **FAIL** | No theme routes or reusable VideoHero source were produced |
| Nature / Still Life / Materials / Metal Parts art direction | **FAIL** | Missing |
| Real optimized looping videos | **FAIL** | No `<video>` deliverable exists |
| TypeScript verification | **FAIL / not run on deliverable** | Only generated scaffold exists |
| Four-route browser verification | **FAIL / not reached** | `verify_ui_routes` was never called |
| Four meaningful screenshots | **FAIL** | 0/4 screenshots |
| Nice UI/UX | **FAIL / cannot evaluate** | No showcase UI exists |
| ≤12 provider calls | **FAIL** | 14 successful provider calls known minimum |
| ≤100K tokens | **FAIL** | 123,138 successfully-accounted tokens known minimum |
| ≤180 seconds | **FAIL** | Multiple monitored phases exceeded the target |
| Zero intervention / one uninterrupted run | **FAIL** | Watchdog stopped stalled phases; continuations were attempted |

## Known provider accounting

| Thread | Successful calls | Prompt | Completion | Total | Cost estimate | Productive result |
|---|---:|---:|---:|---:|---:|---|
| `lab-test4-video-heroes` | 10 | 96,179 | 1,993 | 98,172 | $0.098172 | Scaffold only; no showcase source |
| `lab-test4-video-heroes-resume` | 4 | 24,412 | 554 | 24,966 | $0.024966 | Generated-layout type fix only |
| Durable same-thread continuation | 0 completed responses | 0 accounted | 0 | 0 accounted | unknown | Provider request timed out / watchdog stop |
| Direct pre-approved-plan thread | 0 completed responses | 0 accounted | 0 | 0 accounted | unknown | `openai.APITimeoutError: Request timed out` |
| **Known minimum** | **14** | **120,591** | **2,547** | **123,138** | **$0.123138** | No deliverable |

Timed-out requests may still consume provider credits. The engine has no response usage record for them, so actual calls/cost can be higher. “Known minimum” is mandatory.

## 30-second monitoring

### Initial run

| Time | AI turns | Tool calls | Source files | Screenshots |
|---:|---:|---:|---:|---:|
| 30s | 0 | 0 | 0 | 0/4 |
| 60s | 2 | 2 | 4 generated scaffold files | 0/4 |
| 90s | 2 | 2 | 4 | 0/4 |
| 120s | 4 | 8 | 4 | 0/4 |
| 150s | 7 | 12 | 4 | 0/4 |
| 180s | 8 | 13 | 4 | 0/4 |

Watchdog action: killed because showcase source remained missing at 180s.

### Focused fresh continuation

| Time | AI turns | Tool calls | Source files | Screenshots |
|---:|---:|---:|---:|---:|
| 30s | 0 | 0 | 4 | 0/4 |
| 60s | 2 | 6 | 4 | 0/4 |
| 90s | 2 | 6 | 4 | 0/4 |
| 120s | 2 | 6 | 4 | 0/4 |

Watchdog action: killed because deliverable source remained missing at 120s.

### Durable same-thread continuation

No agent/tool event occurred for 120 seconds. The watchdog terminated the stalled provider wait.

### Direct pre-approved-plan execution

No agent/tool event occurred for 211 seconds. The request ultimately surfaced:

```text
openai.APITimeoutError: Request timed out
```

No provider response was returned and no files were changed.

## Workspace result

Only the generated Next.js scaffold exists. Relevant files:

```text
src/app/globals.css
src/app/layout.tsx
src/app/page.tsx
src/app/favicon.ico
```

`src/app/layout.tsx` received the known generated `LayoutProps` correction. There is no `VideoHero`, no theme data, no dynamic theme route, and no screenshots.

## Performance assessment

| Dimension | Verdict |
|---|---|
| Capability delivery | **FAIL** |
| Token efficiency | **FAIL** — exceeded 100K before producing source |
| Call efficiency | **FAIL** — exceeded 12 known calls |
| Latency | **FAIL** |
| Browser/UI quality | **Not reached** |
| Watchdog behavior | **PASS** — stopped non-progress and protected remaining credits |
| Reporting honesty | **PASS** — no scaffold or process exit is classified as task success |

## Primary engineering findings

1. **Planning/exploration still dominated execution.** The initial run consumed multiple reads, terminal metadata checks, `think`, and an rejected `execute_code` attempt after the scaffold instead of writing the known deliverables.
2. **Large multi-file tool responses can exceed provider read latency.** Focused/direct prompts that requested the complete source batch produced no response before timeout.
3. **A process exit is not a task verdict.** The direct harness returned process exit 0 because it captured the exception into JSON, while the report correctly records a provider timeout and zero work.
4. **Performance gates worked.** The run cannot be presented as success merely because setup succeeded.
5. **No further live retry should run on this key without user authorization.** Remaining credits are limited and provider timeouts have unknown billing.

## Final classification

```text
TEST 4: FAIL
Artifacts: missing
Typecheck: not applicable to missing deliverable
Browser match: not reached
UI/UX: not evaluated
Performance: fail
Durability: fail
Watchdog: pass
```
