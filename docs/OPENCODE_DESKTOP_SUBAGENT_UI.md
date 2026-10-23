# OpenCode Desktop UI — Subagent Pipeline (no TUI)

> **Status:** upstream reference snapshot from 2026-09-22, not current Crusor
> behavior. Use [`DESIGN/SUBAGENT_PARITY_AUDIT.md`](DESIGN/SUBAGENT_PARITY_AUDIT.md)
> plus its 2026-10-23 correction for Crusor parity.

Source: `anomalyco/opencode` cloned 2026-09-22 to `/home/user/opencode`
Scope: **Desktop only** — Electron + SolidJS web app (`packages/app` + `packages/session-ui` + `packages/desktop`)

---

## 1. Desktop Architecture

```
Electron main (packages/desktop/src/main)
  ├── sidecar.ts → spawns opencode server (binary, bun)
  ├── server.ts → manages server lifecycle, port, auth
  ├── window-registry.ts + windows.ts → BrowserWindow per workspace
  └── ipc.ts → bridge to renderer

Renderer (packages/desktop/src/renderer)
  ├── index.tsx → mounts @opencode-ai/app (SolidJS SPA)
  └── preload/index.ts → exposes platform APIs (checkAppExists, open, etc.)

App (packages/app/src)
  ├── context/global-sync/* → sync store: sessions, messages, parts, permissions, questions
  ├── context/sync.tsx → useSync() accessor
  ├── context/server-sync.tsx → ensures DirSyncContext, trimSessions, childSessions handling
  ├── pages/session/
  │   ├── session-layout.ts → useSessionKey(), useSessionLayout() (tabs, view)
  │   ├── composer/session-composer-region-controller.ts → parentID detection, child UI lock
  │   ├── composer/session-composer-region.tsx → renders permission/question/todo docks + prompt or child disabled UI
  │   └── timeline/message-timeline.tsx → virtualized timeline, Task card rendering via session-ui
  └── components/titlebar-tab-strip.tsx → tab strip, drag-drop, visibility

Session-UI (packages/session-ui/src/components)
  ├── message-part.tsx → PART_MAPPING["tool"] ToolPartDisplay + ToolRegistry task card
  ├── basic-tool.tsx → collapsible tool UI, deferred mounts, shimmer
  └── basic-tool.css → task-tool-card styles
```

All subagent state comes from **server SDK events** over SSE/WebSocket, stored in `sync` store, then projected to timeline rows.

---

## 2. Session Model for Subagents

**File:** `packages/opencode/src/session/session.ts` (server) + client types `packages/client/src/generated/types.ts`

- `Session.info.parentID?: string` — child points to parent
- Created by `task` tool: `title = "${description} (@${agent} subagent)"`, `agent = subagent_type`, `permission = derived`
- `session.created` event → `event-reducer.ts`:
  - If `!info.parentID` → `sessionTotal++`
  - Child sessions kept even if parent archived? `trimSessions` keeps children when root kept, permission exists, or child recent (see `session-trim.test.ts`)
- `home-session-index.ts`: `if (item.parentID || archived) return []` — **home list hides children** (only root sessions shown in home)
- `server-sync.tsx`: `childSessions = store.session.filter(s => !!s.parentID)` then merged into trim logic

**Client sync:**
- `useSync().session.get(id)` → cached session
- `useSync().session.lineage.peek(id)` → peek without fetch
- `createSessionLineage(sessionID, lineage)` → reactive lineage that resolves via `lineage.resolve(id)`, throws `sessionNotFoundError` if settled missing (child deleted)

**File:** `packages/app/src/pages/session/composer/session-request-tree.ts`
```ts
// Build parentID -> childID map
map = sessions.reduce((acc, item) => {
  if (!item.parentID) return acc
  (acc.get(item.parentID) ?? set).push(item.id)
  return acc
}, Map)
// BFS to collect all descendants
```
Used to bubble child permission/question requests up to parent composer.

---

## 3. Composer Region — Child Session Lock

**File:** `session-composer-region-controller.ts`

```ts
parentID = createMemo(() => sync().session.get(sessionID())?.parentID)
child = () => !!parentID()
showComposer = () => !state.blocked() || !!parentID()
```

**File:** `session-composer-region.tsx`

```tsx
<Show when={child()} fallback={<Show when={!blocked()}>{promptInput}</Show>}>
  <div class="rounded-[12px] border bg-background-base p-3 text-16-regular text-text-weak">
    <span>{t("session.child.promptDisabled")} </span>
    <Show when={parentID()}>
      <button onClick={openParent}>{t("session.child.backToParent")}</button>
    </Show>
  </div>
</Show>
```

- When viewing a child session (subagent), prompt is **disabled** — you can't prompt a subagent directly from desktop; you view its transcript only.
- "Back to Parent" button navigates to parent session via `openParent` (uses `sessionHref`).
- Permission/question docks still show child requests bubbled via request-tree.

**File:** `session-composer-state.ts` tests:
- `sessionPermissionRequest` prefers current session permission, else nested child permission (DFS through parentID map)
- Same for `sessionQuestionRequest`

---

## 4. Task Tool Card — Desktop UI Rendering

### 4.1 Data extraction

**File:** `packages/session-ui/src/components/message-part.tsx`

```ts
function taskAgent(raw, list): {name, color, v2Color}
  - list = data.store.agent (agents from server)
  - find agent by name (case-insensitive)
  - color = agentColor(item.color, theme) ?? agentTones[key] ?? hashPalette(key)
  - v2Color = v2AgentThemeColors or v2Tone

function taskSession(input, parentID, sessions, agents): sessionID
  - filter sessions where parentID==parentID && !archived && title startsWith description && title includes @Agent
  - sort by created desc, return first id

getToolInfo(tool, input, metadata):
  case "task": icon="task", title=agentTitle(i18n, Capitalized subagent_type), subtitle=input.description
```

**ToolPartDisplay (PART_MAPPING["tool"]):**
```ts
taskId = metadata.sessionId (from server) || taskSession(...)
taskHref = sessionLink(taskId, data.sessionHref)
taskSubtitle = description || taskId
// Click handler:
onSubtitleClick = (e) => {
  if (!navigateToSession) return
  if (e.button!==0 || alt/ctrl/meta/shift) return
  e.preventDefault()
  navigateToSession(taskId)
}
```

Renders `ToolRegistry.render(tool)` or `GenericTool` fallback.

### 4.2 Task card component

**File:** `message-part.tsx` `ToolRegistry.register({name:"task"})`

```tsx
childSessionId = metadata.sessionId || taskSession(...)
agent = taskAgent(subagent_type, agents)
title = agent.name ?? "Agent"
tone = agent.color (legacy), v2Tone = v2Color
subtitle = description (+ " (background)" if metadata.background)
running = status pending|running
href = sessionLink(childSessionId)
clickable = !!childSessionId && (navigateToSession || href)

trigger = <div data-component="task-tool-card" style="--task-agent-color: v2Tone(), --task-agent-legacy-color: tone()">
  <div data-component="task-tool-surface">
    <div data-slot="basic-tool-tool-info-structured">
      <div data-slot="basic-tool-tool-info-main">
        <Show when={running()} fallback={<Show when={newLayout()}><Icon name="subagent" /></Show>}>
          <span data-component="task-tool-spinner" style="color: tone()">
            <Show when={newLayout()} fallback={<Spinner />}>
              <SessionProgressIndicatorV2 style="color: v2Tone()" />
            </Show>
          </span>
        </Show>
        <span data-component="task-tool-title">{title}</span>
        <Show when={subtitle()}><span data-slot="basic-tool-tool-subtitle">{subtitle}</span></Show>
      </div>
    </div>
  </div>
  <Show when={clickable()}><div data-component="task-tool-action"><Icon name="square-arrow-top-right" /></div></Show>
</div>

return <BasicTool icon="task" status={status} trigger={trigger()} hideDetails triggerAsLink triggerHref={href()} clickable={clickable()} onTriggerClick={navigate} onTriggerKeyDown={navigateKey} />
```

- **Running:** spinner (`SessionProgressIndicatorV2` in v2 layout, `Spinner` in legacy) colored by agent tone
- **Completed:** subagent icon
- **Subtitle:** description, or sessionId if no description, plus "(background)" if background
- **Clickable:** if child session exists, entire card is link + shows external arrow on hover, keyboard Enter/Space navigates
- `hideDetails` = true — no collapsible body (unlike bash/read tools), card is self-contained

### 4.3 CSS

**File:** `basic-tool.css` lines 173-360

Legacy layout:
```css
[task-tool-card] {
  width:100%; display:flex; gap:8px; padding:8px 12px; border-radius:6px;
  border:0.5px solid var(--border-weak-base); background: color-mix(bg-base 92%, transparent);
  transition: border-color, background, color 0.15s;
  [task-tool-surface] { flex:1; gap:8px; }
  [task-tool-title] { font-size:14px; font-weight:medium; color: var(--task-agent-legacy-color); text-transform:capitalize; }
  [basic-tool-tool-subtitle] { color: var(--v2-text-text-base); }
  [task-tool-action] { opacity:0; transition: opacity 0.15s; color: var(--v2-text-text-faint); margin-left:auto; }
  &:hover { background: bg-stronger 88%; [task-tool-action]{opacity:1} }
}
```

V2 layout (`body[data-new-layout]`):
```css
[task-tool-card] { gap:8px; padding:0; border:0; background:transparent;
  [task-tool-surface] { padding:8px 12px; border-radius:8px; background: var(--v2-background-bg-layer-01); }
  [task-tool-icon] [icon] { color: var(--task-agent-color); }
  [task-tool-title] { height:20px; font: Inter 13px weight 530 line-height 20px letter-spacing -0.04px; color: var(--v2-text-text-base); }
  [basic-tool-tool-subtitle] { font: Inter 13px weight 440; color: var(--v2-text-text-base); }
  [session-progress-indicator-v2] { color: var(--task-agent-color); }
}
```

Variables:
- `--task-agent-color` = v2 tone (e.g. blue, green from `v2AgentThemeColors` or `v2AgentTones[explore]=?`)
- `--task-agent-legacy-color` = legacy palette hash

Hover reveals `task-tool-action` arrow, indicating navigation to child session.

---

## 5. Timeline & Virtualization

**File:** `packages/app/src/pages/session/timeline/message-timeline.tsx`

- Uses `@tanstack/solid-virtual` with `createVirtualizer`, `defaultRangeExtractor`, `elementScroll`
- `timelineFallbackItemSize = 60`, measurements cached per sessionID in `timelineCache` Map
- `taskDescription(part, sessionID)` helper: checks `metadata.sessionId === sessionID` then returns `description`
- Rows from `rows.ts` `Timeline.constructSessionMessageRows`:
  - Groups user + assistant messages, handles compaction, interrupted, thinking, diff summary, error
  - `groupParts` groups consecutive context tools (read/glob/grep/list) into context group
  - Subagent tasks are **not** special rows — they are tool parts inside `AssistantPart` group, rendered as task-tool-card

**Virtualization for subagents:**
- Child session has its own timeline (same projection), no parent transcript mixed
- Parent timeline shows only task card, not child commits (child commits live in child session page)
- Clicking task card navigates to `/session/:childID` route (via `sessionHref` or `navigateToSession`)

---

## 6. Titlebar & Navigation

**File:** `titlebar-tab-strip.tsx`

- Tabs are `SessionTab` or `DraftTab`, drag-drop via `@dnd-kit/solid`
- Visibility tracked via `visibility[tabKey]` store, `visibleTabs = tabs.filter(draft || visibility[tabKey])`
- Child sessions **do not** automatically get top tabs — they appear only when navigated (via task card or direct URL)
- `selectAdjacentTab` cycles with `mod+option+ArrowLeft/Right` or `ctrl+tab`
- Session rename: `sdk.api.session.rename({sessionID, title})` with optimistic `sync.session.remember`

**File:** `session-layout.ts`

```ts
useSessionKey = () => {
  params = useParams() // {dir, id}
  sdk = useSDK()
  serverSDK = useServerSDK()
  scope = serverSDK().scope
  directory = base64Encode(sdk().directory)
  workspaceKey = SessionStateKey.from(scope, Route.fromRoute(directory))
  sessionKey = SessionStateKey.from(scope, Route.fromRoute(directory, params.id))
  return {params, sessionKey, workspaceKey}
}
```

- `sessionKey` drives `DirectoryDataProvider` which pins session lineage (exempt from cache pruning)
- Child session pinned when viewed, so lineage missing after settlement = deleted (throws `sessionNotFoundError`)

---

## 7. Notification & Permission Handling for Subagents

**File:** `packages/app/src/context/notification.tsx`

```ts
if (session.parentID) return // don't notify for child sessions
if (session?.parentID) return // don't show toast for child
```

- Desktop notifications only for root sessions — subagent completions silent (parent already shows task card status)

**File:** `permission.tsx` + `session-request-tree.ts`

- Permission requests bubble: if child session has pending permission, parent composer shows it via `sessionPermissionRequest` that walks parentID map
- Same for questions

---

## 8. Side Panel & File Tree

**File:** `session-side-panel.tsx`

- Shows diffs (review), file tree, context usage
- For subagent child sessions, file tree shows same workspace (child inherits directory)
- No special subagent UI in side panel — focus is timeline

---

## 9. Electron Main — Server Management

**File:** `packages/desktop/src/main/server.ts` + `sidecar.ts`

- Spawns `opencode` binary (or `bun` in dev) with env, port, directory
- Manages lifecycle, restart on crash, logging via `electron-log`
- `background-cli.ts` handles background subagent processes? Actually background jobs run inside server process (Effect)

---

## 10. End-to-End Desktop Flow

```
1. User prompt in composer (SessionComposerRegion)
   ↓
2. LLM calls task tool → server creates child session (parentID = parent)
   → permission derived, title "desc (@agent subagent)"
   → SDK event session.created (parentID) → sync store adds child, but home index hides it
   ↓
3. Server runs child agent, emits message.part.updated for task tool part:
   metadata = {sessionId: childID, toolCalls: n, background?: bool}
   status: pending → running → completed/error
   ↓
4. App sync reducer merges part, timeline re-renders:
   - ToolPartDisplay extracts taskId from metadata.sessionId
   - Task card shows spinner (running) or subagent icon (completed)
   - Card colored by agent (hash or configured color)
   - Clickable → sessionLink(childID) → navigateToSession(childID)
   ↓
5. Click task card:
   - router navigates to /session/:childID
   - useSessionKey resolves child session via lineage (peek or resolve)
   - SessionComposerRegionController detects parentID → shows disabled prompt + Back to Parent button
   - Timeline shows child transcript (virtualized)
   - Permission/question docks show child requests if any (bubbled)
   ↓
6. Back to Parent button:
   - navigates to parentID route
   - parent timeline still shows task card with completed status
   ↓
7. Background subagent:
   - If background=true, task card subtitle shows " (background)"
   - Parent prompt not blocked, can continue
   - When child completes, server injects synthetic <task> result to parent
   - Parent timeline appends tool output, task card status → completed
```

---

## 11. Key Files (Desktop Only)

| File | Role |
|------|------|
| `packages/desktop/src/main/sidecar.ts` | Spawn opencode server |
| `packages/desktop/src/main/server.ts` | Server lifecycle |
| `packages/app/src/context/sync.tsx` | Sync store accessor |
| `packages/app/src/context/global-sync/event-reducer.ts` | session.created/deleted, parentID handling, sessionTotal |
| `packages/app/src/context/global-sync/home-session-index.ts` | Hides parentID sessions from home |
| `packages/app/src/pages/session/composer/session-composer-region-controller.ts` | parentID memo, child() boolean, back navigation |
| `packages/app/src/pages/session/composer/session-composer-region.tsx` | Renders disabled prompt for child + Back button |
| `packages/app/src/pages/session/composer/session-request-tree.ts` | ParentID → childID map, BFS descendants for permission bubbling |
| `packages/session-ui/src/components/message-part.tsx` | taskAgent(), taskSession(), getToolInfo(task), ToolPartDisplay, ToolRegistry task card |
| `packages/session-ui/src/components/basic-tool.tsx` | Collapsible tool, deferred mounts, shimmer, BasicTool props |
| `packages/session-ui/src/components/basic-tool.css` | task-tool-card styles, v2 vs legacy, hover action |
| `packages/app/src/pages/session/timeline/message-timeline.tsx` | Virtualizer, taskDescription, timeline render |
| `packages/app/src/pages/session/timeline/rows.ts` | Timeline row construction, groupParts |
| `packages/app/src/components/titlebar-tab-strip.tsx` | Tab strip, child sessions not auto-tabbed |
| `packages/app/src/context/notification.tsx` | Filters parentID sessions from notifications |

---

## 12. What CrusorAI Should Copy for Desktop

1. **Child session persistence** with parentID in DB, title `@agent subagent`, hidden from home list
2. **Task card metadata** `sessionId` + `toolCalls` + `background` always emitted on tool part updates
3. **Clickable card** with agent color (`--task-agent-color` CSS var), spinner vs icon, external arrow on hover, keyboard nav
4. **Child view lock**: composer disabled when `parentID` exists, show Back to Parent button
5. **Permission bubbling** via parentID map DFS — child permission/question requests show in parent composer
6. **No notification for child** — parent card status enough
7. **Virtualized timeline per session** — child has own timeline, not inline in parent

---

End.
