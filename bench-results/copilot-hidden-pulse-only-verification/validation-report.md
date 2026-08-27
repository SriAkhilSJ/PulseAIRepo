# Copilot-Hidden Pulse-Only UI Verification Report

**Date:** 2026-08-27
**Branch:** `main` (HEAD: `7d2d8473`)
**Required implementation ancestor:** `d0843937` (four-mode agent)
**Required CDP harness ancestor:** `d9cdec27` (mode menu CDP)
**Provider requests:** 0

## Source/Build Results

| Check | Exit | Result |
|-------|------|--------|
| Focused pytest | 0 | **65/65 PASS** |
| Protocol generation | 0 | **PASS** |
| Desktop syntax | 0 | **PASS** |
| UI build (vite) | 0 | **PASS** |
| Desktop typecheck-client | 0 | **PASS** |
| Desktop valid-layers | 0 | **PASS** |
| Desktop compile | 0 | **PASS** |

## CDP Runtime Results (10/10 PASS)

| Check | Result |
|-------|--------|
| AuxBar: no Chat tab | **PASS** |
| Watermark: no "Open Chat" | **PASS** |
| Title bar: no Copilot sparkle | **PASS** |
| Pulse composer visible | **PASS** |
| Mode menu (Agent/Plan/Debug/Ask) | **PASS** |
| No Copilot Chat view | **PASS** |
| No MCP invoke surface | **PASS** |
| Pulse view present | **PASS** |
| No renderer/console errors | **PASS** |

## Copilot Hiding Mechanism

Three-layer approach:

1. **Context keys** (`pulseAIHideCopilot.ts`): Forces `chatSetupHidden=true`, `chatIsEnabled=false` at `AfterRestored` phase. Handles watermark, onboarding, and title bar widget.

2. **View deregistration** (`pulseAIHideCopilot.ts`): Deregisters Copilot Chat view from its container via `IViewsRegistry.deregisterViews()`. Container has `hideIfEmpty:true` so it auto-removes from auxiliary bar.

3. **CSS hiding** (`pulseAI.css`): Hides remaining Copilot chrome: status bar entry (`#chat\.statusBarEntry`), sparkle icons (`.codicon-chat-sparkle`), title bar sign-in button via `chat.titleBar.signIn.enabled: false`.

## Phase 1 Inventory

| Check | Result |
|-------|--------|
| Fork rebranding docs | Present |
| Copilot integration analysis | Present |
| PulseAI design plan | Present |
| Copilot registration review | Present |
| Pulse agent UI adaptation | Present |
| Copilot source intact (`contrib/chat`) | Present |
| Copilot extension intact (`extensions/copilot`) | Present |
| `defaultChatAgent` in `product.json` | Present (required field) |
| `chat.disableAIFeatures: true` | Set in theme-defaults |
| `chat.titleBar.signIn.enabled: false` | Set in theme-defaults |
| `pulseAIHideCopilot.ts` | Present |

## Files Modified

| File | Change |
|------|--------|
| `pulseAIHideCopilot.ts` | Added view deregistration at `AfterRestored` |
| `pulseAI.css` | Added Copilot CSS hiding rules |
| `theme-defaults/package.json` | Added `chat.titleBar.signIn.enabled: false` |

## Verdict

**Source/build validation: PASS**
**CDP runtime validation: PASS**
**Phase 1 inventory: PASS**
**Overall: PASS**
