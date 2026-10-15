# AG-UI + A2UI Plan — CrusorAI

**Status: DECISIONS LOCKED by founder, 2026-10-14. Not yet implemented.**
This is the build doc the desktop agent executes against. UI-language rule from the
founder applies everywhere in this doc: visible labels are human words, never raw
tool ids (the ids appear here only as engineering references).

## 0. The two protocols (one line each)

- **AG-UI** (CopilotKit): agent <-> frontend **transport**. A stream of typed events
  (run lifecycle, text, reasoning, tool calls, state, interrupts) over HTTP/SSE.
- **A2UI** (Google, v0.9): agent -> frontend **UI description**. The agent sends
  surface operations (`createSurface`, `updateComponents`, `updateDataModel`,
  `deleteSurface`); the client renders them from a **fixed component catalog**.
  No arbitrary HTML/JS ever crosses the wire.

They compose: AG-UI carries the conversation; A2UI payloads ride inside it.

## 1. Locked decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Desktop internal protocol | **Keep Bridge Protocol v2; map to AG-UI at the edge** | v2 is a superset of AG-UI (host tools, checkpoints, inline completions, subagents, skills hub have no AG-UI standard events). It runs over local IPC — no port, no HTTP stack, lowest latency on desktop. Migration buys compatibility, not speed: turn latency lives in model calls and tool execution (audit: 25–56 s/step), protocol overhead is milliseconds. |
| 2 | First new A2UI surface | **Verification Receipt** | Approval UI already works (safety dock) — rebuilding it first is risk without new value. Verification is the product signature ("Receipts, not vibes") and currently the weakest surface (placeholder rows in the renderer verification body). |
| 3 | A2UI renderer scope | **Native pane only (MVP)** | The native pane is canonical. The webview lab already has CopilotKit's React-side path if ever needed. |
| 4 | UI architecture | **Hybrid: custom shell, dynamic bodies** | Transcript, composer and streaming stay hand-built (brand, paint isolation, accessibility). Tool bodies and generated surfaces become A2UI data rendered through the catalog. |

## 2. Current state (verified in code, 2026-10-14)

- **Bridge Protocol v2** is the desktop contract: `src/bridge/protocol.py`
  (newline-delimited JSON codec, PROTOCOL_VERSION = 2) and
  `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAIProtocol.ts`
  (~33 engine->client event types, ~25 client->engine commands).
- **AG-UI exists for the web path only**: `src/server.py` (FastAPI +
  `ag_ui_langgraph` + `copilotkit.LangGraphAGUIAgent`). Consumed by the
  `crusor-webview` lab (`crusor-webview/src/hermes-ui/crusor/normalize.ts`).
  ⚠️ `src/server.py` binds `0.0.0.0:8123` with no auth — Phase 1 fixes this
  before any external use.
- **A2UI exists for exactly one surface**: `display_crusor_task`
  (`src/graphs/chat_graph.py`, copilotkit `a2ui` with a stdlib fallback) +
  `src/a2ui_schemas/crusor_task_schema.json` (12 components: Card/Column/Row/
  Text/Button). The native renderer paints that tool with a bespoke card
  (`crusorAIRenderer.ts: taskToolCard`), not a generic surface renderer.
- **Renderer bodies the catalog will reuse** (`crusorAIRenderer.ts`):
  `familyBody` (family dispatch), `terminalBody`, `planListBody`,
  `taskToolCard`, `approvalDock`, `clarifyCard`. Tool presentation lives in
  `common/crusorAIToolCatalog.ts` (48 named presentations; 20 canonical tools
  — skills/hub, targets, target scaffolds, devices — still fall back to
  generic). Full tool inventory: `wireframes/reference/tool-ui-cards.md`.
- **Golden-fixture source**: `src/dashboard/mock_agent.py` emits a scripted
  turn (think -> delegate -> plan -> write -> terminal) usable for
  protocol-conformance tests without a live model.

## 3. Event mapping — Bridge v2 <-> AG-UI (edge contract)

Engine -> client:

| Bridge v2 (desktop) | AG-UI (edge) | Notes |
|---|---|---|
| `turn_started` | `RUN_STARTED` | threadId/runId from session identity |
| `token` | `TEXT_MESSAGE_START` (first) + `TEXT_MESSAGE_CONTENT` … `TEXT_MESSAGE_END` (at turn end) | messageId stable per turn |
| `reasoning` | `REASONING_*` message events (exact member names settled against the installed `ag-ui-protocol` package in Phase 1) | visible-thinking contract: summary text only |
| `tool_call_start` | `TOOL_CALL_START` + `TOOL_CALL_ARGS` | args streamed whole (v2 sends whole arguments today) |
| `tool_call_end` | `TOOL_CALL_END` + `TOOL_CALL_RESULT` | status maps: passed->success payload, failed->error |
| `plan_updated`, `todo_updated` | `STATE_DELTA` (JSON Patch on `/plan`, `/todos`) or `CUSTOM{name:"plan_updated"}` | choose STATE_DELTA if the consuming client renders state; CUSTOM is the fallback — decide in Phase 1 by what the webview actually consumes |
| `verification_updated` | `CUSTOM{name:"verification_updated"}` + A2UI surface ops (Phase 3) | receipt is a surface, not just an event |
| `safety_request` | **Interrupt** (`RUN_FINISHED` with interrupt payload / SDK HITL pattern) | resume carries the reply (below) |
| `clarify_request` | **Interrupt** (questions payload) | same |
| `subagent_updated`, `subagent_list`, `subagent_background_completed` | `CUSTOM` (namespaced `crusor.*`) | no AG-UI standard exists |
| `telemetry`, `context_status` | `CUSTOM{name:"crusor.telemetry"}` etc. | never block the main stream |
| `turn_done` | `RUN_FINISHED` | |
| `turn_failed`, `error` | `RUN_ERROR` | |
| `session_info`, `session_messages`, `events_replay`, `workspace.bound`, `checkpoint_event`, `host_tool_request`, `inline_completion_result`, `next_edit_result`, `llm.*` | **Not mapped** | desktop-only concerns; they are why v2 stays |

Client -> engine:

| AG-UI (edge) | Bridge v2 (desktop) |
|---|---|
| `RunAgentInput.messages` (user turn) | `prompt` |
| interrupt resume (approval) | `safety_reply{approved, always_allow}` |
| interrupt resume (answers) | `clarify_reply{answers}` |
| run abort (client disconnect / stop) | `cancel` |
| forwarded state (mode, reasoning effort) | `prompt{mode, reasoning_effort}` |

## 4. A2UI — Crusor Catalog v1

Client-side component types the native renderer will support. Each maps to an
existing renderer builder; props are data-bound via JSON Pointer paths into the
surface's data model (A2UI semantics, same as `crusor_task_schema.json`).

| Component | Renders as | Reuses | Data (typical paths) |
|---|---|---|---|
| `Card` | bordered surface container | tool-row body chrome | child |
| `Column` / `Row` | layout stacks | flex helpers | children |
| `Text` | text (variants: h3/body/caption/mono) | markdown copy pass | `/title`, `/status`, … via `{path}` |
| `Diff` | diff preview block | file-write body diff | `/diff`, `/file`, `/added`, `/removed` |
| `TerminalOutput` | command + stdout window (4rem tail-pinned) | `terminalBody` | `/command`, `/output`, `/exit`, `/duration` |
| `PlanList` | task rows with status glyphs | `planListBody` | `/steps[]{description,status}` |
| `Receipt` | verification ledger: check rows + verdict | verification body (rewritten honest) | `/checks[]{label,status}`, `/verdict` |
| `QuestionForm` | clarify questions (choice + free text) | `clarifyCard` | `/questions[]`, answers via action event |
| `ApprovalBar` | approve/reject/always actions | `approvalDock` | `/name`, `/warning`, action events out |
| `Image` | screenshot / generated media | browser + media bodies | `/src`, `/alt` |
| `Button` | action button (emits `userAction`) | renderer buttons | `/label`, `/action` |

**Surface lifecycle in the renderer (Phase 2):** a surface store keyed by
`surfaceId` inside the transcript model; ops applied in order; `updateDataModel`
patches re-render only that surface (same paint-isolation discipline as
`paintSignature` — never repaint the transcript); unknown component/action =
drop + log, never throw; surfaces die with their turn unless pinned by id.

**Action events out:** `Button`/`QuestionForm`/`ApprovalBar` emit A2UI
`userAction` -> renderer host -> existing v2 commands (`safety_reply`,
`clarify_reply`, `host.revealFile`, `host.openDiff`). No new engine commands.

## 5. Phases

### Phase 1 — AG-UI edge hardening + mapping (engine)
- `src/server.py`: bind `127.0.0.1` by default; `CRUSORAI_HOST` env to override;
  token required when non-loopback (`CRUSORAI_DASHBOARD_TOKEN` pattern from
  `src/dashboard_server.py:372-375`). Refuse public bind without token.
- New `src/agui/__init__.py` + `src/agui/mapping.py`: pure functions
  v2-event-dict -> AG-UI-event-dict per §3 (used by tests now, by a gateway
  endpoint when the web surface needs it).
- Tests: `src/tests/test_agui_mapping.py` — golden sequences built from
  `mock_agent` shapes: (a) text turn, (b) tool turn, (c) approval interrupt +
  resume, (d) failed turn. Assert exact AG-UI type order.
- Acceptance: tests green; server refuses `0.0.0.0` without token; branding +
  protocol tests untouched and green.

### Phase 2 — A2UI surface manager + Catalog v1 (desktop)
- `common/crusorAIProtocol.ts`: accept the A2UI envelope where it already
  flows — tool results shaped `{"a2ui_operations": [...]}` (the shape
  `display_crusor_task` returns). No protocol version bump: it rides
  `tool_call_end.result`.
- New `browser/crusorA2UISurface.ts`: surface store + op application +
  component builders for Catalog v1 (wrapping existing body builders).
- Renderer: when a card tool's result parses as A2UI ops, render via the
  surface manager instead of `familyBody`. `display_crusor_task` migrates to
  the generic path; bespoke `taskToolCard` is deleted once parity is proven.
- Tests: extend `src/tests/test_desktop_renderer_architecture.py` (surface
  store isolation, unknown-component drop, data-model patch re-render);
  re-emit bundle (`node scripts/emit-crusorai-bundle.mjs` in
  `desktop/vscode`).
- Acceptance: task card renders identically through the generic path;
  renderer architecture suite green; no raw tool id visible anywhere.

### Phase 3 — Verification Receipt surface (engine + desktop)
- Engine: `verify` / `typecheck_workspace` results gain an A2UI `Receipt`
  surface (checks with honest per-check status + evidence paths), emitted
  alongside the text result; non-A2UI clients keep the text.
- Renderer: `Receipt` component via Catalog v1; replaces the placeholder
  verification body rows.
- Tests: python golden-surface test (schema-valid ops, catalog-only
  components); renderer test for receipt render.
- Acceptance: a real verified turn on the laptop shows the receipt surface;
  failed check renders red, never a green verdict.

### Phase 4 — Approval as A2UI (later, optional)
- Re-express `approvalDock` content via `ApprovalBar` + `Diff` components.
  The dock's keyboard contract (Cmd/Ctrl+Enter, Esc) and `safety_reply`
  flow do not change.
- Acceptance: existing approval tests pass unchanged.

## 6. Guardrails (all phases)

- **Fixed catalog only.** The agent can never inject component types,
  HTML, styles, or scripts. Unknown op/component/action: drop + log.
- **Validation at both ends:** engine validates ops against Catalog v1
  schemas before emit; renderer re-validates before paint.
- **Size caps:** ops per surface, components per surface, text lengths —
  bounded like `boundedText` today.
- **Fallbacks:** no CopilotKit -> stdlib A2UI fallback (existing pattern);
  no A2UI in result -> today's family bodies; A2UI disabled by flag ->
  everything renders as before.
- **Security:** Phase 1's bind/token fix lands before the AG-UI endpoint
  is used beyond localhost development.
- **No global chrome changes** in this plan; colors keep deriving from the
  live workbench theme (forced-black product defaults already shipped
  separately). Branding gate (`test_crusorai_branding.py`) must stay green —
  nothing here adds hex to `crusorAI-tokens.css` or removes the seed colors
  in `crusorTheme.ts`.

## 7. What this plan deliberately does NOT do

- No migration of the desktop off Bridge v2 (Decision 1).
- No latency promises from protocol work (see Decision 1 rationale;
  latency is the agent-core track: context size, tool parallelism).
- No full-generative UI: transcript/composer/streaming stay custom
  (Decision 4).
- No webview A2UI work (Decision 3).
