# Pulse Agent UI Desktop Validation Report

**Date:** 2026-08-26
**Branch:** `arena/01a03741-pulseairepo`
**Source commit:** See `head.txt`
**Required UI ancestor:** `0f84d2df`
**Provider requests:** 0
**Attempt 12:** Immutable runtime/product FAIL — not rerun

## Results Summary

| Check | Exit Code | Result |
|-------|-----------|--------|
| Focused pytest | 0 | **30/30 PASS** |
| Desktop syntax check | 0 | **22/22 files parsed** |
| UI build (vite) | 0 | **PASS** |
| Desktop typecheck-client | 1 | **FAIL** (1 TS error) |
| Desktop valid-layers-check | 1 | **FAIL** (1 layer error) |
| Desktop compile | 1 | **FAIL** (1 compile error) |
| Desktop UI smoke | — | **NOT RUN** (compile failed) |
| Agent responsive | — | NOT RUN |
| Manager responsive | — | NOT RUN |
| Keyboard focus | — | NOT RUN |
| Plan/tool disclosure | — | NOT OBSERVED |
| High contrast | — | NOT RUN |
| Reduced motion | — | NOT RUN |

## Failure Details

### TypeScript compile error

```
src/vs/workbench/contrib/pulseai/browser/pulseAIRenderer.ts(451,117): error TS2339: Property 'openManager' does not exist on type 'PulseAIRenderHost'.
```

The `PulseAIRenderHost` interface (line 44) does not declare `openManager`, but the `renderAgent` function (line 451) calls `host.openManager`. The service implementation (`pulseAIRendererService.ts`) also lacks this property in its host object.

This is a missing interface method — the `openManager` callback was added to the renderer UI code but the host interface and implementation were not updated to match.

## Command Exit Codes

- `pytest`: 0
- `npm run check:desktop-syntax`: 0
- `npm run build` (UI): 0
- `npm run typecheck-client`: 1
- `npm run valid-layers-check`: 1
- `npm run compile`: 1

## Confirmations

- **Zero provider requests:** Confirmed. All checks were provider-free.
- **Attempt 12 untouched:** Confirmed. No rerun, repair, or relabel.
- **Historical evidence untouched:** Confirmed. `bench-results/native-capability-validation-desktop/` unchanged.
- **PR #9:** Open and unmerged.
- **No source modifications:** This validation preserved all failures and made no fixes.
