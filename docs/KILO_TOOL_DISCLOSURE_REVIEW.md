# Kilo Code Tool Rendering Review → PulseAI Decisions

**Reviewed:** 2026-08-15
**Kilo commit:** `c8271ad6f4b9d8a33da2485202af17ab07563c63`
**Method:** blobless/no-checkout clone; individual source blobs read with `git show`.

## End-to-end files reviewed

- `packages/session-ui/src/components/basic-tool.tsx`
- `packages/session-ui/src/components/basic-tool.css`
- `packages/session-ui/src/components/message-part.tsx`
- `packages/session-ui/src/components/tool-status-title.tsx`
- `packages/session-ui/src/components/tool-error-card.tsx` and CSS
- `packages/kilo-vscode/webview-ui/src/components/chat/AssistantMessage.tsx`
- `packages/kilo-vscode/webview-ui/src/components/chat/TaskToolExpanded.tsx`
- `packages/kilo-vscode/webview-ui/src/components/chat/VscodeToolOverrides.tsx`
- `packages/kilo-vscode/webview-ui/src/components/chat/task-tool-state.ts`
- `packages/kilo-vscode/webview-ui/src/components/chat/tool-default-open.ts`

## Kilo behavior that matters

### 1. Tool rows are disclosures, not static cards

`BasicTool` is built on `Collapsible`. The trigger carries status/title/subtitle/arguments and an arrow only when expandable content exists. Expanded content is mounted separately.

### 2. Open policy depends on tool and state

- terminal/bash can default open;
- edit/write/apply-patch can follow an edit preference;
- active sub-agent tasks open while running;
- queued/pending tools normally cannot be toggled unless explicitly allowed;
- force-open supports navigation from another UI location;
- locked disclosures cannot be closed.

### 3. Heavy expanded bodies are deferred

Default-open bodies can defer mounting across animation frames, prioritizing the newest visible tools. This avoids freezing a long transcript.

### 4. Tool-specific bodies are registered

A registry maps tool names to renderers. Read/list/glob/grep, shell, edit, task/sub-agent, background process, web tools, and errors do not all show the same generic output.

### 5. Running sub-agent details stream

Expanded task tools subscribe to child-session visibility, show child tool rows, auto-scroll while running, and allow opening the child in a separate tab.

### 6. Status text transitions in place

`ToolStatusTitle` swaps/shimmers active and done labels without inserting another transcript row.

## PulseAI implementation now

The browser UI now implements the interaction model without reintroducing floating cards:

- flat `<details>` disclosures;
- chevron only for tools with usable details;
- queued tools are locked;
- approval/running/failure disclosures default open;
- Read details show path/range and preview;
- Edit details show compact diff and native-diff/reveal actions;
- Verify details show individual evidence states;
- tool results remain in the same transcript location;
- all disclosure controls use SVG icons;
- Playwright pins expansion, default-open edit behavior, and locked queued behavior.

## Pulse tool coverage

A catalog now maps all **36 current runtime tool names** to renderer families and default-open policy. A Python AST pin compares it with `src/tools/toolsets.py` and the browser tool decorators, so adding a runtime tool without a UI presentation fails tests.

Families: control, file read, file write/diff, search, terminal, background process, code execution, verification, web, browser, session, sub-agent, scaffold, and generic fallback.

The UI Lab now includes a **Tool Gallery** (development-only, not a third product surface) with the complete 34-name catalog and 13 specialized family examples. Search, web, browser, process, session, sub-agent, code/scaffold, verification, file and terminal disclosures each render family-appropriate detail bodies.

### Terminal example now implemented

`run_terminal` defaults open like Kilo's VS Code bash override and shows:

- exact command;
- terminal/host identity;
- exit code;
- bounded, scrollable ANSI-free output;
- passed/failed lines;
- copy-output and open-native-terminal actions.

The demo intentionally shows a failed authentication test, followed by the proposed edit, so the expanded terminal output explains why the agent is changing the file.

## Deferred for the real event reducer

- per-tool renderer registry driven by actual bridge tool names;
- deferred body mounting/virtualization for very long sessions;
- terminal output tailing and background-process structured fields;
- sub-agent child-session live subscription;
- force-open from Pulse Manager/checkpoint/verification navigation;
- persisted user preference for default-open terminal/edit tools;
- status label transition animation.

## Explicit non-adoptions

- Kilo activity timeline graph;
- visual graph of tool calls;
- Kilo branding or exact component styling;
- large monorepo/package architecture.
