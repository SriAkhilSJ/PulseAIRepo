# Four-Mode Agent UI Desktop Validation Report

**Date:** 2026-08-27
**Branch:** `arena/01a03741-pulseairepo`
**Source commit:** See `head.txt`
**Required implementation ancestor:** `d0843937`
**Required CDP harness ancestor:** `d9cdec27`
**Provider requests:** 0

## Source/Build Results

| Check | Exit | Result |
|-------|------|--------|
| Focused pytest | 0 | **65/65 PASS** |
| Protocol generation | 0 | **PASS** |
| Desktop syntax | 0 | **22/22 files parsed** |
| UI build (vite) | 0 | **PASS** |
| Desktop typecheck-client | 0 | **0 errors** |
| Desktop valid-layers | 0 | **0 violations** |
| Desktop compile | 0 | **0 errors** |

## CDP Runtime Results (16/16 PASS)

| Check | Result |
|-------|--------|
| Agent composer visible/enabled | **PASS** |
| Agent header + Manager button | **PASS** |
| Agent shell no overflow | **PASS** |
| Mode menu Agent/Plan/Debug/Ask | **PASS** |
| Mode accessible roles/descriptions | **PASS** |
| Agent initially selected | **PASS** |
| Ask selection updates mode | **PASS** |
| Execution mode picker (full DOM) | **PASS** |
| Agent narrow responsive | **PASS** |
| Assistant echo exact text | **PASS** |
| Completed transcript receipt | **PASS** |
| Manager opens visible | **PASS** |
| Manager no overflow | **PASS** |
| Manager responsive container (<=880) | **PASS** |
| Manager responsive inspector hidden | **PASS** |
| No renderer/console errors | **PASS** |

## Mode Menu Validation

- Four modes visible: Agent, Plan, Debug, Ask
- Each has accessible `radio-menuitem` role and description
- Agent is initially selected
- Ask selection updates the functional mode control
- DOM interaction restores Agent selection

## Echo Turn Verification

- Prompt: `Pulse Agent UI provider-free CDP smoke`
- Assistant response: exact match
- Completion receipt: `Run completed`
- Provider requests: 0

## Screenshots

- `01-agent-ready.png`
- `02-agent-narrow.png`
- `03-agent-echo-completed.png`
- `04-manager-wide.png`
- `05-manager-responsive.png`
- `06-mode-menu.png`

## Confirmations

- **Zero provider requests:** Confirmed. Echo runner used only.
- **All historical evidence untouched:** Confirmed.
- **PR #9:** Open and unmerged.
- **No source modifications:** All results preserved.

## Verdict

**Source/build validation: PASS**
**CDP runtime validation: PASS**
**Overall: PASS**
