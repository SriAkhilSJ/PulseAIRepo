# Crusor Frontend Understanding

Status: read-only investigation. No source, backend, test, branch or commit was modified. This report was the only file created.

Repository state observed: branch `feat/prompt-cache-stabilization`, HEAD `fb5bd528b40933346c4004a1490154683dc0d40e`, `origin/main` `8fa4e240be65b98472c9b2d3a505ade2aea1a5c6`. The working tree still contains the preserved excluded entries (unrelated app work, diagnostics, historical reports).

---

## 1. Frontend architecture overview

Crusor is not a webview/React frontend. The Agent UI is a first-party, framework-neutral DOM renderer mounted inside the VS Code-derived workbench.

```text
Electron workbench
  └─ contrib/crusorai
       ├─ view container + Agent view pane (auxiliary bar)
       ├─ Manager editor tab (full-width)
       ├─ ICrusorAIRendererService singleton
       │    ├─ engine frame subscription
       │    ├─ mutable session/turn state
       │    ├─ CrusorAIRenderModel projection
       │    └─ mounts (agent / manager)
       ├─ crusorAIRenderer.ts (DOM painter)
       ├─ common/crusorAICards.ts (card schema validation)
       ├─ common/crusorAIProtocol.ts (typed protocol)
       ├─ css/theme/icons
       └─ engine sidecar chain
            ├─ electron-browser/crusorAIEngineService.ts
            ├─ node/crusorAIWorkerProcessService.ts
            └─ python -m src.bridge
```

The Python bridge is the only engine connection. It emits newline-delimited JSON v2 frames; the worker forwards each line to `ICrusorAIEngineService`, which fires `onDidReceiveFrame`; the singleton renderer service consumes it in `acceptFrame()`.

Key registration paths:

- `browser/crusorAI.contribution.ts:78` registers `ICrusorAIRendererService` as a delayed singleton.
- `browser/crusorAI.contribution.ts:102-126` registers the right auxiliary-bar container and `CrusorAIViewPane`.
- `browser/crusorAI.contribution.ts:128-135` auto-hides the view until the focus command.
- `browser/crusorAI.contribution.ts:151-174` defines `Crusor: Open Agent`, bound to Ctrl/Cmd+L.
- `browser/crusorAIViewPane.ts:54-130` builds the agent body, installs the live theme, mounts the native renderer.
- `browser/crusorAIManagerEditor.ts:17-30` hosts the same renderer service as a full-width editor surface.
- `electron-browser/crusorAIEngineService.ts:39-40,71,162` is the frame event boundary.
- `node/crusorAIWorkerProcessService.ts:156-178,212-221` spawns `python -m src.bridge` and forwards stdout frames.

The renderer has no React components and no arbitrary model markup. `crusorAIRenderer.ts` builds DOM with `element()` and text nodes. This is the design to preserve.

---

## 2. Complete relevant frontend file map

| File | Responsibility |
|---|---|
| `browser/crusorAI.contribution.ts` | View container, view registration, commands, keybinding, Manager registration, service singleton. |
| `browser/crusorAIViewPane.ts` | Agent pane shell, theme install, mount point, preview tab. |
| `browser/crusorAIManagerEditor.ts` | Manager editor tab, same renderer service. |
| `browser/crusorAIRendererService.ts` | Single event/state owner; frame routing; model projection; hydration; restart; session UI state. |
| `browser/crusorAIRenderer.ts` | All DOM rendering: transcript, reasoning, tool cards, plan strip, approval dock, typed cards, composer, Manager. |
| `browser/crusorAIActivity.ts` | Tail activity row, liveness/quiet logic, activity part model, timers. |
| `browser/crusorAIRunSummary.ts` | Tool categories/grouping and summary clauses. |
| `browser/crusorAIToolCatalog.ts` | Tool presentation families/titles/glyphs. |
| `browser/crusorAIIcons.ts` | Codicon mapping. |
| `browser/crusorAIReasoningBlocks.ts` | Repairs glued/streamed reasoning blocks. |
| `browser/crusoraiCardFormat.ts` | Diff/terminal/markdown/card formatting helpers. |
| `browser/crusorA2UISurface.ts` | Optional A2UI Catalog v1 renderer from tool results (`a2ui_operations`). |
| `browser/crusorTheme.ts` | Live workbench theme → Crusor semantic palette. |
| `browser/media/crusorAI.css` | Transcript, tools, plan, approval, diff, cards, composer, narrow layouts. |
| `browser/media/crusorAI-tokens.css` | Theme fallback token chains. |
| `common/crusorAIProtocol.ts` | Typed client/server frames and identity fields. |
| `common/crusorAIProtocol.generated.ts` | Generated protocol names from `src/bridge/protocol_v2.json`. |
| `common/crusorAICards.ts` | Versioned card validation, sanitization, unknown-card fallback, headline. |
| `common/crusorAIRendererService.ts` | Renderer service interface (mount/new/open/turn entry points). |
| `common/crusorAISessionProjection.ts` | Engine rows → workbench Agent Sessions rows. |
| `common/crusorAISessionStore.ts` | Client session rows/attention state. |
| `browser/crusorAISessionController.ts` | Registers Crusor sessions with the workbench Agent Sessions service. |
| `common/crusorAIEngineService.ts` | Engine service interface and frame event. |
| `electron-browser/crusorAIEngineService.ts` | Electron implementation, worker lifecycle, frame parsing. |
| `node/crusorAIWorkerProcessService.ts` | Spawns the Python sidecar and transports newline frames. |
| `browser/crusorAIWorkbenchService.ts` | Workbench host actions (diff, files, editor, workspace). |
| `common/crusorAIWorkbenchService.ts` | Host service contract. |
| `browser/crusorAIPreviewService.ts` | Preview window/proxy (adjacent, not Agent Core). |
| `browser/crusorAIHubDialog.ts` | Skills/MCP hub (adjacent surface). |
| `browser/crusorAISkillsHub.ts` | Skills Hub operations (adjacent). |
| `browser/crusorAIOneShot.ts` | One-shot jobs (adjacent). |

Typed card contract: `common/crusorAICards.ts:7-14` declares schema v1 and the nine card types. It is already present and must not be duplicated.

---

## 3. Component and renderer responsibilities

### Renderer service state

`crusorAIRendererService.ts:284-340` owns one mutable surface:

- `parts` — ordered text/tool/reasoning timeline (`:289-296`).
- `reasoningParts` — per-LLM-call reasoning (`:297-299`).
- `approvals` — pending approvals keyed by tool id, tree-aware (`:308-329`).
- `plan`, `verification`, `telemetry` (`:335-337`).
- `cards` and `cardOrder` — typed agent cards keyed by stable id (`:338-340`).
- `tools` live in `private readonly tools = new Map<string, CrusorAIToolView>()` (`crusorAIRendererService.ts:183`; used throughout `:2335-2435`).
- `history` — hydrated turns (`:1393-1465`).

`crusorAIRendererService.ts:955-1020` projects all of this into `CrusorAIRenderModel`; `cards` are emitted in `cardOrder` (`:1006`), not in transcript parts.

### Mount and paint

- `crusorAIRendererService.ts:609-620` mounts the renderer and pushes the initial model.
- `crusorAIRenderer.ts:4721-4759` owns mount-scoped UI state (`openTools`, `closedTools`, plan disclosure), streaming isolation, and the activity ticker.
- `crusorAIRenderer.ts:5119+` implements the update/paint loop.
- `crusorAIRenderer.ts:4462-4484` renders the Agent shell; `agentColumn()` (`:4416-4459`) lays out plan strip, engine status, transcript, approval dock, clarify dock, todo stack, then composer.

### Transcript and timeline

`crusorAIRenderer.ts:2680-2767` (`assistantTurn`) is the core ordering engine:

1. Renders the assistant label.
2. Walks `parts` in arrival order (`:2728-2749`).
3. Reasoning parts render as `thinkingBlock()` at their pinned index (`:2729-2739`).
4. Consecutive tool parts flush into `toolSection()` at their pinned index (`:2722-2750`).
5. Text parts render where they arrived (`:2746-2748`).
6. Orphan tools with no part append after the timeline (`:2751-2754`).
7. **All typed agent cards are appended after the entire timeline** (`:2755-2756`).
8. Legacy assistant text without parts appends last (`:2757-2759`).

This is the exact current ordering behavior; it is not claimed to be correct for cards.

### Thinking/reasoning

- Live: `crusorAIRendererService.ts:2316-2332` handles `reasoning` frames, pins `parts` index, seals the block when a tool starts (`:2336-2340`).
- Render: `crusorAIRenderer.ts:2627-2662` (`thinkingBlock`) — live shimmering `Thinking`, settled `Thought`, disclosure state.
- Persisted: `crusorAIRendererService.ts:1408-1415` hydrates `message.reasoning` into both `reasoningParts` and a pinned part.
- This is implemented and working in normal chat.

### Tool activity and groups

- Live frames: `tool_call_start` (`:2335-2355`), `tool_call_args` (`:2356-2373`), `tool_call_progress` (`:2374-2390`), `tool_output` (`:2391-2400`), `tool_call_end` (`:2401-2435`).
- Rendering: `crusorAIRenderer.ts:2397-2452` (`toolSection`), grouping via `activityGroupKey()` (`:2340-2355`) and `splitActivityGroups()` in `crusorAIRunSummary.ts:114-145`.
- Categories and clauses: `crusorAIRunSummary.ts:12-79,147-189`.
- File edits do not fold; they render their own diff card (`crusorAIRenderer.ts:2348-2352`).
- This is implemented and working for the normal chat/tool path.

### Plan UI

- Live frame: `plan_updated` → `plan` (`crusorAIRendererService.ts:2333-2334`).
- Chat backend emits `plan.created` (`src/graphs/chat_graph.py:8479`); bridge maps it to `plan_updated` (`src/bridge/__main__.py:666`).
- Render: `crusorAIRenderer.ts:2492-2516` (`planStrip`), placed above the transcript by `agentColumn()` (`:4418-4419`), plus a typed plan card in the card stack (`:2804-2817`).
- So there are two plan surfaces: the persistent top strip and the typed card.

### Approval UI

- Backend: graph approval queue emits `tool.approval.request` (`src/graphs/chat_graph.py:7589`); orchestrator approval gateway also emits it (`src/orchestration/approval_gateway.py:238-239`).
- Bridge maps to `safety_request` (`src/bridge/__main__.py:662`).
- Service stores the tree-wide approval (`:2138-2141`) and also puts the tool in `approval` state (`:2436-2446`).
- Renderer: `toolRow` approval rendering plus `approvalDock()` (`crusorAIRenderer.ts:3188-3300`), dock is outside the transcript in `agentColumn()` (`:4439-4440`).
- Approval is implemented and working on both paths.

### File-change/diff

- Normal chat: tool result is mapped to a file-change card by `src/bridge/agent_cards.py:285-304`; diff rendering exists in `crusorAIRenderer.ts:1481-1600` and edit/write card families.
- Orchestrator: no tool result events; only terminal receipt `changed_files` become file cards (`src/bridge/agent_cards.py:340-349`).

### Test results / verification / delivery / cost

- Test results: chat tool result → `test_result_card()` (`agent_cards.py:305-308,401+`); receipt tests → card at terminal (`:351-363`).
- Verification: chat `verification.updated` → frame (`bridge:668`) → `verification` state (`:2545-2546`); receipt → verification card (`agent_cards.py:365-375`).
- Delivery: `turn_done` receipt → delivery card (`agent_cards.py:256-274`).
- Cost: chat `analytics.update` → telemetry (`bridge:665`) → cost card (`agent_cards.py:244-254`); receipt usage → cost card (`:377-397`).
- Renderer cards: `agentCardView()` (`crusorAIRenderer.ts:2772-2862`) and `agentCardStack()` (`:2864-2870`).
- All nine cards exist; none need a new schema.

### A2UI

`crusorA2UISurface.ts` is an optional, fixed Catalog v1 surface carried inside `tool_call_end.result.a2ui_operations`. It is not the typed `agent_card` system and is rendered inside tool bodies via `crusorAIRenderer.ts:1720-1726`. It must not be merged into or replaced by the card stack.

---

## 4. Existing Agentic UI inventory

| UI element | Implementation | Data source | Live? | Persisted? |
|---|---|---|---|---|
| Assistant text | `assistantTurn` text parts `:2680,2746-2748` | `token` frames (`service:2309-2311`) | Yes | Yes (checkpoint messages) |
| Streaming label | `assistantTurn` label `:2702` | `running`, `cancelRequested` | Yes | N/A |
| Thinking block | `thinkingBlock` `:2627-2662` | `reasoning` frames; `message.reasoning` | Yes | Yes |
| Tool card | `toolSection`/`toolRow` `:2397-2452` | `tool_call_*`, `tool_output`, `tool_call_end` | Yes | Tool calls/results via checkpoint hydration (`:1420-1437`) |
| Activity group | `splitActivityGroups`, `activityGroupKey` `:2340-2452` | groups of consecutive same-key tools | Yes | Not separately persisted; rebuilt from hydrated tools |
| Tail activity row | `crusorAIActivity.ts:133-207` | model text/reasoning/tools/timer | Yes | Ephemeral |
| Plan strip | `planStrip` `:2492-2516` | `plan_updated`; hydrated history sets `[]` (`:1455`) | Yes for chat | Live only; not rehydrated |
| Typed plan card | `agentCardView` `:2804-2817` | `agent_card` (plan) | Yes | Journaled; loaded via `session_messages.cards` |
| File-change card | `agentCardView` `:2818-2821` | companion/terminal receipt | Yes chat; terminal engineering | Journaled; loaded as global current cards |
| Approval card | `agentCardView` `:2822-2827` | `safety_request` companion | Yes | Journaled; loaded |
| Approval dock | `approvalDock` `:3188-3300` | `approvals` map | Yes | Pending request is runtime state; not history |
| Tool card (typed) | `agentCardView` `:2828-2831` | `agent_card` tool | Yes | Journaled; loaded |
| Test-results card | `agentCardView` `:2832-2838` | tool result or terminal receipt | Chat: live when a test tool runs; engineering: terminal | Journaled; loaded |
| Verification card | `agentCardView` `:2839-2845` | `verification_updated` or receipt | Chat: live; engineering: terminal | Journaled; loaded |
| Delivery card | `agentCardView` `:2846-2850` | `turn_done.receipt` | Terminal | Journaled; loaded |
| Cost card | `agentCardView` `:2851-2859` | `telemetry` or receipt usage | Chat: live; engineering: terminal | Journaled; loaded |
| A2UI surface | `crusorA2UISurface.ts` | tool result `a2ui_operations` | With tool result | With tool result |
| Copy action | `assistantTurn` `:2760-2766` | assistant text, turn settled | End of turn | N/A |

---

## 5. Backend-to-frontend event flow

### Normal chat/tool path

```text
LangGraph planner/ai/tools/finalize
  → event_bus.emit
       message.agent.chunk / reasoning.update / tool.call / tool.args / tool.result /
       plan.created / verification.updated / analytics.update / tool.approval.request
  → Bridge._project_event (src/bridge/__main__.py:651-673)
       token / reasoning / tool_call_* / plan_updated / verification_updated /
       telemetry / safety_request
  → Bridge._forward_events (src/bridge/__main__.py:1003-1060)
       emit(frame); _emit_companion_cards(frame)
  → _emit_companion_cards (src/bridge/__main__.py:615-644)
       agent_card frames; journal append
  → Electron worker stdout (node/crusorAIWorkerProcessService.ts:156-178)
  → engine service onDidReceiveFrame (electron-browser/crusorAIEngineService.ts:71,162)
  → renderer service acceptFrame (crusorAIRendererService.ts:2097+)
  → state maps/parts/model
  → mount.update/paint (crusorAIRenderer.ts:4721+, 5119+)
```

### Engineering path

```text
LangGraph task_manager
  → engineering_task_node (src/graphs/chat_graph.py:5261)
  → EngineeringExecutionOrchestrator.run_task_request (src/graphs/chat_graph.py:5394)
       orchestrator.emit_progress (src/orchestration/orchestrator.py:516-532)
         → on_progress(...) ONLY
  → DeliveryContract
  → engineering_task_node emits one message.agent.chunk summary (src/graphs/chat_graph.py:5331-5340)
  → bridge terminal receipt / companion cards
```

**Critical difference:** `orchestrator.run_task_request()` is called without `on_progress` (`src/graphs/chat_graph.py:5394-5397`). Therefore `emit_progress` has no listener and none of its stage updates reach `event_bus`. The orchestrator itself has no `event_bus` imports/emits (verified by `rg event_bus src/orchestration`).

The only engineering events that reach the frontend live are:

- `turn_started` → activity card.
- approval gateway `tool.approval.request` → approval frame/card.
- final summary chunk and terminal receipt → delivery/plan/file/test/verification/cost cards.

Plan, implementation/tool activity, test execution, verification and cost do **not** stream live during engineering execution. They appear only at the terminal receipt, if the receipt contains the relevant fields.

---

## 6. Normal chat versus engineering execution

| Capability | Normal chat/tools | Engineering orchestrator |
|---|---|---|
| Token streaming | Yes, `message.agent.chunk` per token | One summary chunk at end (plus any pre-delegation text) |
| Reasoning | Yes, `reasoning.update` | No orchestrator reasoning events; model reasoning is not exposed |
| Live activity card | `turn_started`, then tool/LLM events | `turn_started` only; no intermediate stages |
| Plan | `plan.created` → `plan_updated` → strip/card | `emit_progress` not wired; only receipt plan card if `receipt.plan` |
| Tool/file activity | `tool.call`/`tool.result` → cards | No tool events; implementation is internal adapter/engine work |
| Approval | `safety_request` → dock/card | Yes, approval gateway emits `tool.approval.request` |
| Test results | Test tool result → card | Only receipt `tests` → card |
| Verification | `verification.updated` → card | Only receipt `verification_status` → card |
| Delivery | `turn_done.receipt` → card | Same |
| Cost | `analytics.update` → telemetry/card | Only receipt usage → card |
| Persistence | checkpoint messages + journal cards | same, but cards are terminal-only |

This is the primary verified gap: the components exist, but the engineering path does not publish its progress into them.

---

## 7. Conversation timeline and card ordering

### What the current implementation actually does

`assistantTurn()` walks `parts` in arrival order. Text, reasoning and tools are interleaved correctly. But at the end it does:

```ts
const cards = agentCardStack(spec.cards ?? []);
if (cards) { response.append(cards); }
```

`crusorAIRenderer.ts:2755-2756`

Therefore:

- All typed cards for a turn render **after every text and tool part**, regardless of when their `agent_card` frame arrived.
- A plan card, approval card, tool card, test card, verification card, delivery card and cost card all share the same bottom stack.
- The legacy plan strip is not part of the timeline at all; it is above the transcript (`agentColumn:4418-4419`).
- The approval dock is outside the transcript (`agentColumn:4439-4440`).
- The card order inside the stack is `cardOrder`, which is first-arrival order of unique `cardId` (`service:338-340,1006`); updates replace in place.

This is not an accident of the data. It is the literal render path.

### Persistence/replay ordering

- Cards are journaled as `agent_card` events (`bridge:628-637`).
- `session_messages` reads the latest card per `card_id` from the journal and returns them (`bridge:1839-1863`).
- The service applies them to the global live `cards` map after `hydrateTranscript()` (`service:2674-2684`).
- `hydrateTranscript()` has no card field in `HydratedTurn` (`:1394`) and history rendering never passes `cards` (`:2917-2930`).
- Result: after a reload, cards are not attached to their original history turn; they appear in the current bottom `assistantTurn` card stack. The transcript text/tools/reasoning restore correctly, but card placement and per-turn association are only partial.

### Consequence

The existing cards are real and data-driven, but their chronological placement is wrong for an execution narrative. Fixing this is a renderer/model-ordering change, not a new card system.

---

## 8. Existing functionality that must be preserved

Do not regress or duplicate:

1. `CrusorAITurnPart` text/tool/reasoning ordering (`crusorAIRenderer.ts:64-69,2728-2750`).
2. Streaming fast path and last-text-part patching (`:4733-4755,5119+`).
3. Thinking block behavior and hydration (`:2627-2662`; `service:2316-2332,1408-1415`).
4. Tool grouping law and file-edit cards (`runSummary.ts:114-145`; `renderer.ts:2340-2452`).
5. Plan strip disclosure and per-step status (`renderer.ts:2492-2516`).
6. Approval dock and all approval scopes (`renderer.ts:3188-3300`).
7. A2UI Catalog v1 surfaces inside tool results (`crusorA2UISurface.ts`).
8. Typed card schema v1 and unknown-card safe fallback (`common/crusorAICards.ts:7-113`).
9. Theme derivation and CSS variables (`crusorTheme.ts:347-407`; `crusorAI.css`).
10. Session list/Agent Sessions integration (`crusorAISessionController.ts`).
11. History hydration and stream-adoption rules (`service:1393-1465,2902-2980`).
12. Electron checkpoint reload and bridge restart behavior.

---

## 9. Verified implementation gaps

| Feature | Frontend implementation | Backend/event source | Live event delivery | Rendering status | Actual gap |
|---|---|---|---|---|---|
| Chat token streaming | `assistantTurn` text parts; service `token` | `message.agent.chunk` → `token` | Yes | IMPLEMENTED AND WORKING | None |
| Thinking | `thinkingBlock` | `reasoning.update` → `reasoning`; checkpoint reasoning | Yes | IMPLEMENTED AND WORKING | None |
| Tool cards | `toolSection`/`toolRow` | `tool.call`/`tool.result` | Yes (chat) | IMPLEMENTED AND WORKING | Engineering path emits none |
| Activity groups | `splitActivityGroups` | Consecutive tool frames | Yes (chat) | IMPLEMENTED AND WORKING | Engineering has no tool frames |
| Plan strip | `planStrip` | `plan.created` → `plan_updated` | Yes (chat) | IMPLEMENTED AND WORKING for chat | Engineering has no plan event |
| Typed plan card | `agentCardView` | companion `agent_card` | Yes (chat) | IMPLEMENTED BUT NOT RENDERED IN ORDER | Appended after timeline |
| File-change card | `agentCardView` | tool result companion; receipt files | Chat live; engineering terminal | PARTIALLY IMPLEMENTED | Engineering has no live file event |
| Approval card/dock | `approvalDock`, `agentCardView` | `tool.approval.request` → `safety_request` | Yes, both paths | IMPLEMENTED AND WORKING | Card is appended after timeline; dock is outside |
| Test-results card | `agentCardView` | test tool result; receipt tests | Chat live; engineering terminal | PARTIALLY IMPLEMENTED | No live engineering test event |
| Verification card | `agentCardView`; `verification` inspector | `verification.updated`; receipt | Chat live; engineering terminal | PARTIALLY IMPLEMENTED | No live engineering verification event |
| Delivery card | `agentCardView` | `turn_done.receipt` | Terminal | IMPLEMENTED AND WORKING | Appended last (correct terminal placement) |
| Cost card | `agentCardView`; telemetry inspector | `analytics.update`; receipt usage | Chat live; engineering terminal | PARTIALLY IMPLEMENTED | No live engineering cost event |
| Activity card | `agentCardView` | `turn_started`, `llm.request` | Yes | IMPLEMENTED BUT NOT RECEIVING ENGINEERING PROGRESS | Only “Understanding request”; no stage updates |
| Card ordering | `agentCardStack` after timeline | `agent_card` frames | Yes | IMPLEMENTED BUT NOT RENDERED CORRECTLY | All cards appended after text/tools |
| Card persistence | journal + `session_messages.cards` | `agent_card` journal | Replay | PARTIALLY IMPLEMENTED | Cards not attached to history turns |
| Engineering stage progress | none | `orchestrator.emit_progress` | **No** | GENUINELY NOT RECEIVING EVENTS (frontend present) | `on_progress` not passed at `chat_graph.py:5394` |
| A2UI cards | `crusorA2UISurface.ts` | tool result `a2ui_operations` | With tool result | IMPLEMENTED AND WORKING | Not the same system; keep separate |

Note on classification: “GENUINELY MISSING” is not used for any of the nine card types. Every type exists. The engineering progress pipeline is the genuinely missing event wiring, not a missing component.

---

## 10. Recommended minimal integration fixes

These are proposals only; none were implemented.

### Fix 1 — wire orchestrator progress into existing events (highest value)

In `engineering_task_node` (`src/graphs/chat_graph.py:5394`), pass an `on_progress` callback to `run_task_request`. Map the returned `DesktopVisibilityReporter` view to existing event names/cards:

- `current_step`/stage → `agent.card` `activity` with stable card id `${turn}:activity`, updating the same card.
- plan nodes/completed/pending/failed → `agent.card` `plan` or existing `plan.created` shape; use stable `${turn}:plan`.
- implementation/test/verification stages → existing `tool`/`test_results`/`verification` card data where semantically true; do not fabricate tool calls.
- cost/tokens → existing `analytics.update`/receipt cost card.

This uses `agent_card` and the existing event bus. Do not create another event system or schema.

### Fix 2 — restore chronological placement without duplicating renderers

Extend the existing turn part union with a card pin (for example `{kind:'card', cardId}`), or add a card sequence field to `CrusorCardView` and merge by sequence. Then in `assistantTurn`:

- render a card where its card pin/sequence lands, not always at the end;
- keep the terminal delivery/cost cards at the end;
- keep approval dock outside the composer for security UX;
- keep plan strip as the persistent top summary if desired.

No second card component is needed; `agentCardView()` stays the only renderer.

### Fix 3 — persist cards per turn

Add `cards` to `HydratedTurn` and pass them to history `assistantTurn` calls. On `session_messages`, group cards by `turnId` instead of placing every card in the current live stack. Cards already carry stable `card_id`/`turn_id`; no schema change is required.

### Fix 4 — tests before/with the fix

Add tests for:

- engineering `on_progress` emits activity/plan/file/test/verification cards;
- card pin ordering relative to text/tools;
- card restoration attached to the correct history turn;
- no duplicate card ids on update/replay;
- unknown card remains visible;
- dark/light/narrow card layout.

---

## 11. Relevant tests and missing coverage

### Existing coverage

- `src/tests/test_agent_cards.py` — schema v1, all nine types, unknown fallback, bounded data, plan/approval/verification/cost/delivery projection, scripted turn cards (`:34-212`).
- `scripts/test_crusorai_cards.mjs` — runtime TS validation: unknown types, prototype pollution, invalid versions, cost headline, frame validation.
- `src/tests/test_desktop_renderer_architecture.py` — source-level renderer contracts: plan strip (`:1253,1285`), approval dock (`:578,2622,2696`), streaming isolation (`:657`), tool cards (`:1970,2103,2236,2323`), A2UI (`:1696-1729`), child/session behavior.
- `src/tests/test_utf8_reliability.py` — UTF-8 at broker/protocol/file boundaries.
- `src/tests/test_invocation_reconciliation.py` — gateway/ledger/receipt/UI cost-card identity (13 tests).
- `desktop/vscode/scripts/accept-crusorai-checkpoint.mjs` — real Electron reload and bridge restart; transcript/cards existence, no re-execution.
- `desktop/vscode/scripts/accept-crusorai-engineering.mjs` — real Electron engineering: approval, cards existence, reload and bridge restart.
- `desktop/vscode/scripts/accept-crusorai-streaming.mjs` — deterministic card-flow screenshots: activity/plan/approval/test/verification/delivery/cost.
- `src/tests/test_termination_diagnosability.py`, `test_step_tracker.py` — terminal trace and diagnostics reports.

### Missing coverage

1. No test that orchestrator `emit_progress` is connected to `event_bus` or that engineering progress cards appear live.
2. No DOM test for `agentCardStack` placement relative to text/tool parts.
3. No test for card-per-turn persistence/hydration; replay tests check existence, not attachment to the original turn.
4. No test for engineering live cost/test/verification card arrival before terminal.
5. No test that duplicate `agent_card` replays do not duplicate card order.
6. No dark/light/narrow screenshot test for typed cards (CSS exists, no acceptance assertion).
7. No test asserting plan strip vs plan card consistency when both exist.
8. No test that engineering activity card updates stage rather than staying "Understanding request".

---

## Bottom line

Crusor already has the complete Agentic UI surface: typed cards, thinking, tool activity/groups, plan, approval/diff, test results, verification, delivery and cost. The failure mode is not missing frontend. The primary verified causes are:

1. Engineering orchestrator progress is not wired to the event bus, so its plan/tool/test/verification/cost stages never reach the existing UI live.
2. Typed cards are appended after the transcript timeline instead of being placed chronologically.
3. Cards are persisted globally and are not reattached to their original history turn on replay.

Any fix should preserve the existing renderer, schema, event bus, plan strip, approval dock, A2UI surface and checkpoint behavior.
