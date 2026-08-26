# Pulse Agent UI CDP Runtime Validation Report

**Date:** 2026-08-26
**Branch:** `arena/01a03741-pulseairepo`
**Source commit:** See `head.txt`
**Required repair ancestor:** `b790a29d`
**Provider requests:** 0
**Attempt 12:** Immutable runtime/product FAIL — not rerun
**R1:** Immutable FAIL (`openManager` missing)
**R2:** Source/build PASS, interactive smoke NOT RUN

## CDP Runtime Results

| Check | Result |
|-------|--------|
| Agent composer visible and enabled | **PASS** |
| Agent header and Manager button visible | **PASS** |
| Agent shell no horizontal overflow | **PASS** |
| Agent narrow responsive width active | **PASS** |
| Assistant response contains exact echo text | **PASS** |
| Completed transcript contains completion receipt | **PASS** |
| Pulse Manager opens as visible editor | **PASS** |
| Pulse Manager no horizontal overflow | **FAIL** |
| Pulse Manager responsive inspector | NOT REACHED |
| No renderer exceptions | **PASS** |
| No console errors | **PASS** |

## Failure Details

```
Pulse Manager has no horizontal overflow
scrollWidth: 860, clientWidth: 588
```

The `.pulseai-manager-shell` container has horizontal overflow. The inspector sidebar content (860px) exceeds the container width (588px). This prevented the Manager responsive check from executing.

## Screenshots

- `01-agent-ready.png` — 114,269 bytes (PASS)
- `02-agent-narrow.png` — 114,269 bytes (PASS)
- `03-agent-echo-completed.png` — 106,023 bytes (PASS)
- `04-manager-wide.png` — NOT CAPTURED (script failed before reach)
- `05-manager-responsive.png` — NOT CAPTURED (script failed before reach)

## Echo Turn Verification

- Prompt: `Pulse Agent UI provider-free CDP smoke`
- Assistant response: `Pulse Agent UI provider-free CDP smoke` (exact match)
- Completion receipt: `Run completed` (observed)
- Provider requests: 0

## Confirmations

- **Zero provider requests:** Confirmed. Echo runner used only.
- **Attempt 12 untouched:** Confirmed.
- **R1 evidence untouched:** Confirmed.
- **R2 evidence untouched:** Confirmed.
- **PR #9:** Open and unmerged.
- **No source modifications:** All failures preserved.

## Verdict

- **CDP runtime validation:** FAIL (Manager overflow)
- **Overall UI validation gate:** FAIL

The Agent UI passes all checks (composer, header, echo turn, no overflow). The Manager has horizontal overflow in its shell container that needs investigation.
