# OpenCode Subagent Full Pipeline — Analysis from anomalyco/opencode

Source: https://github.com/anomalyco/opencode.git (cloned 2026-09-22 to /home/user/opencode)
Focus: full lifecycle of subagents including UI rendering.

---

## 1. High-level mental model

```
User Prompt → Parent Session (build/plan agent) → LLM decides to call `task` tool
    → task tool creates CHILD session (parentID = parent session)
    → child permission = parent deny + external_directory + todowrite/task denies
    → promptOps resolves prompt parts → prompt() runs child agent turn
    → child session emits SDK events → parent's tool part updates metadata {sessionId, background, toolCalls}
    → TUI reducer builds FooterSubagentTab + DetailState (80 commits cap)
    → Footer UI: subagent-menu → subagent inspector (14 rows) + scrollback
    → Web UI: task-tool-card with spinner/icon, clickable → navigates to child session
    → Background: BackgroundJob registry, inject synthetic <task> result back to parent
```

Two UIs share same event source but render differently.

---

## 2. Agent definitions

**File:** `packages/opencode/src/agent/agent.ts`

Schema:
```ts
Info = { name, description, mode: "subagent" | "primary" | "all", permission, model, prompt, color, hidden... }
```

Built-ins:

| name | mode | description | permission |
|------|------|-------------|------------|
| `build` | primary | default, executes tools based on permissions | `* allow`, question/plan_enter allow |
| `plan` | primary | disallows all edit tools | edit:* deny except .opencode/plans/*.md |
| `general` | subagent | multi-step parallel work | defaults + todowrite deny |
| `explore` | subagent | fast codebase explorer | * deny, grep/glob/list/bash/webfetch/websearch/read allow, external_directory readonly |
| `compaction` | primary hidden | prompt=compaction.txt | * deny |
| `title` | primary hidden | title gen | * deny |
| `summary` | primary hidden | summary gen | * deny |

User-defined agents in `opencode.json` → merged deep, `mode` can be `all` to be both.

**Config:** `cfg.subagent_depth` default 1 — max nesting depth. Checked in task tool by walking parent chain.

---

## 3. The `task` tool — spawn boundary

**File:** `packages/opencode/src/tool/task.ts` (14k)

**Parameters (Base):**
- `description: string` — 3-5 words
- `prompt: string` — task for subagent
- `subagent_type: string` — agent name (general/explore/custom)
- `task_id?: string` — resume existing subagent session
- `command?: string` — original command that triggered task
- `background?: boolean` — async launch (requires `OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true`)

**Execution steps in `TaskTool.execute`:**

1. **Depth check:**
```ts
let current=parent; depth=0; while(current.parentID){ depth++; current=get(current.parentID) }
if(depth >= cfg.subagent_depth) fail("Subagent depth limit reached")
```

2. **Permission ask:**
```ts
ctx.ask({ permission: "task", patterns: [subagent_type], always: ["*"], metadata:{description, subagent_type}})
```

3. **Resolve agent:**
```ts
next = agent.get(subagent_type) // throws if unknown
```

4. **Derive child permission:**
```ts
childPermission = deriveSubagentSessionPermission({parentSessionPermission: parent.permission, subagent: next})
childToolDenies = [
  todowrite deny if subagent doesn't allow todowrite,
  task deny if subagent doesn't allow task,
  experimental.primary_tools deny
]
permission = [...childPermission, ...childToolDenies filtered]
```
See `subagent-permissions.ts`:
```ts
deriveSubagentSessionPermission = parent denies + external_directory rules + todowrite/task deny if subagent lacks
```
This ensures parent restrictions (deny) always flow down, but subagent's own capabilities are respected.

5. **Create child session:**
```ts
sessions.create({ parentID: ctx.sessionID, title: description + " (@name subagent)", agent: next.name, permission })
```
Or reuse if `task_id` provided.

6. **Metadata on tool part:**
```ts
metadata = { parentSessionId, sessionId: child.id, model, background? }
ctx.metadata({title: description, metadata})
```

7. **Run logic (`runTask`):**
```ts
parts = resolvePromptParts(prompt)
result = prompt({ sessionID: child.id, model, variant, agent: next.name, parts })
if result.error → fail
if tool part error → fail
return last text part
```

8. **Background handling:**
- `BackgroundJob.Service` is instance-scoped wrapper over core registry.
- `extend` check: if already running (resume), return immediately with `running` output.
- `start` with `onPromote` callback that patches tool metadata to `background:true` + notifies.
- `notify` → `background.wait(jobID)` → `inject` synthetic text part to parent:
```ts
renderOutput = `<task id="${sessionID}" state="${state}"><summary>...</summary><${tag}>text</${tag}></task>`
```
- Foreground path: `raceFirst(wait(id), waitForPromotion(id))` — if promoted to background mid-flight, return backgroundResult instead of blocking.
- Abort handling: `ctx.abort` listener → `cancel(childSession)` + `background.cancel`

9. **Output:** `renderOutput` with XML wrapper — parent LLM sees `<task id=... state=completed>...</task>` and can summarize.

**JSON Schema:** When background experimental flag off, `jsonSchema = ToolJsonSchema.fromSchema(BaseParameters)` (no background param) to hide from LLM.

---

## 4. Session hierarchy

**File:** `packages/opencode/src/session/session.ts`

- `Info.parentID?: SessionID` — child points to parent
- `Info.agent?: string` — which agent runs it
- `isDefaultTitle` regex: `New session - <iso>` or `Child session -`
- `fromRow/toRow` maps DB rows (drizzle-orm sqlite) to Info.
- `CreateInput` allows parentID, title, agent, permission.
- Children queried via `parentID` filter, non-archived sorted by created desc — used in web UI to find task session:
```ts
taskSession = sessions.filter(s=>s.parentID===parentID && title.startsWith(description) && title.includes(@Agent)).sort(created desc)[0]
```

**Prompt execution:** `packages/opencode/src/session/prompt.ts` (~1000 lines)

- Creates assistant message with `finish="tool-calls"`, cost 0 initially.
- Creates tool part: `type:"tool", tool:"task", state:{status:"running", input:{prompt, description, subagent_type, command}, time:{start}}`
- `plugin.trigger("tool.execute.before")`
- Calls `taskTool.execute` via Effect.
- On interrupt: marks assistant finish, updates tool part to error "Cancelled".
- On success: updates part to `completed` with `output`, `title`, `metadata`, `attachments`.
- On failure: `error` state.
- `plugin.trigger("tool.execute.after")`
- If `task.command` present, injects synthetic user part "Summarize the task tool output above and continue".

This is the server-side source of truth — both TUI and web subscribe via SDK events.

---

## 5. BackgroundJob registry

**File:** `packages/opencode/src/background/job.ts` → core `packages/core/src/background-job`

Interface:
- `list()`, `get(id)`, `start({id, type, title, metadata, onPromote, run: Effect})`, `extend({id, run})`, `wait({id})`, `waitForPromotion(id)`, `promote(id)`, `cancel(id)`

- Registry keeps job status: running/completed/error/cancelled + output/error + metadata (sessionId, background flag)
- `start` stores job, forks `run` effect, `onPromote` runs when job promoted to background (user pressed background key).
- TUI uses `wait` to block foreground task tool until child completes, but also listens for promotion to switch UI.

---

## 6. TUI Pipeline (opencode --mini)

**Architecture doc:** `types.ts` header explains two-lane model:

```
SDK events → session-data reducer → StreamCommit[] + FooterOutput
  → stream.ts bridges to footer API
    → footer.ts queues commits and patches footer view
      → OpenTUI split-footer renderer
```

### 6.1 Types

**File:** `packages/opencode/src/cli/cmd/run/types.ts`

- `FooterSubagentTab`: `sessionID, partID, callID, label (Titlecased subagent_type), description, status: running|completed|cancelled|error, background?, title?, toolCalls?, lastUpdatedAt`
- `FooterSubagentState`: `tabs[], details: Record<sessionID, {sessionID, commits[]}> , permissions[], questions[]`
- `FooterView`: `prompt | permission | question`
- `FooterPromptRoute`: `composer | queued-menu | subagent-menu | subagent (sessionID) | command | skill | model | variant`
- `StreamCommit`: `kind: system|user|assistant|reasoning|tool|error, text, phase: start|progress|final, source, messageID, partID, tool, part?: ToolPart, toolState, toolError, shell?`

### 6.2 subagent-data.ts

**File:** `packages/opencode/src/cli/cmd/run/subagent-data.ts`

- Constants: `SUBAGENT_BOOTSTRAP_LIMIT 200`, `SUBAGENT_CALL_BOOTSTRAP_LIMIT 80`, `SUBAGENT_COMMIT_LIMIT 80`, `SUBAGENT_CALL_LIMIT 32`
- `SubagentData`: `tabs: Map<sessionID, Tab>, details: Map<sessionID, {data: SessionData, frames: {key, commit}[]}>`
- Helpers:
  - `taskTab(part, sessionID)`: label = titlecase(subagent_type), description = input.description or title or inputLabel, status = `taskStatus(part)` (completed/error/cancelled/running via metadata), `background = metadata.background===true`, `toolCalls = metadata.toolcalls|toolCalls|calls`, `lastUpdatedAt = time.end||start||now`
  - `taskSessionID(part)`: metadata.sessionId or sessionID
  - `syncTaskTab`: updates tabs Map from tool part, ensures detail exists
  - `compactToolPart`: strips to id/type/sessionID/messageID/callID/tool/state compacted (no huge output)
  - `frameKey(commit)`: `kind:partID:phase` or `kind:messageID:phase` or `kind:phase:text`
  - `mergeLiveCommit`: if both progress and same kind/source/partID/tool → concat text
  - `appendCommits`: merges into frames, caps to 80
  - `bootstrapSubagentInput`: replays historical messages (200 limit) to build initial tabs/details
  - `sameSubagentTab` equality check to avoid re-render

### 6.3 session-data.ts reducer

- `createSessionData({includeUserText})`
- `reduceSessionData(event)`: handles `message.updated`, `message.part.delta`, `message.part.updated`, `permission.*`, `question.*`, `session.error`, `session.next.shell.*`
- For tool parts, creates `toolCommit` with `toolStatus(part)` → "running shell" etc.
- Emits `FooterOutput` with `subagent` state when task tool updates.
- `flushInterrupted` emits interrupted finals on abort.

### 6.4 Footer UI

**File:** `packages/opencode/src/cli/cmd/run/footer.ts` (RunFooter class)

- Owns scrollback (immutable) + footer (mutable)
- `append(commit)`: coalesces consecutive progress chunks same partID → concat text, queueMicrotask flush
- `event(next: FooterEvent)`: handles `stream.subagent` → `setSubagent(state)` + `applyHeight()`
- `applyHeight()`: if `promptRoute.type === "subagent"` → `base + SUBAGENT_INSPECTOR_ROWS (14)` else base + textarea rows etc.
- `promptRoute` drives which footer view is active.

**File:** `footer.subagent.tsx`

```tsx
export const SUBAGENT_INSPECTOR_ROWS = 14
statusColor: completed→highlight, cancelled→muted, error→error, running→highlight
statusIcon: completed ●, cancelled ○, error ◍, running ◔ (spinner)
RunFooterSubagentBody:
  - header: spinner if running else icon, title (description||title||label), subtitle if different, "index of total" if >1
  - scrollbox sticky bottom, scrollbar track
  - rows = commits.map(RunEntryContent) with separatorRows gap logic
  - keyboard: esc → onClose, tab → onCycle(1), up/k → scroll -1, down/j → scroll +1
```

**File:** `footer.prompt.tsx`, `footer.view.tsx`

- Prompt autocomplete includes `@agent` mentions (agents filtered `!hidden && mode !== primary`)
- `FooterPromptRoute` subagent-menu lists tabs, subagent inspector shows detail
- `onSubagentSelect` callback from lifecycle → sets route

**File:** `runtime.lifecycle.ts`

- Boots `createCliRenderer` with `screenMode: split-footer`, `footerHeight: FOOTER_HEIGHT`, `externalOutputMode: capture-stdout`
- Creates `RunFooter` with `onSubagentSelect`
- Handles SIGINT → `footer.requestExit()`
- `close()` flushes, writes exit splash, destroys renderer

---

## 7. Web App Pipeline (app)

**File:** `packages/app/src/pages/session/timeline/message-timeline.tsx`

- `taskDescription(part, sessionID)` extracts metadata.sessionId match
- Title label strips ` (@... subagent)` suffix: `replace(/\s+\(@[^)]+ subagent\)$/, "")`

**File:** `packages/session-ui/src/components/message-part.tsx`

Core rendering:

- `getToolInfo(tool, input, metadata)`: for `task`, icon="task", title=agentTitle(i18n, Capitalized subagent_type), subtitle=input.description
- `taskAgent(raw, list)`: finds agent in list, resolves color via `agentPalette` hash or theme colors, returns {name, color, v2Color}
- `taskSession(input, parentID, sessions, agents)`: finds child session by parentID + title prefix + agent name, sort by created desc
- `PART_MAPPING["tool"] = ToolPartDisplay`:
  - For task: `taskId = metadata.sessionId || taskSession(...)`, `taskHref = sessionLink(taskId)`, `taskSubtitle = description || taskId`
  - Renders `BasicTool` with `subtitle`, `href`, `onSubtitleClick` → `navigateToSession(id)` if available
  - Clickable if session exists

- `ToolRegistry.register({name:"task", render})`:
  - `childSessionId = metadata.sessionId || taskSession(...)`
  - `agent = taskAgent(subagent_type, agents)`, `title = agent.name`, `tone = color`
  - `subtitle = description (+ " (background)" if background)`
  - `running = status pending|running`
  - `trigger = <div data-component="task-tool-card" style="--task-agent-color">`
    - `task-tool-surface` → `task-tool-icon` (subagent icon) or spinner (SessionProgressIndicatorV2 or Spinner)
    - `task-tool-title` = agent name
    - `task-tool-subtitle` = description
    - `task-tool-action` → external link icon if clickable
  - Returns `BasicTool` with `icon="task"`, `status`, `trigger`, `href`, `clickable`

**File:** `basic-tool.tsx`

- `BasicTool` props: icon, status pending|running, trigger (title/subtitle/args/action), hideDetails, defaultOpen, open, defer, animated, etc.
- Deferred mount queue: `deferredMounts` array, `requestAnimationFrame` flush, pop from end so bottom tools become interactive first
- Collapsible with spring animation `visualDuration 0.35`, `animate(height auto)`
- Trigger renders title with `TextShimmer` active when pending
- Subtitle clickable for subagent navigation

**File:** `rows.ts` / `projection.ts`

- `Timeline.constructSessionMessageRows`: groups user message + assistant messages, handles compaction, interrupted, thinking, diff summary, error
- `groupParts` groups consecutive context tools (read/glob/grep/list) into context group
- `TimelineRow` types: UserMessage, AssistantPart, TurnGap, CommentStrip, TurnDivider (compaction/interrupted), Thinking, Retry, DiffSummary, Error
- Subagent tasks are just tool parts inside AssistantPart — no special row, but their clickable card links to child session timeline

**Navigation:**
- `sessionHref` from context, `navigateToSession` prop → client-side router to child session page
- Child session page shows its own timeline (same projection), with back to parent via parentID breadcrumb

---

## 8. SDK Events (client/src/generated/types.ts, server)

Events driving UI:
- `message.updated` — role, model, usage
- `message.part.delta` — streaming text
- `message.part.updated` — tool state transitions (pending→running→completed/error), metadata updates (sessionId, toolCalls)
- `permission.updated`, `question.updated`
- `session.next.shell.started/ended`
- `session.error`

Both TUI and web subscribe via `OpencodeClient.session.subscribe` (SSE).

---

## 9. Config & Permissions

- `opencode.json`:
```json
{
  "subagent_depth": 2,
  "permission": {"task": {"*": "allow"}},
  "agent": {
    "my-explorer": {"mode": "subagent", "description": "...", "permission": {"*": "deny", "read": "allow"}, "color": "blue"}
  },
  "experimental": {"primary_tools": ["write", "edit"], "background_subagents": true}
}
```
- `OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true` enables background flag
- Permission ruleset: array of `{permission, pattern, action: allow|ask|deny}` — parent deny + external_directory always inherited

---

## 10. E2E Tests

- `packages/app/e2e/regression/subagent-child-navigation.spec.ts` — verifies clicking task card navigates to child session, child timeline renders
- `packages/app/e2e/performance/timeline/...` — timeline stress with subagents
- `packages/opencode/test/cli/run/footer.view.test.tsx` — footer view state with subagent tabs

---

## 11. Comparison with CrusorAI (PulseAIRepo)

**Current CrusorAI subagent:**

- `src/agents/sub_agent.py`: `SubAgentCoordinator.spawn(mode, task, parent_thread_id)` → `invoke_agent(message=focused_task, thread_id=agent_id)` synchronously inside tool call, result capped 2000 chars, pop-on-read registry capped 50. `spawn_batch` uses ThreadPoolExecutor + contextvars, index-ordered results.
- `src/agents/subagent_lifecycle.py`: managed lifecycle with handles, token verification, cancellation via `turn_controls.cancel`
- `src/graphs/chat_graph.py`: `delegate_to_subagent` and `delegate_to_subagent_batch` tools, parallel_tools conflict detection, D32 file-state guard
- Bridge: `subagent_launch`, `subagent_status`, `subagent_cancel`, `subagent_result` frames → `subagent_updated` events to desktop
- Desktop: `crusorAIRenderer.ts` parts timeline (text|tool|reasoning) interleaved, but no dedicated subagent inspector yet
- Missing vs opencode:
  - No child session persistence (opencode stores child session in DB with parentID, Crusor uses in-memory registry)
  - No permission inheritance derivation (Crusor has scope_capabilities tuple, but not deny+external_directory merge)
  - No background job registry with promotion + synthetic inject
  - No subagent-menu / inspector 14-row UI in TUI
  - No clickable task-tool-card linking to child session timeline in webview

**What to steal:**

1. **Session model:** Store child sessions with parentID in `~/.crusorai/sessions.db` (already has checkpoint), title `@agent subagent`, permission derived via `deriveSubagentSessionPermission` logic.
2. **Task tool metadata:** Always emit `metadata: {sessionId, toolCalls, background}` on tool part updates — enables UI to link.
3. **SubagentData reducer:** Implement `tabs Map` + `details Map` with 80 commit cap, frameKey merging, compactToolPart to avoid huge outputs in parent context.
4. **Footer UI:** Add `FooterPromptRoute: subagent-menu | subagent` and inspector component similar to `footer.subagent.tsx` with spinner, status colors, scrollbox sticky bottom, esc/tab navigation.
5. **Web task card:** In `crusor-webview/src/a2ui/renderers.tsx`, render task tool as card with `--task-agent-color`, spinner when running, clickable href to child session (if using AG-UI, need session route).
6. **Background:** Add `BackgroundJob` service with `start/wait/waitForPromotion/promote/cancel`, inject `<task id state>` synthetic result.
7. **Depth guard:** Walk parent chain, enforce `subagent_depth` config (opencode default 1, same as Crusor current).

---

## 12. File Map (opencode repo)

| File | Role |
|------|------|
| `packages/opencode/src/agent/agent.ts` | Agent registry, built-in subagents |
| `packages/opencode/src/agent/subagent-permissions.ts` | Derive child permission |
| `packages/opencode/src/tool/task.ts` | Task tool spawn, background, depth, permission ask |
| `packages/opencode/src/session/session.ts` | Session create/get with parentID |
| `packages/opencode/src/session/prompt.ts` | Prompt execution, tool part lifecycle |
| `packages/opencode/src/background/job.ts` | Background job registry |
| `packages/opencode/src/cli/cmd/run/types.ts` | FooterSubagentTab, FooterSubagentState, StreamCommit |
| `packages/opencode/src/cli/cmd/run/subagent-data.ts` | Tabs+details reducer, frame merging, 80 cap |
| `packages/opencode/src/cli/cmd/run/session-data.ts` | SDK event → commits + footer output |
| `packages/opencode/src/cli/cmd/run/footer.ts` | RunFooter class, split-footer, subagent event handling |
| `packages/opencode/src/cli/cmd/run/footer.subagent.tsx` | Inspector UI, 14 rows, spinner, keyboard |
| `packages/opencode/src/cli/cmd/run/footer.prompt.tsx` | Prompt input, @agent mentions, slash commands |
| `packages/opencode/src/cli/cmd/run/runtime.lifecycle.ts` | Boot renderer, create RunFooter, SIGINT |
| `packages/session-ui/src/components/message-part.tsx` | getToolInfo, taskAgent, taskSession, ToolPartDisplay, ToolRegistry task card |
| `packages/session-ui/src/components/basic-tool.tsx` | Collapsible tool UI, deferred mounts, shimmer |
| `packages/app/src/pages/session/timeline/rows.ts` | Timeline row construction |
| `packages/app/src/pages/session/timeline/projection.ts` | Timeline projection memo |
| `packages/app/src/pages/session/timeline/message-timeline.tsx` | Task description extraction, timeline render |
| `packages/app/e2e/regression/subagent-child-navigation.spec.ts` | E2E for child navigation |

---

## 13. Minimal reproduction

```bash
# Clone
git clone https://github.com/anomalyco/opencode.git /tmp/opencode
cd /tmp/opencode

# Run TUI with demo subagent
OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true bun run packages/opencode/src/cli/cmd/run.ts -- --agent build
# In prompt: "Use @explore to find how task tool works and @general to summarize"

# Observe:
# - task tool parts appear with spinner
# - footer shows subagent-menu (tab to cycle)
# - footer.subagent inspector shows 14-row scrollbox with child commits
# - child session created with parentID, navigable via click (web) or tab (TUI)
```

---

**End of analysis.**
