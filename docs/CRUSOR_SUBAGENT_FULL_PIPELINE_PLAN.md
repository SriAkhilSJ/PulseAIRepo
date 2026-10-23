# Crusor Subagent Full Pipeline — Implementation Plan (Desktop Focus)

> **Status:** historical pre-implementation plan. The referenced webview was
> later deleted and the native/sub-agent implementation evolved substantially.
> Use [`DESIGN/SUBAGENT_PARITY_AUDIT.md`](DESIGN/SUBAGENT_PARITY_AUDIT.md) for
> the dated parity record and [`PERMISSIONS.md`](PERMISSIONS.md) for current
> approval behavior.

**Date:** 2026-09-22
**Source analysis:** `anomalyco/opencode` desktop UI (packages/app + session-ui + desktop) + Crusor current (`src/agents/sub_agent.py`, `subagent_lifecycle.py`, `chat_graph.py`, bridge, `crusorAIRenderer.ts`, `crusor-webview`)
**Author:** Arena agent
**Status:** Draft plan, no code yet — careful implementation

> **Careful note:** This plan deliberately avoids TUI. Only Desktop IDE (VSCode workbench contrib) + CopilotKit webview (hermes-ui) are in scope. Every change is behind a feature flag and preserves existing depth=1, capability-token, and event-bus contracts.

---

## 0. Goals / Non-Goals

### Goals
- Full OpenCode-like subagent pipeline inside Crusor:
  - Child session with `parentID`, persistent in `~/.crusorai/sessions.db` (LangGraph checkpoint) + journal
  - Permission inheritance: parent DENY + external_directory always flows down (OpenCode `deriveSubagentSessionPermission`)
  - Tool metadata: `sessionId`, `toolCalls`, `background` on every `delegate_to_subagent` part update
  - Background jobs with promotion + synthetic `<task>` inject back to parent
  - Desktop workbench UI: task-tool-card (agent color, spinner vs icon, clickable → child), child view lock (prompt disabled + Back to Parent), permission bubbling, no notification for child
  - Webview UI: same card in `hermes-ui/components/tool-card.tsx` / `a2ui/renderers.tsx`, clickable navigation to child transcript
  - Config: `subagent_depth` (default 1, same as today), `CRUSORAI_EXPERIMENTAL_BACKGROUND_SUBAGENTS`

### Non-Goals
- No TUI footer (OpenCode TUI `footer.subagent.tsx` 14-row inspector) — desktop equivalent is a subagent list panel + card navigation
- No breaking change to existing `subagent_updated` event shape — additive fields only
- No auto-tab for child sessions in titlebar (OpenCode also doesn't) — navigation only via card
- No change to LLM provider routing, no new provider
- No deletion of existing `SubAgentCoordinator` pop-on-read registry — extend it, keep cap 50

---

## 1. Current Crusor State — Gaps vs OpenCode Desktop

| Area | Crusor Today | OpenCode Desktop | Gap |
|------|--------------|------------------|-----|
| Session model | `thread_id = sub-{mode}-{6hex}`, in-memory `_active_agents` dict, pop-on-read, cap 50, no parentID persistence | `Session.info.parentID`, SQLite row, title `@agent subagent`, sorted by created desc | No persistence, no navigation, orphan risk on crash |
| Permission | `allowed_capabilities` tuple checked against `KNOWN_CAPABILITIES`, child may not broaden parent | `deriveSubagentSessionPermission`: parent deny + external_directory + todowrite/task deny if subagent lacks | No deny inheritance, no external_directory readonly merge |
| Tool | `delegate_to_subagent(mode, task, config)` → `spawn()` sync, result capped 2000 chars, batch via ThreadPool | `task` tool with `description`, `prompt`, `subagent_type`, `task_id` (resume), `background`, metadata `sessionId`, `toolCalls`, `background` | No description, no sessionId metadata, no resume, no background, result cap but no compactToolPart |
| Background | `SubagentLifecycleService` has ThreadPool max 4, state PENDING/RUNNING/SUCCEEDED/FAILED/CANCELLED, HMAC token verification, emits `subagent.updated` | `BackgroundJob` registry with `start/extend/wait/waitForPromotion/promote/cancel`, synthetic `<task id state>` inject | No promotion, no synthetic inject, parent blocked always |
| Bridge | `subagent_launch`, `subagent_status`, `subagent_cancel`, `subagent_result` client methods, `subagent_updated` server event with `subagent_id`, `state` | Same + session list with parentID filter | Bridge exists but desktop renderer only shows list `crusorai-subagent-list` with goal/state/duration, no navigation |
| Desktop UI | `crusorAIRenderer.ts:875` family `subagent`, `crusorAIRendererService.ts:966` `subagent_updated` → `subAgents Map`, `crusorAIRunSummary.ts` CARD_TOOL_NAMES includes delegate, `crusorAIToolCatalog.ts` Delegate | `message-part.tsx` task-tool-card with `--task-agent-color`, spinner vs icon, clickable href, hover action arrow, subtitle description + "(background)" | No color, no clickable navigation, no description extraction, no background label |
| Webview | `a2ui/renderers.tsx` only Card/Title/StatusBadge/PriorityTag/AssigneeBadge/Button, `hermes-ui/components/tool-card.tsx` generic | Same + task-specific card with progress indicator V2 | No task-specific renderer |
| Config | `subagent_auto_approve` env, depth cap via `thread_id.startswith("sub-")` | `subagent_depth` config, permission ruleset | No config file for depth, hardcoded 1 level |

**Careful observation:** Crusor's `subagent_lifecycle.py` already has HMAC token verification (`_token(sid, parent, created)`) — stronger than OpenCode's simple sessionID check. Keep it.

---

## 2. Design Principles — Be Careful

1. **Additive protocol:** `subagent_updated` already has `subagent_id`, `state`. Add `parent_session_id`, `session_id` (child thread_id), `title`, `description`, `tool_call_id`, `toolCalls`, `background` — never remove existing.
2. **Depth guard preserved:** Current guard `if thread_id.startswith("sub-")` → deny nested. Extend to walk parent chain via `subagent_sessions` table to enforce `cfg.subagent_depth` (default 1). Single level today = no behavior change.
3. **Thread safety:** `SubAgentCoordinator._active_agents` mutates from worker threads in `spawn_batch` — already has `_lock`. Keep lock, never hold across `invoke_agent`.
4. **No token bloat:** OpenCode `compactToolPart` strips output to keep parent context lean. Crusor already caps result 2000 chars, but tool part output still stored in checkpoint. Add `compact` flag to keep only metadata in parent message, full output in child session.
5. **EventBus session isolation:** `event_bus.emit("subagent.updated", {"thread_id": parent_session_id, ...})` already uses parent thread_id — ensures parent session only sees its children. Keep it, add `child_thread_id` field.
6. **Cancellation:** `turn_controls.cancel(child_id)` + `future.cancel()` already exists. Ensure `subagent_cancel` frame cancels both lifecycle future and turn_control.
7. **Feature flag:** `CRUSORAI_EXPERIMENTAL_SUBAGENT_NAVIGATION` (default off) gates new UI, `CRUSORAI_EXPERIMENTAL_BACKGROUND_SUBAGENTS` gates background (same env name as OpenCode for familiarity).
8. **Security:** `allowed_capabilities` must remain subset of parent, checked via `KNOWN_CAPABILITIES`. Add `deriveSubagentSessionPermission` logic for file permissions: parent deny rules + external_directory always inherited, even if child allows.
9. **UI performance:** Task card is lightweight — no virtualization change. Child timeline reuses existing `groupsFromMessages` + `RENDER_BUDGET` (FIRST_PAINT_BUDGET + BACKFILL_STEP). No new heavy component.
10. **No secret leak:** Child session title is `description + (@agent subagent)` — description may contain user data, but title is stored in `~/.crusorai` only, not sent to provider except as part of tool metadata (already). Ensure description truncated to 200 chars in events.

---

## 3. Full Pipeline Design for Crusor

### 3.1 Data Model

**New table `subagent_sessions` in `~/.crusorai/sessions.db` (or reuse checkpoint metadata):**

```sql
CREATE TABLE IF NOT EXISTS subagent_sessions (
  subagent_id TEXT PRIMARY KEY,
  parent_session_id TEXT NOT NULL,
  child_thread_id TEXT NOT NULL UNIQUE, -- equals subagent_id today, but explicit
  mode TEXT NOT NULL, -- research|code|test|review
  goal TEXT NOT NULL, -- original task, truncated 16000
  description TEXT, -- short 3-5 words (new param)
  agent_name TEXT, -- subagent_type
  state TEXT NOT NULL, -- pending|running|succeeded|failed|cancelled
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  tool_call_id TEXT, -- parent tool_call_id that spawned it
  tool_calls INTEGER DEFAULT 0, -- updated from child metadata
  background BOOLEAN DEFAULT 0,
  result TEXT, -- capped 32000 (existing)
  error TEXT
);
CREATE INDEX idx_subagent_parent ON subagent_sessions(parent_session_id, created_at);
```

**Why separate table, not just checkpoint metadata?**
- Checkpoint DB is managed by `langgraph-checkpoint-sqlite` (opaque schema). Adding our own table in same file is safe, WAL mode, same lock.
- Allows `session_list` to return children via `parentID` filter without scanning all checkpoints.
- Keep existing `_active_agents` in-memory for fast pop-on-read, but also persist to this table for crash recovery + navigation.

**In-memory registry extension:**
```python
# In SubAgentCoordinator._active_agents[agent_id] = {mode, task, description, result, parent, child_thread_id, tool_call_id, background}
```

### 3.2 Permission Derivation (port OpenCode logic)

**File:** `src/context/safety_guard.py` or new `src/agents/subagent_permissions.py`

```python
def derive_subagent_permission(parent_ruleset: list[dict], subagent_info: Agent.Info) -> list[dict]:
    # parent_ruleset = list of {permission, pattern, action}
    # Keep only deny + external_directory from parent
    inherited = [r for r in parent_ruleset if r["action"]=="deny" or r["permission"]=="external_directory"]
    # Add todowrite deny if subagent doesn't allow it, same for task
    if not any(r["permission"]=="todowrite" for r in subagent_info.permission):
        inherited.append({"permission":"todowrite","pattern":"*","action":"deny"})
    if not any(r["permission"]=="task" for r in subagent_info.permission):
        inherited.append({"permission":"task","pattern":"*","action":"deny"})
    # Deduplicate
    return dedup(inherited)
```

**Integration:** In `SubagentLifecycleService.launch`, accept `parent_permission` (from `sessions.get(parent).permission` or current safety rules), derive, then pass to `subagent_coordinator.spawn` as `scope_capabilities` filtered.

### 3.3 Tool Layer — LangGraph Tools

**File:** `src/graphs/chat_graph.py`

Current:
```python
@tool
def delegate_to_subagent(mode, task, config): ...
@tool
def delegate_to_subagent_batch(mode, tasks, config): ...
```

Proposed (additive, keep old for compat):

```python
@tool
def delegate_to_subagent_v2(
    description: str, # 3-5 words, required new
    prompt: str, # full task
    subagent_type: str = "general", # maps to mode
    task_id: Optional[str] = None, # resume
    background: bool = False,
    config: RunnableConfig,
) -> str:
```

But to avoid breaking LLM tool schema (already learned), keep `delegate_to_subagent` signature but **add optional args** with defaults:

```python
@tool
def delegate_to_subagent(
    mode: Literal[...],
    task: str,
    description: Optional[str] = None, # new
    subagent_type: Optional[str] = None, # alias for mode
    background: bool = False, # new
    config: RunnableConfig,
) -> str:
```

Implementation steps inside:
1. Resolve `description = description or task[:50]` (truncated)
2. Resolve `agent_name = subagent_type or mode`
3. Check depth via `subagent_sessions` table: walk parent chain, count depth, compare `cfg.subagent_depth` (new config, default 1)
4. If `task_id` provided and exists in `subagent_sessions` with same parent, reuse `child_thread_id` instead of creating new
5. Check `background` flag: if True and `CRUSORAI_EXPERIMENTAL_BACKGROUND_SUBAGENTS` not set, return error message (like OpenCode)
6. Launch via `subagent_lifecycle.launch(parent_session_id=caller_thread, goal=task, mode=mode, ...)` — already creates record + future
7. Immediately emit `subagent_updated` with `session_id=child_thread_id`, `parent_session_id`, `description`, `state=running`, `tool_call_id=config["configurable"]["tool_call_id"]`
8. If background: return immediately with XML `<task id=child_thread_id state=running><summary>Background task started</summary>...</task>` + store `background=True`
9. If foreground: `wait(handle, timeout=None)` blocking, then return `<task id=... state=completed>result</task>` with result capped 2000
10. On each child progress (tool call inside child), update `tool_calls` counter in `subagent_sessions` and emit `subagent_updated` with `toolCalls`

**Batch tool:** Same, but description list optional.

**Result formatting (OpenCode parity):**
```python
def render_output(session_id, state, text, summary=None):
    tag = "task_error" if state=="error" else "task_result"
    return f'<task id="{session_id}" state="{state}">{f"<summary>{summary}</summary>" if summary else ""}<{tag}>\n{text}\n</{tag}>\n</task>'
```

Parent LLM sees this XML and can summarize.

### 3.4 Background Job Registry (extend lifecycle)

**File:** `src/agents/subagent_lifecycle.py`

Add:
- `background: bool` field in `_Record`
- `tool_call_id: str`
- `tool_calls: int` counter
- Methods:
  - `promote(subagent_id)` → sets background=True, emits updated
  - `extend` logic: if `subagent_id` already exists and running, return existing handle (resume)
  - `inject_result(parent_session_id, child_session_id, state, text)` → emits synthetic user message? Actually OpenCode injects via `ops.prompt` with synthetic text part. In Crusor, we can emit a `token` event with synthetic `<task>` XML to parent session via `event_bus.emit("token", {"thread_id": parent, "text": render_output(...)})` — parent LLM will see it as tool result? Need careful: tool result already returned. For background, parent tool call already returned `running` state. When child completes, we need to inject new assistant message? OpenCode does `ops.prompt` with synthetic text part to parent. In Crusor, we can use `event_bus` to emit a new `token` + `turn_started`? Simpler: emit `subagent_updated` with final state, and also append to parent's `steps_completed`? Actually parent already finished its turn after returning backgroundResult. The background completion should start a **new turn** in parent session with synthetic user message containing `<task id state=completed>`.

Implementation: When background job completes, spawn a new thread that calls `stream_agent` with synthetic prompt `render_output(...)` and same parent thread_id, but with `synthetic=True` flag to avoid approval.

This matches OpenCode's `inject` which does `ops.prompt({sessionID: parent, parts: [{type:"text", synthetic:true, text: renderOutput}]})`.

In Crusor, we have `turn_controls` and `stream_agent` — we can call `stream_agent` in a new thread with `synthetic` message.

Add config `CRUSORAI_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true` to enable.

### 3.5 Bridge Protocol

**File:** `src/bridge/protocol_v2.json`

Add client method `subagent_list` (list children of a session) — optional, but useful for desktop to show subagent panel.

Extend `subagent_updated` event payload:

```json
{
  "type": "subagent_updated",
  "session_id": "parent_thread_id",
  "subagent_id": "sub-xxx",
  "child_thread_id": "sub-xxx",
  "parent_session_id": "parent_thread_id",
  "state": "running|succeeded|failed|cancelled",
  "mode": "research|code|test|review",
  "description": "short desc",
  "goal": "full task truncated 200",
  "tool_call_id": "call_xxx",
  "tool_calls": 3,
  "background": false,
  "duration": "12s",
  "result": "capped 2000",
  "error": "..."
}
```

**File:** `src/bridge/__main__.py`

- `_subagents: dict[subagent_id, handle]` already exists
- On `subagent_launch`: create handle via lifecycle, store, emit `subagent_updated` with extended fields
- On `subagent_status`, `subagent_cancel`, `subagent_result`: return extended status
- New `subagent_list`: query `subagent_sessions` table where `parent_session_id == sid`, return list sorted by created_at desc
- Ensure `subagent_updated` emitted via `event_bus` subscription already in `_forward_events`? Check: `event_bus.emit("subagent.updated")` in lifecycle `_emit` uses `thread_id=parent_session_id`, so forwarder that subscribes with `thread_id=None` admin will get it, then filter by session? Actually forwarder filters by `identity`? Need to ensure child events don't leak. Current forwarder: `q = event_bus.subscribe(thread_id=None)` admin, then in `_forward_events` it checks `event.thread_id == sid`? Let's verify: In `__main__.py` around 500, it forwards events where `event.thread_id == sid` or `event.session_id == sid`. Since `subagent.updated` emits with `thread_id=parent_session_id`, it will be forwarded to parent session client. Good.

Add `child_thread_id` to emission.

### 3.6 Event Journal

**File:** `src/runtime/event_journal.py`

Add method `list_subagent_events(parent_session_id)` that queries `runtime_events` where `event_type="subagent.updated"` and `session_id=parent`.

No schema change needed, just helper.

### 3.7 Desktop Workbench UI

**Files:** `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/`

Current: `crusorAIRenderer.ts` renders subagent list as `crusorai-subagent-list` with rows `crusorai-subagent-row is-{state}`.

Proposed (OpenCode desktop parity):

1. **Task tool card** — in `crusorAIRenderer.ts` family `subagent` and tool `delegate_to_subagent`:

```ts
// Existing tool catalog: delegate_to_subagent: tool('Delegate', 'subagent', 'rocket', 'running')
// Extend presentation:
if (presentation.family === 'subagent' || name.startsWith('delegate_to_subagent')) {
  const childId = tool.metadata?.sessionId || tool.metadata?.child_thread_id;
  const description = tool.input?.description || tool.input?.task || 'Sub-agent task';
  const agentName = tool.input?.subagent_type || tool.input?.mode || 'general';
  const background = tool.metadata?.background;
  const toolCalls = tool.metadata?.toolCalls;
  const card = element('div', 'crusorai-task-tool-card');
  card.style.setProperty('--task-agent-color', agentColor(agentName));
  const surface = element('div', 'crusorai-task-tool-surface');
  const icon = running ? element('span', 'crusorai-task-tool-spinner', icon('loading~spin')) : element('span', 'crusorai-task-tool-icon', icon('robot'));
  surface.append(icon, element('span', 'crusorai-task-tool-title', agentName), element('span', 'crusorai-task-tool-subtitle', description + (background?' (background)':'')));
  if (toolCalls) surface.append(element('span', 'crusorai-task-tool-calls', `${toolCalls} tool calls`));
  card.append(surface);
  if (childId) {
    const action = element('div', 'crusorai-task-tool-action', icon('arrow-up-right'));
    card.append(action);
    card.classList.add('is-clickable');
    card.addEventListener('click', () => {
      // Navigate to child session: emit event to session controller to load child thread_id
      // For now, open in manager? Or replace current session?
      // Proposal: open child in same panel via session_load with child thread_id
      // Keep parent in history stack
      host.navigateToSession?.(childId); // need to add host method
    });
  }
  return card;
}
```

2. **Child view lock** — in `crusorAIRendererService.ts`:

```ts
// Detect if current session is child (has parentID)
private isChildSession(sessionId: string): boolean {
  // Query subagent_sessions table via bridge? Or check if sessionId startsWith "sub-"
  // Better: ask bridge for parent via subagent_list
  return sessionId.startsWith('sub-');
}

get model(): CrusorAIRenderModel {
  return {
    ...,
    isChild: this.isChildSession(this.sessionId),
    parentSessionId: this.parentMap.get(this.sessionId),
  }
}
```

In renderer: if `model.isChild`, disable composer, show banner "Sub-agent session — prompt disabled. Back to Parent" button that calls `session_resume` with parent.

3. **Subagent list panel** — existing `crusorai-subagent-list` at bottom of transcript? Enhance to show description, toolCalls, background, duration, and make rows clickable to navigate to child.

4. **Tool catalog** — `crusorAIToolCatalog.ts`: keep delegate, but add `subagent` family with icon `robot`, color via agent palette hash (like OpenCode `tone(name)`).

5. **Host capability** — add `navigateToSession` method in `crusorAIWorkbenchService.ts` that sends `session_load` or `session_resume` for child.

**CSS** — add to `crusorTheme.ts` or new `crusorai-subagent.css`:

```css
.crusorai-task-tool-card {
  display:flex; gap:8px; padding:8px 12px; border-radius:6px;
  border:0.5px solid var(--vscode-widget-border); background: var(--vscode-editor-background);
  --task-agent-color: #0b6bcb;
}
.crusorai-task-tool-card.is-clickable { cursor:pointer; }
.crusorai-task-tool-card.is-clickable:hover { background: var(--vscode-list-hoverBackground); }
.crusorai-task-tool-surface { flex:1; display:flex; gap:8px; align-items:center; min-width:0; }
.crusorai-task-tool-title { font-weight:500; text-transform:capitalize; color: var(--task-agent-color); }
.crusorai-task-tool-subtitle { color: var(--vscode-descriptionForeground); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.crusorai-task-tool-action { margin-left:auto; opacity:0; transition:opacity 0.15s; }
.crusorai-task-tool-card:hover .crusorai-task-tool-action { opacity:1; }
.crusorai-task-tool-spinner { color: var(--task-agent-color); }
```

### 3.8 Webview UI (CopilotKit)

**Files:** `crusor-webview/src/a2ui/renderers.tsx`, `hermes-ui/components/tool-card.tsx`, `hermes-ui/crusor/types.ts`

- Add `TaskToolCard` renderer similar to desktop:
  - Props: `description`, `subagent_type`, `sessionId`, `toolCalls`, `background`, `status`
  - Use `cn` + `status-pulse.tsx` for running spinner (400ms pulse every 5000ms, existing breathing UI)
  - Clickable → `window.open` or `navigate` to child session route (if webview has router, or emit event to parent)
  - Color via `agentColor` hash (reuse `tone` from OpenCode or existing `--crusor-*` palette)

- In `hermes-ui/crusor/normalize.ts`: detect `delegate_to_subagent` tool calls, extract `sessionId` from metadata, produce `toolView` with `kind: 'task'`

- In `thread.tsx`: if `isChild` (check if sessionId startsWith sub- or has parentID from API), render disabled composer + Back button (similar to OpenCode `SessionComposerRegion`)

- **AG-UI bridge:** Ensure `src/server.py` exposes `session_id` in tool metadata — already via `tool_call_end`? Need to add `metadata` field to `tool_call_end` event.

### 3.9 Config

**File:** `src/config/settings.py`

Add:
```python
SUBAGENT_DEPTH = int(os.getenv("CRUSORAI_SUBAGENT_DEPTH", "1"))
SUBAGENT_NAVIGATION = os.getenv("CRUSORAI_EXPERIMENTAL_SUBAGENT_NAVIGATION", "false").lower()=="true"
BACKGROUND_SUBAGENTS = os.getenv("CRUSORAI_EXPERIMENTAL_BACKGROUND_SUBAGENTS", "false").lower()=="true"
```

Add to `.env.example`.

---

## 4. Implementation Phases

### Phase 0: Contracts & Safety (1 day, no behavior change)

**Files:**
- `src/agents/subagent_permissions.py` (new)
- `src/tests/test_subagent_permissions.py` (new)
- `src/config/settings.py` (add depth, flags)
- `docs/CRUSOR_SUBAGENT_FULL_PIPELINE_PLAN.md` (this file)

**Tasks:**
- Implement `derive_subagent_permission` with tests (parent deny + external_directory inheritance, todowrite/task deny)
- Add `subagent_sessions` table creation in `EventJournal` or new `src/runtime/subagent_store.py` with `init_db`, `create`, `get`, `list_by_parent`, `update_state`, `depth_of`
- Unit tests for depth walking (parent chain)
- Feature flag checks

**Risks:** None, additive.

**Verification:**
```bash
uv run python -m pytest src/tests/test_subagent_permissions.py -q
uv run python -m pytest src/tests/test_subagent_lifecycle_service.py -q
```

---

### Phase 1: Session Hierarchy & Persistence (2 days)

**Files:**
- `src/runtime/subagent_store.py` (new)
- `src/agents/subagent_lifecycle.py` (extend _Record, add description, tool_call_id, tool_calls, background, parent chain)
- `src/agents/sub_agent.py` (extend _active_agents to include description, child_thread_id, persist to store)
- `src/bridge/__main__.py` (subagent_list method, extended subagent_updated payload)
- `src/bridge/protocol_v2.json` + generated TS

**Tasks:**
- Create `SubagentStore` class wrapping sqlite `~/.crusorai/sessions.db` (same file as checkpoint, but separate table) with WAL, busy_timeout
- On `launch`, insert into store, set state pending, emit with child_thread_id
- On `_run` start, update state running, updated_at
- On success/fail/cancel, update result/error, state, updated_at
- Add `tool_calls` increment on each child tool call (hook via event_bus listener for child thread_id)
- `depth_of(thread_id)` walks parent chain via store
- Bridge `subagent_list` returns `list_by_parent(parent_session_id)` sorted desc
- Regenerate protocol TS: `python scripts/generate_bridge_protocol.py`

**Careful:**
- Keep existing `_active_agents` pop-on-read, but also keep store — store is source of truth for navigation, memory dict is for fast result delivery
- Lock ordering: store lock inside lifecycle lock? Use separate RLock, never hold across `invoke_agent`
- Truncate goal to 16000, description to 200, result to 32000 (existing)

**Tests:**
- `test_subagent_store.py` (new): create, list, depth, truncation
- `test_subagent_lifecycle_service.py` extended: check store persistence, background flag

---

### Phase 2: Tool Layer — Description, SessionId Metadata, Background (2 days)

**Files:**
- `src/graphs/chat_graph.py` (delegate_to_subagent, delegate_to_subagent_batch)
- `src/agents/subagent_lifecycle.py` (promote, inject)
- `src/llm/factory.py` (maybe pass tool_call_id)

**Tasks:**
- Add `description` optional param to `delegate_to_subagent` (fallback to task[:50])
- Add `background` bool param (default False)
- Resolve `subagent_type` alias for `mode`
- Depth check via `subagent_store.depth_of(caller_thread)` vs `SUBAGENT_DEPTH`
- If `background` and flag off, return error message "Background subagents require ..."
- Launch via lifecycle, get `child_thread_id`
- Emit `subagent_updated` with `tool_call_id` from `config["configurable"]["tool_call_id"]` (need to pass through)
- If background: return `render_output(child_id, "running", BACKGROUND_STARTED, summary="Background task started")` immediately, set background=True in store, spawn thread that waits for child completion then calls `inject_result`
- If foreground: `wait(handle)` blocking, then `render_output(child_id, "completed", result[:2000])`
- `inject_result` implementation: new thread calls `stream_agent` with synthetic prompt containing `<task id=... state=completed>...</task>` and same parent thread_id, but with `synthetic=True` to bypass approval. Use `turn_controls.begin(parent)`? Careful not to deadlock.
- Batch tool same, but descriptions list optional

**Careful:**
- `config` may not have `tool_call_id` — fallback to `ulid()` or `subagent_id`
- Background inject must not create infinite loop: synthetic prompt should not trigger another subagent (depth guard will prevent, but also check synthetic flag)
- Keep existing tool name `delegate_to_subagent` — LLM already knows it. Adding optional params is safe (pydantic will ignore unknown? Actually tool schema derived from function signature — adding optional with default is backward compat)

**Tests:**
- `test_subagent_autodeny.py` extended
- `test_subagent_hygiene.py` — check pop-on-read still works, store persistence
- New `test_subagent_background.py` — mock lifecycle, check backgroundResult format

---

### Phase 3: Bridge & Event Journal (1 day)

**Files:**
- `src/bridge/__main__.py`
- `src/runtime/event_journal.py`
- `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAIProtocol.ts` (manual, then generated)

**Tasks:**
- Implement `subagent_list` client method handler
- Extend `subagent_updated` emission to include all new fields (parent_session_id, child_thread_id, description, mode, tool_call_id, tool_calls, background, duration)
- Add `duration` calculation: `updated_at - created_at` formatted like `12s` or `1:05`
- Ensure `event_bus.subscribe(thread_id=None)` admin gets subagent events, and `_forward_events` forwards only if `thread_id == parent_session_id`
- Add `list_subagent_events` helper in journal (optional)

**Verification:**
```bash
uv run python -m pytest src/tests/test_bridge.py src/tests/test_bridge_protocol_v2.py -q
```

---

### Phase 4: Desktop Workbench UI (3 days) — Most Careful

**Files:**
- `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRenderer.ts`
- `crusorAIRendererService.ts`
- `crusorAIToolCatalog.ts`
- `crusorAIWorkbenchService.ts`
- `crusorTheme.ts` or new `crusorai-subagent.css`
- `crusorAIProtocol.ts`

**Tasks:**

4.1 Tool catalog:
- Keep `delegate_to_subagent` icon `rocket`, but add `color` via hash function `tone(agentName)` (reuse OpenCode palette or Crusor accent `#0b6bcb`)
- Add `subagent` family presentation

4.2 Renderer service:
- `subAgents: Map<subagent_id, {id, state, goal, description, mode, parent_session_id, child_thread_id, tool_call_id, toolCalls, background, duration, result, error}>`
- On `subagent_updated` frame, merge into map, keep `lastUpdatedAt`
- Add `parentMap: Map<child_thread_id, parent_session_id>` for navigation
- Add `isChildSession(sessionId)` → check `parentMap.has(sessionId)` or `sessionId.startsWith("sub-")`
- Add `getChildren(parentId)` → filter subAgents where parent_session_id==parentId, sort by created_at desc
- Add `navigateToSession(childId)` method that sends `session_load` or `session_resume` and updates `sessionId`

4.3 Renderer:
- In `renderTool` for `delegate_to_subagent`:
  - Extract `description`, `mode`, `sessionId` from tool metadata
  - Create card `crusorai-task-tool-card` with CSS var `--task-agent-color`
  - Spinner if running (use existing `icon('loading~spin')` + `status-pulse` 400ms pulse every 5000ms via Web Animations, already exists)
  - Title = capitalized mode, subtitle = description (+ background label)
  - If `toolCalls`, show count
  - If `child_thread_id`, make clickable, show arrow action, on click call `host.navigateToSession(childId)`
  - Keyboard: Enter/Space navigates
- Subagent list at bottom: render `crusorai-subagent-list` with rows clickable, status icon/color (● completed highlight, ○ cancelled muted, ◍ error, ◔ spinner)
- Child view: if `model.isChild`, render banner `crusorai-child-banner` with "Sub-agent session — prompt disabled" + Back button → `host.navigateToSession(parentSessionId)`
- Disable composer when `isChild` (check in `crusorAIViewPane.ts` or renderer)

4.4 Workbench service:
- Add `navigateToSession(sessionId)` that calls `sessionService`? Actually `crusorAIRendererService` owns sessionId, so add method `loadSession(sessionId)` that does `send({type:'session_load', session_id: sessionId})` and updates model

4.5 CSS:
- Add task card styles (see section 3.7), status colors, pulse animation (reuse `status-pulse.tsx` logic: 400ms pulse every 5000ms via WAAPI, sleeps when hidden)

4.6 Feature flag:
- Gate clickable navigation behind `crusorai.experimental.subagentNavigation` setting (default false). When off, card not clickable, child banner not shown, but card still renders.

**Careful:**
- No `innerHTML`, use `element()` helper to avoid XSS (description may contain user data, but truncated and escaped via textContent)
- No hard-coded localhost, use relative navigation
- Preserve existing `crusorai-subagent-list` rendering for backward compat when flag off
- Test with `npm run compile` + `typecheck-client`

**Tests:**
- Manual: launch desktop `npm run compile`, open Crusor, trigger delegate, see card, click navigates, back works, prompt disabled in child
- Automated: add DOM test in `desktop/vscode/test`? Existing branding tests — add `test_crusorai_subagent_card.py`? Actually desktop tests are TS, but we can add `src/tests/test_desktop_subagent_ui.py` that checks renderer template strings

---

### Phase 5: Webview UI (2 days)

**Files:**
- `crusor-webview/src/a2ui/renderers.tsx`
- `crusor-webview/src/hermes-ui/components/tool-card.tsx`
- `crusor-webview/src/hermes-ui/crusor/types.ts`
- `crusor-webview/src/hermes-ui/crusor/normalize.ts`
- `crusor-webview/src/hermes-ui/components/thread.tsx`
- `crusor-webview/src/hermes-ui/model/timeline-data.ts`

**Tasks:**

5.1 Add `TaskToolCard` component:
```tsx
export function TaskToolCard({ description, subagent_type, sessionId, toolCalls, background, status }) {
  const running = status==='running'||status==='pending';
  const tone = agentColor(subagent_type); // hash
  return <div data-component="task-tool-card" style="--task-agent-color: tone">
    <div data-component="task-tool-surface">
      {running ? <StatusPulse /> : <Icon name="subagent" />}
      <span data-component="task-tool-title">{Titlecase(subagent_type)}</span>
      <span data-slot="subtitle">{description}{background?' (background)':''}</span>
      {toolCalls && <span>{toolCalls} calls</span>}
    </div>
    {sessionId && <Icon name="arrow-up-right" />}
  </div>
}
```

5.2 In `renderers.tsx`, add case for `delegate_to_subagent` tool:
- If tool name startsWith delegate, render TaskToolCard with props from tool input + metadata

5.3 In `normalize.ts`, extract `sessionId` from tool metadata, produce `toolView.kind='task'`

5.4 In `thread.tsx`, detect child session (sessionId startsWith sub- or has parentID from API), render disabled composer + Back button (reuse OpenCode `SessionComposerRegion` logic)

5.5 Ensure `src/server.py` AG-UI endpoint includes tool metadata `sessionId` in `tool_call_end` event — check `add_langgraph_fastapi_endpoint` and tool node

**Careful:**
- Webview uses relative runtime URL (`/api/copilotkit`) via Vite proxy — keep it
- No `localhost` hard-code
- Keep zod 3.25.76 pin (OpenCode trap)
- Keep A2UI flat props format `{id, component, ...props}` not nested `props`

**Tests:**
```bash
cd crusor-webview && npm test # DOM harness, provider-free
npx tsc --noEmit --project tsconfig.json
```

---

### Phase 6: Config, Docs, Rollout (1 day)

**Files:**
- `src/config/settings.py`
- `.env.example`
- `README.md`
- `docs/OPENCODE_SUBAGENT_PIPELINE.md` (already) + this plan
- `crusor-webview/README.md`
- `desktop/README.md`

**Tasks:**
- Add env vars to `.env.example` with comments
- Add setting `crusorai.experimental.subagentNavigation` in `crusorAI.contribution.ts` (default false)
- Update README Recent Changes
- Write migration guide: how to enable, how to test, how to disable
- Add e2e test `crusor-webview/e2e-verify.spec.ts` for task card navigation (fix Windows hard-coded path first)

**Rollout:**
- Phase 0-2 behind flag off by default, merge to arena branch
- Phase 4-5 behind `experimental.subagentNavigation` flag
- Manual verification on Windows + Linux (existing `test5.py`?)
- After 1 week, enable flag default true

---

## 5. Testing Strategy

**Unit:**
- `test_subagent_permissions.py`: parent deny inheritance, external_directory, todowrite/task deny
- `test_subagent_store.py`: create, list_by_parent, depth, truncation, WAL
- `test_subagent_lifecycle_service.py`: launch, status, cancel, background, token verification
- `test_subagent_background.py`: backgroundResult XML format, inject synthetic

**Integration:**
- `test_bridge.py` + `test_bridge_protocol_v2.py`: subagent_list, subagent_updated extended fields
- `test_event_safety.py`: ensure child events only go to parent session, not cross-session
- `test_desktop_workspace_boundary.py`: ensure child session workspace == parent workspace

**Desktop:**
- `npm run compile` + `typecheck-client` + `valid-layers-check`
- Manual: trigger `delegate_to_subagent` with description, see card, click, back, prompt disabled, permission bubbling
- Webview: `npm test` DOM harness, `npx tsc -b`

**E2E:**
- `scripts/run_bridge_turn.py` with prompt that triggers subagent, verify `subagent_updated` frames, child session created, parent receives `<task>` XML
- Playwright `e2e-verify.spec.ts` fixed to use relative paths, not `D:/`

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Child session DB grows unbounded | Cap `subagent_sessions` table: keep newest 100 per parent, or 1000 total, evict oldest (like _active_agents cap 50) |
| Token bloat from child output in parent | Keep parent result capped 2000, store full in child only, use compactToolPart logic (strip output from parent checkpoint) |
| Deadlock on background inject (stream_agent called from background thread while parent turn active) | Inject via new thread, use `turn_controls` to ensure parent idle before inject, or queue synthetic prompt via `turn_controls.queue` (like reasoning_effort queue) |
| UI XSS via description | Use textContent, truncate 200, escape |
| Depth bomb (subagent spawns subagent) | Enforce depth via store walk, default 1, error message same as today |
| Breaking existing `subagent_updated` consumers | Additive fields only, keep `subagent_id`, `state` |
| Electron recompile STALE warning | Run `npx gulp compile` after every desktop change, commit `out/` |
| Zod v4 breaking A2UI bindings | Pin zod 3.25.76 in crusor-webview/package.json |
| Hard-coded localhost breaking preview | Use relative URLs + Vite proxy, test in preview host `https://{port}-{sandbox}.e2b.app` |

---

## 7. Open Questions

1. Should child session be visible in Manager window (`Crusor Manager`)? Currently manager shows sessions from `sessionStore.records()` — should filter out children or show with indent? Proposal: show with `↳` prefix and parentID tooltip, but hidden from home list (like OpenCode).
2. Should `delegate_to_subagent_batch` create multiple child sessions with same description prefix + index? OpenCode does. Proposal: yes, title `"{desc} [{i}/{total}] (@{agent} subagent)"`.
3. Background inject: should it create a new turn or append to existing assistant message? OpenCode injects synthetic user message that starts new turn. Proposal: same — new turn with synthetic user part, so parent LLM can summarize.
4. Permission derivation: Crusor's safety_guard uses `git check-ignore` path-based, OpenCode uses ruleset. How to map? Proposal: keep existing `allowed_capabilities` check, plus add `derive_subagent_permission` for file permissions using same path logic.
5. Webview navigation: AG-UI agent currently doesn't have router for child sessions. Should child session be opened in same webview or new tab? Proposal: same webview, replace transcript, keep history stack for Back button (like OpenCode desktop).

---

## 8. Minimal Implementation Order (for careful PRs)

1. **PR1: Store + Permissions** (Phase 0+1) — no UI, no behavior change, just new table + derivation + tests
2. **PR2: Tool metadata + Background** (Phase 2) — add description, sessionId metadata, background flag, render_output XML, but still synchronous
3. **PR3: Bridge extension** (Phase 3) — subagent_list + extended subagent_updated
4. **PR4: Desktop card** (Phase 4.1-4.3) — task-tool-card rendering, clickable behind flag, child banner
5. **PR5: Webview card** (Phase 5) — same for webview
6. **PR6: Background inject + Config + Docs** (Phase 2 background + Phase 6) — enable background, final docs, e2e

Each PR <300 lines, passes `pytest -q --basetemp=/tmp`, `npm run compile`, `npx tsc -b`, `npm test`.

---

## 9. File Checklist

**New:**
- `src/runtime/subagent_store.py`
- `src/agents/subagent_permissions.py`
- `src/tests/test_subagent_permissions.py`
- `src/tests/test_subagent_store.py`
- `src/tests/test_subagent_background.py`
- `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorai-subagent.css` (or add to theme)

**Modified:**
- `src/agents/sub_agent.py`
- `src/agents/subagent_lifecycle.py`
- `src/graphs/chat_graph.py`
- `src/bridge/__main__.py`
- `src/bridge/protocol_v2.json`
- `src/config/settings.py`
- `src/runtime/event_journal.py` (optional helper)
- `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRenderer.ts`
- `crusorAIRendererService.ts`
- `crusorAIToolCatalog.ts`
- `crusorAIWorkbenchService.ts`
- `crusorAI.contribution.ts` (setting)
- `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAIProtocol.ts` + generated
- `crusor-webview/src/a2ui/renderers.tsx`
- `crusor-webview/src/hermes-ui/components/tool-card.tsx`
- `crusor-webview/src/hermes-ui/crusor/normalize.ts`
- `crusor-webview/src/hermes-ui/components/thread.tsx`
- `.env.example`
- `README.md`

---

**End of plan — ready for implementation when flagged.**
