# Pulse Manager CDP Revalidation Report

**Date:** 2026-08-27
**Branch:** `arena/01a03741-pulseairepo`
**Source commit:** See `head.txt`
**Required repair ancestor:** `927d8eb4`
**Required harness ancestor:** `f61a6ca2`
**Provider requests:** 0

## Previous Evidence

- **Attempt 12:** Immutable runtime/product FAIL
- **R1:** Immutable FAIL (openManager missing)
- **R2:** Source/build PASS, interactive smoke NOT RUN
- **CDP R1:** Immutable FAIL (Manager overflow scrollWidth 860 > clientWidth 588)

## Compile Results

| Check | Exit |
|-------|------|
| `npm run compile` | **0** |

CSS changes compiled successfully.

## CDP Runtime Results

| Check | Result |
|-------|--------|
| Agent composer visible and enabled | **PASS** |
| Agent header + Manager button visible | **PASS** |
| Agent shell no horizontal overflow | **PASS** |
| Agent narrow responsive width | **PASS** |
| Assistant echo exact text | **PASS** |
| Completed transcript receipt | **PASS** |
| Manager opens as visible editor | **PASS** |
| Manager no horizontal overflow | **PASS** |
| Manager responsive inspector | **FAIL** (CDP protocol limitation) |
| No renderer exceptions | **PASS** |
| No console errors | **PASS** |

## Key Improvement

The Manager overflow fix (`927d8eb4`) resolved the R1 failure:
- **Before:** scrollWidth 860 > clientWidth 588
- **After:** scrollWidth 636 <= clientWidth 636

## Failure Analysis

The responsive inspector check failed because `Browser.getWindowForTarget` is not available in this Electron/Chromium CDP build:

```
Browser.getWindowForTarget: {"code":-32601,"message":"'Browser.getWindowForTarget' wasn't found"}
```

This is a CDP protocol limitation, not a UI bug. The CDP script cannot resize the Electron window to trigger the responsive breakpoint. The Manager's CSS container queries cannot be validated through CDP alone.

## Screenshots

- `01-agent-ready.png` — 111,863 bytes
- `02-agent-narrow.png` — 111,863 bytes
- `03-agent-echo-completed.png` — 103,885 bytes
- `04-manager-wide.png` — 128,852 bytes
- `05-manager-responsive.png` — NOT CAPTURED (CDP protocol limitation)

## Echo Turn Verification

- Prompt: `Pulse Agent UI provider-free CDP smoke`
- Assistant response: `Pulse Agent UI provider-free CDP smoke` (exact match)
- Completion receipt: `Run completed` (observed)
- Provider requests: 0

## Confirmations

- **Zero provider requests:** Confirmed.
- **Attempt 12, R1, R2, CDP R1 evidence:** All untouched.
- **PR #9:** Open and unmerged.
- **No source modifications:** All failures preserved.

## Verdict

- **Manager overflow fix:** PASS (validated via CDP)
- **CDP runtime validation:** FAIL (protocol limitation)
- **Overall:** FAIL

The Manager overflow is fixed. The remaining CDP failure is a harness limitation (`Browser.getWindowForTarget` unavailable). The responsive inspector behavior requires either a different CDP approach or manual verification.
