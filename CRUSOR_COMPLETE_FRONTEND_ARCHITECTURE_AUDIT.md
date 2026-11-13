# Crusor Complete Frontend Architecture Audit

**Type:** read-only investigation. No product source, test, protocol, schema or configuration was modified. This report is the only file created.
**Repository:** `PulseAIRepo` · branch `feat/prompt-cache-stabilization` · HEAD `fb5bd528b40933346c4004a1490154683dc0d40e` (no commit made)
**Working tree at audit start:** 216 entries, 0 deletions; all pre-existing work preserved.
**Evidence rule:** every claim below is tied to a file and line in the current tree, or explicitly marked as unverified.

---

## 1. Executive summary

Crusor's frontend is not a webview or a React app. It is a **framework-neutral DOM renderer mounted directly into a VS Code-derived workbench**, fed by an NDJSON bridge to a Python sidecar. That architecture is deliberate and, on the chat/tool path, it is genuinely good: typed cards, streaming tool arguments, live write diffs, reasoning disclosure, approval dock, per-turn card ownership, theme-derived tokens and a security-first card validator all exist and work.

The real-provider failure you experienced is **not primarily a frontend rendering defect**. The evidence separates cleanly:

1. **Test A never reached the model at all.** `parse_prompt_contract` (`src/orchestration/contract.py:311-315`) only recognises a symbol when it follows the literal token `def`/`function`, so *"a divide(a, b) function"* produced an empty symbol list and `:522` rejected the plan before dispatch. Zero provider calls. The only events that ever existed were: one activity card and one error string.
2. **The frontend then mislabelled that failure.** `turn_done` arrives with `completed: false`, but the renderer derives its outcome from `cancelled` and the receipt only (`crusorAIRendererService.ts:2708-2715`). No receipt on that path ⇒ the turn painted as **completed**, with the failure text as ordinary assistant prose. There was no error state, no failed row, no actionable next step. That is a real frontend defect and it is independent of the contract bug.
3. **Engineering turns cannot stream tokens by design.** The orchestrator's model calls go through `ModelExecutionAdapter` as a single blocking `invoke_model(...)` with no callbacks (`src/orchestration/model_adapter.py:1497-1503`), and nothing in `src/orchestration` emits `message.agent.chunk` (only `approval_gateway.py` and `progress_events.py` touch the bus). So the UI can only show stage cards, never generated text, during engineering work.
4. **What does stream is held back.** On the chat path, a tools-bound call holds the first **160 characters** before going live (`src/graphs/chat_graph.py:4171,4527-4531,2712`). Short answers therefore appear in one burst at the end.

The net effect is exactly what you saw: a panel that looks frozen for a minute, shows one stage at 0 %, then prints a terminal error as if it were the assistant's answer.

Two things must be said plainly:

- The **contract gate** is the reason no engineering work happened. It is one regex, and it is reproducible without a provider.
- The **frontend** is the reason the failure looked like a chat reply instead of a failed run. It also has no liveness signal during long engineering generations, and its per-frame work grows with transcript length.

The rest of this document maps every layer, answers the nine streaming questions per hop, separates the five possible causes of "event missing from the UI" for the real run, and proposes four consolidated milestones rather than another dozen phases.

---

## 2. Complete frontend file map

Root: `desktop/vscode/src/vs/workbench/contrib/crusorai/`

### 2.1 Registration, surfaces and lifecycle

| File | Size | Responsibility | Status |
|---|---:|---|---|
| `browser/crusorAI.contribution.ts` | 18.9 KB | Container (right auxiliary bar), view registration, auto-hide until Ctrl+L, Manager editor registration, 9 commands, keybinding, Crusor menubar, command-centre icon, one config key | Implemented |
| `browser/crusorAIViewPane.ts` | 7.5 KB | Agent pane shell, theme install, mount root, Preview chip with honest three-state label | Implemented |
| `browser/crusorAIManagerEditor.ts` | 2.2 KB | Full-width Manager editor tab hosting the same renderer | Implemented |
| `browser/crusorAIManagerInput.ts` | 1.9 KB | Manager editor input + serializer (restores tab across reload) | Implemented |
| `electron-browser/crusorAI.desktop.contribution.ts` | 1.9 KB | `crusorai.engineRoot`, `crusorai.pythonPath`, `crusorai.autoStart` settings | Implemented |
| `browser/crusorAIHideCopilot.ts` | 9.0 KB | Hides Copilot's first-run surfaces when Crusor is primary | Implemented (visual layer) |
| `browser/crusorAIAccount.ts` | 7.2 KB | Title-bar avatar + dropdown (settings/shortcuts/theme) | Implemented; sign-out is a documented placeholder (`:76-77`) |

### 2.2 Chat, timeline and Agentic rendering

| File | Size | Responsibility | Status |
|---|---:|---|---|
| `browser/crusorAIRenderer.ts` | 258.5 KB | All DOM: transcript, turns, thinking, tools/families, diffs, plan strip, approval dock, clarify, todos, cards, composer, inspector, Manager, mount/paint | Implemented, monolithic |
| `browser/crusorAIRendererService.ts` | 140.5 KB | Single state owner: frame routing, part timeline, tools map, approvals/clarifies, plan/verification/telemetry, card store, history hydration, watchdogs, restart, host bridge | Implemented, monolithic |
| `browser/crusorAIActivity.ts` | 9.5 KB | Dom-free activity/no-activity state machine, reveal delay, timers | Implemented + unit-testable |
| `browser/crusorAIRunSummary.ts` | 8.3 KB | Tool grouping law and summary clauses | Implemented |
| `common/crusorAIToolCatalog.ts` | 8.8 KB | Tool → presentation family | Implemented |
| `browser/crusoraiCardFormat.ts` | 12.2 KB | Diff/terminal/markdown/card formatting (pure) | Implemented |
| `browser/crusorAIIcons.ts` | 7.6 KB | Codicon mapping | Implemented |
| `browser/crusorAIReasoningBlocks.ts` | 1.9 KB | Repairs glued reasoning blocks | Implemented |
| `common/crusorAICards.ts` | 8.5 KB | Card schema v1, sanitisation, unknown fallback, per-turn store, user-facing policy | Implemented |
| `common/crusorAIProtocol.ts` | 17.8 KB | Typed wire protocol (all frames) | Implemented |
| `common/crusorAIProtocol.generated.ts` | 2.6 KB | Protocol version/names generated from `src/bridge/protocol_v2.json` | Implemented |
| `browser/media/crusorAI.css` | 177.5 KB | Every style, tokens, responsive, reduced motion | Implemented, monolithic |
| `browser/media/crusorAI-tokens.css` | 5.1 KB | Fallback token chains | Implemented |
| `browser/crusorTheme.ts` | 16.0 KB | Live workbench theme → `--crusorai-*` palette with WCAG contrast enforcement | Implemented |

### 2.3 Transport and engine

| File | Size | Responsibility | Status |
|---|---:|---|---|
| `common/crusorAIEngineService.ts` | 2.4 KB | Engine contract, state enum, engine-root resolution | Implemented |
| `electron-browser/crusorAIEngineService.ts` | 7.8 KB | Utility-process host, handshake (45 s), frame parse, crash/degraded state | Implemented |
| `node/crusorAIWorkerProcessService.ts` | 9.7 KB | Spawns `python -m src.bridge`, NDJSON line transport, engine-root up-walk, 1 MB frame cap | Implemented |
| `common/crusorAIWorkerService.ts` / `node/crusorAIWorkerMain.ts` | 1.3 + 1.2 KB | Utility-process worker wiring | Implemented |
| `browser/crusorAIUnavailableEngineService.ts` | 1.6 KB | Web-safe fallback | Implemented |

### 2.4 Host integration (workbench actions)

| File | Size | Responsibility | Status |
|---|---:|---|---|
| `browser/crusorAIWorkbenchService.ts` | 34.8 KB | Diffs (native + inline), editor context, diagnostics, symbols/defs/refs, search, SCM state, workspace edits, test discover/run, tasks, terminals, trust | Implemented |
| `common/crusorAIWorkbenchService.ts` | 6.4 KB | Host capability contract | Implemented |
| `browser/crusorAISessionController.ts` | 7.0 KB | Registers Crusor as a workbench "Agent Sessions" provider | Implemented |
| `common/crusorAISessionStore.ts` | 3.9 KB | Session facts store (64 max), change signature | Implemented |
| `common/crusorAISessionProjection.ts` | 12.7 KB | Facts → workbench session rows | Implemented |

### 2.5 Adjacent surfaces (not Agent Core, but shipped)

| File | Size | Responsibility | Status |
|---|---:|---|---|
| `browser/crusorAIPreviewService.ts` | 36.6 KB | Preview window, proxy, dev-server discovery, health, relaunch, batch→agent | Implemented |
| `browser/media/crusor-preview/*` | ~88 KB | Preview window UI + overlay | Implemented |
| `browser/crusorAIHubDialog.ts` | 36.9 KB | In-panel Marketplace / Connectors / My Skills / One-Shot dialog | Implemented |
| `browser/crusorAISkillsHub.ts` | 13.0 KB | Skills operations (list/install/update/remove/manifest) | Implemented |
| `browser/crusorAIOneShot.ts` | 4.9 KB | Stateless one-shot jobs (one aux call, result to clipboard) | Implemented |
| `browser/crusorAIConnectors.ts` | 3.6 KB | Read-only MCP/connector listing | Implemented, intentionally light |
| `browser/crusorA2UISurface.ts` | 19.8 KB | Fixed A2UI Catalog v1 surface inside tool results | Implemented |
| `browser/crusorAIInlineCompletionProvider.ts` | 6.3 KB | Ghost-text completions via bridge | Implemented |
| `browser/crusorAINextEditProvider.ts` | 6.7 KB | Next-edit suggestions with diff preview | Implemented |

Nothing in the contribution is an empty placeholder except account sign-out. The "placeholder" problem is not missing features; it is the **engineering path's event coverage**.

---

## 3. Architecture diagram

```text
┌───────────────────────────── Electron workbench (renderer) ─────────────────────────────┐
│                                                                                          │
│  crusorAI.contribution.ts ── registers ──► CrusorAIViewPane (right aux bar)              │
│         │                                   CrusorAIManagerEditor (full tab)             │
│         │                                        │                                       │
│         └── singleton ──► CrusorAIRendererService (state owner, 1 per window)             │
│                                  │        ▲                                              │
│                  mount(root) ────┘        │ frames                                    │
│                                  ▼        │                                              │
│                        crusorAIRenderer.ts (DOM painter)                                  │
│                                  ▲        │                                              │
│                    CrusorAIRenderModel    │                                              │
│                          (plain object)   │                                              │
│                                           │                                              │
│  CrusorAIEngineService.onDidReceiveFrame ─┘                                              │
│         ▲                                                                                │
│         │ NDJSON line per frame (stdout)                                                 │
│  CrusorAIWorkerProcessService ── spawn ──► python -m src.bridge  (utility process)        │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                            │ stdin: prompt/cancel/steer/…
                                            ▼
                          Python Agent Core (LangGraph + orchestrator)
                                            │ event_bus
                                            ▼
                          Bridge._forward_events → _project_event → emit(frame)
```

Three facts about this diagram matter:

1. **One service, many mounts.** The Agent pane and the Manager tab mount the same singleton, so they cannot disagree about state (`crusorAIRendererService.ts:611-620`).
2. **The renderer is pure.** It receives a `CrusorAIRenderModel` and returns DOM. It never talks to the bridge (`mountCrusorAIRenderer`, `crusorAIRenderer.ts:4769`).
3. **The only async boundary is the frame stream.** Everything else — diffs, files, terminal, tests — is a request/response through host callbacks (`crusorAIRendererService.ts:410-556`).

---

## 4. Component responsibility map

| Component | Owns | Never owns |
|---|---|---|
| `CrusorAIRendererService` | session id, turn id, running/outcome, parts, reasoning, tools, approvals, clarifies, plan, verification, telemetry, cards, history, draft, chips, mode, effort, watchdogs, engine fault | DOM, CSS, provider calls |
| `CrusorAIRenderer` (mount) | DOM tree, disclosure sets (`openTools`/`closedTools`), plan disclosure, activity timers, scroll anchoring, focus restoration, Manager tab state | engine/session state |
| `CrusorCardStore` | `(turnId, cardId)` → card, insertion order, turn snapshots | transport, rendering |
| `CrusorAIActivityState` | liveness signature, quiet timer, reveal timer, measured durations | turn state |
| `CrusorAIWorkbenchService` | diffs, editor/selection/diagnostics, search, SCM, terminals, tasks/tests, workspace edits | conversation |
| `CrusorAIEngineService` | sidecar lifecycle, handshake, frame parse | session semantics |
| `CrusorAIWorkerProcessService` | process spawn, NDJSON framing, engine-root resolution | protocol semantics |
| `CrusorAISessionStore` | session facts (label/status/read/timestamps) | transcript |
| `CrusorAIPreviewService` | preview window + proxy + health + batch handoff | agent transcript |

The single host adapter object (`crusorAIRendererService.ts:410-556`) is the seam between DOM and workbench. Every user gesture the DOM can make is one method there: `submitPrompt`, `cancel`, `steer`, `replyToSafety`, `replyToClarify`, `openDiff`, `revealFile`, `openExternal`, `restoreCheckpoint`, `retryEngine`, `selectWorkspace`, `openFolder`, `openEngineSettings`, `openManager`, `skillsHubOp`, `copyToClipboard`, `oneshotRun`, `navigateToSession`, `newSession`. That is a clean, auditable surface.

---

## 5. Frontend state management

### 5.1 Shape

The service holds ~60 mutable fields (declarations `:180-408`), of which the turn-critical ones are:

```ts
parts: CrusorAITurnPart[]              // text | tool | reasoning | card   (:296)
reasoningParts: {text, completedAt}[]  // (:298)
tools: Map<toolId, CrusorAIToolView>   // (:183, mutated :2463-2563)
approvals: Map<toolId, entry>          // tree-scoped (:315-333)
clarifies: Map<requestId, entry>       // tree-scoped (:240-283)
cardStore: CrusorCardStore             // (turnId, cardId) (:338-340)
history: HydratedTurn[]                // (:400)
plan / verification / telemetry        // (:335-337)
running / turnOutcome / currentTurnId  // (:286, :342)
```

`buildModel` (`:958-1025`) produces a **fresh plain object per paint**, with shallow copies (`parts`, `reasoningParts`, `tools`, `subAgents`, `cards`). The renderer treats it as immutable.

### 5.2 Update law

- Every frame path ends in `this.render()` (`:2845`).
- `render()` coalesces to one `requestAnimationFrame` (`:1530-1538`) — good: N tokens per frame cost one paint.
- The renderer then decides between three paths (`crusorAIRenderer.ts:5082-5165`):
  1. **Token fast path** — signature unchanged, text grew: rebuild only the live text slot (`:5094-5113`).
  2. **No-change path** — patch live tool output / install progress only (`:5115-5128`).
  3. **Full repaint** — `root.replaceChildren()` + whole tree rebuild, with scroll/focus restoration (`:5143-5160`).
- Structural changes (new tool, new card, status change) always take the full repaint. That is why a running turn repaints wholesale at every tool transition.

### 5.3 Turn ownership

- `currentTurnId` set on `turn_started` (`:2430`); the card bucket for that turn is cleared first (`:2431-2432`).
- Cards are inserted with fallback turn id (`crusorAICards.ts:141-160`) and pinned into `parts` only if new, user-facing and not a tool duplicate (`crusorAIRendererService.ts:2301-2313`).
- History hydration groups cards by `turn.turnId` and **never merges unmatched buckets into the newest turn** (`:1460-1471`, warning at `:1520-1528`).
- Session switch clears live state (`resetSessionState`, `:892`) and stashes the live surface for return (`:697-812`).

### 5.4 Correctness gaps in state

| Gap | Evidence | Effect |
|---|---|---|
| `turnOutcome` ignores `turn_done.completed` | `:2708` sets `cancelled ? 'cancelled' : 'completed'`; only a receipt's `terminal_status` can override (`:2709-2715`) | A failed graph run with no receipt paints as **completed**; the error is plain prose |
| Hydration invents success | `:1438` (`state: 'passed'` for every hydrated tool), `:1487` (`turnOutcome: 'completed'` for every hydrated turn) | A failed/cancelled turn and failed tools look successful after reload |
| Enter while running archives the live turn | `crusorAIRenderer.ts:4310` submits on Enter regardless of `running`; `crusorAIRendererService.ts:1958-1960` archives + resets | Mid-turn text is moved to history, tools cleared, a second prompt is sent; the `queue` protocol exists (`crusorAIProtocol.ts:219`) but is not used |
| History window is silent | `:1917` `.slice(-20)`, `:1455` `.slice(-20)`, hydration `limit: 120` (`:1587`) | Sessions longer than 20 turns lose in-memory scrollback until re-hydration |
| `notice` lane is dead | declared `crusorAIRenderer.ts:128-129`, rendered `:3107-3110`; service never sets it | Dead code path, no behavioural harm |

None of these is a crash. All of them are state-truth problems, which is exactly what makes an agent feel untrustworthy.

---

## 6. Complete streaming data flow (verified per hop)

| # | Layer | File : function | Receives | Transforms to | Order preserved? | Buffers? | Streams now? | Errors | Cancel |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Composer | `crusorAIRenderer.ts:4165-4398` `composer()` | keystrokes | `host.setDraft` / `submitPrompt` | n/a | no | n/a | disabled when no workspace/child | Stop button → `host.cancel` |
| 2 | Service submit | `crusorAIRendererService.ts:1736-1862` `submitPrompt()` | text + chips | `prompt` frame (or `session_create` first) | n/a | waits ≤20 s for engine ready | on next frame | engine not ready ⇒ actionable error row | — |
| 3 | Turn open | `:1958-1968` `startTurn()` | text | archives previous, resets state, sends `prompt` | n/a | no | optimistic `running=true` | — | — |
| 4 | Engine send | `electron-browser/crusorAIEngineService.ts:120-128` | frame object | one JSON line | yes (single writer) | no | yes | send rejection ⇒ `Degraded` | — |
| 5 | Sidecar stdin | `node/crusorAIWorkerProcessService.ts:205-214` | line | child stdin write | yes | no | yes | write error rejects | `{"type":"shutdown"}` then kill (`:216-230`) |
| 6 | Python turn | `src/bridge/__main__.py` `_run_turn` | prompt | graph invocation | yes | queue | yes | `turn_failed` (`:1855-1859`, `:1874-1878`) | `turn_controls.cancelled`, checked at dispatch and after response (`src/llm/gateway.py:116-117,202-203`) |
| 7 | Token source (chat) | `src/graphs/chat_graph.py:4146-4214` `_AgentTokenPump` | LangChain `on_llm_new_token` | `message.agent.chunk` (`:4525-4539`) | yes (`run_inline = True`, `:4163`) | **holds first 160 chars when tools bound** (`:4171`, `:4527-4531`) | after holdback | emission failures swallowed | pump stops on cancellation upstream |
| 8 | Token source (engineering) | `src/orchestration/model_adapter.py:1497-1503` | — | **nothing** (blocking `invoke_model`, no callbacks) | n/a | whole response | **no** | raises to orchestrator | checked before dispatch (`gateway.py:116`) |
| 9 | Progress source (engineering) | `src/orchestration/progress_events.py:230-321` | orchestrator `on_progress` view | `agent.card` (activity) + `plan.created` | yes | dedupes by signature, bounded emissions | at stage/node boundaries only | never raises (`:264-268`) | stops new stages after cancel (`:281-286`) |
| 10 | Bus → wire | `src/bridge/__main__.py:789-945` `_project_event` | event dict | protocol frame | yes | no | immediately | `runtime_degraded` on forwarder failure (`:1208-1214`) | — |
| 11 | Wire → UI | `node/...WorkerProcessService.ts:175-182` readline | line | `onDidReceiveFrame` | yes | no | immediately | oversized line dropped with note (`:180`) | — |
| 12 | UI state | `crusorAIRendererService.ts:2215-2846` `acceptFrame` | frame | fields/parts/cards | yes (arrival) | only rAF coalescing | yes | `error` frame ⇒ `this.error` (`:2832-2833`) | `cancelRequested` + Stop ack (`:2325-2328`) |
| 13 | Paint | `crusorAIRenderer.ts:5082-5165` `paint` | model | DOM | yes | rAF | yes | — | — |

### 6.1 Answers to the nine per-layer questions

**Which file, which function** — column 3 above. **What it receives / transforms** — columns 4-5. **Order** — preserved at every hop: single writer to stdin, `run_inline` callbacks, one queue consumer, readline, arrival-order parts. **Buffering** — three places only: the 160-char text holdback, per-frame rAF coalescing, and the 8-chunk scripted fixture (test-only). **Streams immediately?** — chat text after 160 chars; reasoning immediately; tool arguments immediately; engineering text never (one summary chunk after the run). **Errors** — provider/graph exceptions → `turn_failed` → error row; in-band task failure → `turn_done` with `completed:false` (currently mis-rendered). **Cancellation** — `cancel` frame → `turn_controls` → checked before dispatch and after response → `turn_done{cancelled:true}` → "Run cancelled" + landed/dropped counts (`crusorAIRendererService.ts:2680-2694`).

---

## 7. Real-time streaming diagnosis

### A. Assistant text

| Question | Answer | Evidence |
|---|---|---|
| Token-by-token? | Provider-chunk-by-chunk on the chat path; **never** on the engineering path | `chat_graph.py:4525-4539`; `model_adapter.py:1497-1503` |
| Buffered? | Yes — first **160 chars** of a tools-bound generation are withheld | `chat_graph.py:4171,4527-4531` |
| Aggregated? | Held text is released as one chunk (`release_held`, `:4546-4548`) | same |
| Waits for whole response? | Engineering: yes. Chat: no (after holdback) | as above |
| Renders during execution? | Chat: yes, one paint per rAF. Engineering: only stage cards | `service:1530-1538` |
| Debounce/throttle/batch delay? | rAF only (≤16 ms). No token debounce | `service:1530-1538` |
| Per-frame cost | Two full-model `JSON.stringify` (`renderer:4800-4803`, `5042-5080`) + full markdown re-parse of the live answer (`:5103`) | measured: ~400 KB serialised, ~0.94 ms/frame pair at 20 turns/64 sessions on this host |

**Why it feels bad even when it streams.** The live slot is rebuilt from scratch: `slot.replaceChildren(markdownCopy(streaming.text, ...))` on every frame (`:5103`). `markdownCopy` re-parses the entire accumulated text line by line and creates fresh nodes (`:423-520`). Consequences: work is O(answer length) per frame (O(n²) overall), text selection inside the answer is destroyed on every frame, and any inline element state is lost. OpenCode instead appends fragments into an existing part; Crusor re-creates the part.

### B. Thinking and activity

- **Reasoning is real** and provider-derived (`reasoning.update` → `reasoning` → `reasoningParts`, `service:2444-2460`), rendered behind a disclosure with a live shimmer and a measured duration (`renderer:2649-2692`).
- It is **not hidden chain-of-thought in the policy sense**: the text shown is whatever the provider returns as reasoning content (or inline `<think>` routed by the pump). There is no content filter or redaction on this path — `_project_event` passes reasoning through verbatim (`bridge:945`). If the product must never show raw reasoning, that is a policy change, not a rendering bug. **Unverified:** no test asserts what happens with a provider that emits no reasoning.
- **Two activity systems coexist**: the typed `activity` card (engineering progress) and the tail activity row (`crusorAIActivity.ts`). They are driven by different sources and can both narrate the same wait.
- **Engineering liveness is thin.** The progress reporter emits on stage/node boundaries (`orchestrator.py:533+`, 30 call sites). During a single 61 s node generation (observed in the live run's ledger) there is **no frame at all** until the request returns. The only signals are `llm.request`/`llm.response`, which the bridge forwards (`factory.py:786-800`) and which the card mapper turns into "Waiting on the model" (`agent_cards.py:176-181`).
- **Stall thresholds are long**: soft "no activity" at 5 min, hard local end at 7 min (12 s only for a tool-less answer) — `service:2158-2200`. A user watching a 60 s generation sees nothing move.

### C. Plan streaming

- Engineering plan events are produced by `plan_event()` from the orchestrator's real DAG (`progress_events.py:211-227`) and emitted as `plan.created` only when steps exist.
- The strip renders `done/total`, not percent (`renderer:2514-2538`); the typed plan card renders per-step status (`renderer:2848-2861`).
- Updates are deduped by `(id, status)` tuple (`progress_events.py:311-315`), so completion/failure/blocked updates appear as they happen — **when the orchestrator reaches them**.
- **On rejection there is no plan at all.** The contract gate fires before a DAG is stored, so `plan_event` returns `None`; the user sees the activity card, no plan, then an error. That is honest but unhelpful: the rejection reason is only in the assistant text.
- **After reload the strip is empty** (`hydrateTranscript` sets `plan: []`, `service:1488`); only the typed plan card survives, because cards are journaled.

### D. Tool streaming

The chat path implements the full lifecycle, and does it well:

| Stage | Frame | UI |
|---|---|---|
| Arguments stream | `tool_call_args` | card is born with `state:'running'` and grows (`service:2484-2501`); a write renders a **live green diff** (`renderer:1814-1822`) |
| Start | `tool_call_start` | durable card, arguments complete (`service:2463-2483`) |
| Progress | `tool_call_progress` | install loader with measured percent + Cancel (`renderer:2045-2087`) |
| Output | `tool_output` | tail-follow terminal text, last 64 KB (`service:2519-2528`, `renderer:4929-4944`) |
| End | `tool_call_end` | settled status/duration/body (`service:2529-2563`) |

**On the engineering path none of these exist**, because the orchestrator does not execute tools through the tool bus: it generates and applies files through `ModelExecutionAdapter` + mutation broker. There is no tool event to render, and inventing one would violate the "no fabricated events" rule. What can honestly be shown is: node started, file written (from mutation receipts), tests run, verification result. Today only the terminal receipt carries them.

### E. Failure handling matrix

| Failure | Backend signal | Frontend behaviour | Verdict |
|---|---|---|---|
| Contract extraction fails | graph returns `task_status: failed` + error text chunk | `turn_done{completed:false}` → **painted completed**, error as prose | **Broken UX** |
| Planning fails | same | same | **Broken UX** |
| Provider auth/transport error | exception → `turn_failed` | error row + `failed` outcome; engine retry hint | Correct |
| Stream disconnects mid-answer | provider raises; retry then `turn_failed` | error row; partial text preserved | Correct |
| Tool execution fails | `tool_call_end{status:'failed'}` | red tool card with error body | Correct |
| Approval denied | `turn_done{cancelled:true}` + message | "Run cancelled" + landed/dropped | Correct (wording could say *denied*) |
| User presses Stop | `turn_done{cancelled:true}` | "Run cancelled", Stop disabled while pending | Correct |
| Bridge crashes | engine state `Crashed` | engine-fault row, turn marked failed, auto-restart ×3 with backoff | Correct |
| App restart mid-turn | sidecar recovery + journal claim | resume + hydrate; healed live lane | Partial (scripted-only evidence) |

---

## 8. OpenCode comparison

Verified against the current `dev` tree (`packages/core/src/session/…`; `processor.ts` no longer exists). Details in `OPENCODE_EXECUTION_ARCHITECTURE_COMPARISON.md`.

| Area | OpenCode | Crusor | Assessment |
|---|---|---|---|
| Message representation | one row, `content: AssistantContent[]` | parts array + tools map + card store | Crusor has two projections (needed for typed UI) |
| Ordered parts | array order is the timeline | `CrusorAITurnPart[]` with card pins | Equivalent for live |
| Text streaming | ephemeral deltas addressed by `(messageID, ordinal)` | `token` frames appended to last text part | **Crusor lacks part identity**; relies on arrival order |
| Reasoning | `reasoning` part, end boundary carries full text | same shape, own disclosure | Equivalent |
| Tool lifecycle | state machine `streaming→running→completed\|error` on the part | `running/passed/failed/approval` on a map + part pin | Equivalent; Crusor adds approval state |
| Stable event identity | `evt_`→`msg_` deterministic ids | `event_id` dedup (20 k window) + `(turnId, cardId)` | Equivalent in practice |
| Event ordering | durable seq + ordinal | journal `seq` exists, but the renderer hydrates from checkpoint messages without per-event order | **Crusor is weaker on restore** |
| State updates | event → projector → row | frame → service fields → model | Equivalent |
| Session persistence | message rows + part rows | checkpoints + journal + receipts | Crusor is richer (hash-chained journal) |
| Historical restoration | ordinal rows re-joined | messages + cards, anchored placement | Crusor anchors rather than interleaves |
| Error handling | error on the assistant step | error row only for `turn_failed` | **Crusor loses in-band failures** |
| Cancellation | abort + interrupted event | cancel frame + terminal frame + landed/dropped | Equivalent |
| Frontend rendering | client parts list | parts + cards + tool families | Crusor is visually richer |

**Ideas worth adopting (Crusor-shaped, not copies):**

1. **Give parts an ordinal.** Adding `ordinal` to `token`/`reasoning`/`tool_call_*` frames would remove the "last text part" assumption and make historical interleaving exact. The protocol already has a place for new optional fields.
2. **Durable boundaries, ephemeral deltas.** Crusor already does this for tool output; doing it for text would let the renderer append instead of re-parse.
3. **Status travels with the turn.** OpenCode stores `finish`/`error` on the assistant row. Crusor should carry `completed:false` into the turn's outcome and its receipt.

**Do not copy:** OpenCode's single-projection model would lose Crusor's typed cards, approval dock and verification/delivery/FinOps projections. Those are product requirements here.

---

## 9. Backend-to-frontend event gap analysis (the real run)

| Observed symptom | Case | Evidence |
|---|---|---|
| No plan card | **A — never emitted.** Contract gate rejected before a DAG existed; `plan_event` returns `None` without steps (`progress_events.py:211-215`) | live-evidence DOM `plan: 0`; error text at `chat_graph.py:5444-5447` |
| Activity stuck at "Planning changes / 0 %" | A + B-minor: one stage emitted; `0%` is `progress_percentage` in the card's detail (`progress_events.py:177-179`), no steps to count | DOM text captured |
| No tool rows | **A — no tool bus involvement** in engineering; adapter applies files directly (`model_adapter.py:1497`) | DOM `tool: 0` |
| No file-change card | A — file cards come from tool results or terminal receipts (`agent_cards.py:285-304`, `:340-349`); neither existed | unchanged file hashes |
| No test-result / verification / cost cards | A — receipt-only, and the run never produced a delivery receipt | `chat_graph.py:5448-5454` returns no `engineering_delivery` |
| Terminal error shown as chat prose | **C — state updated, wrong semantics.** `turn_done{completed:false}` was forwarded; renderer ignores `completed` (`service:2708`) | DOM: no error row, no failed receipt |
| No streaming text | **E — by design.** Engineering text exists only as one post-run summary chunk (`chat_graph.py:5415-5416`) | ledger shows 2 blocking calls, no pump receipts |
| Engine/bridge forwarding | **Not the cause.** `_forward_events` emits every projected frame (`bridge:1199-1202`) | live log balance |

So: **Case A dominates** (the backend genuinely had nothing to say), **Case C is the real frontend defect** (the failure was mislabelled), and **Case E is an architectural choice** (engineering produces one summary, not a stream). Case B and Case D did not occur in this run.

---

## 10. Error and cancellation analysis

**Error taxonomy today** (`renderer:3088-3106`): engine fault row (crash/degraded, with Retry), engine setup row (with Open Settings), generic error row (with Retry), degraded row, context-status row, stalled row. That is a reasonable taxonomy — but it is reached only through `this.error`, which is set by `turn_failed`, `error` frames, engine state, and watchdog expiry. **In-band task failures never enter it.**

**Cancellation** is the strongest path in the frontend: pending state disables the button (`renderer:4319`), the bridge acks `cancel_requested` (`service:2325-2328`), the terminal frame carries `cancelled` and the receipt, and the UI prints landed vs dropped (`renderer:3034-3046`) using `mutation_receipts` when available (`service:2685-2694`). One gap: the agent surface has no *steer/queue* affordance — `queue` is in the protocol (`crusorAIProtocol.ts:219`) and the bridge drains queued submissions (`bridge:1918-1922`), but the composer only steers from the Manager (`renderer:4281`).

---

## 11. Test coverage report

Executed now (deterministic, no provider): **197 passed, 1 skipped, 1 xfailed, 1 failed** across
`test_desktop_renderer_architecture.py` (120), `test_agent_cards.py` (11), `test_turn_card_rendering.py` (11),
`test_turn_card_association.py` (13), `test_bridge_protocol_v2.py` (9), `test_desktop_session_pipeline.py` (20),
`test_desktop_sidecar_architecture.py` (8), `test_desktop_contrib_overlay.py` (6), `test_desktop_startup_registration.py`.

| Surface | Deterministic unit | Real Electron | Real provider |
|---|---|---|---|
| Card schema/validation | ✅ `test_agent_cards.py`, `scripts/test_crusorai_cards.mjs` | — | — |
| Turn ownership / restore | ✅ `test_turn_card_association.py` (13), `test_turn_card_rendering.py` (11) | ✅ `accept-crusorai-progress.mjs` (40 checks, mock) | ❌ |
| Renderer source contracts | ✅ `test_desktop_renderer_architecture.py` (120, **source-text assertions**) | partial (DOM assertions inside acceptance) | ❌ |
| Streaming text | ❌ no DOM test | ✅ `accept-crusorai-streaming.mjs` (scripted, **8 large chunks**, 140 ms apart) | ❌ |
| Thinking | source contract only | scripted acceptance | ❌ |
| Tools/diffs | source contracts | scripted acceptance | ❌ (chat path never exercised with a real model) |
| Plan strip/card | source contracts | mock acceptance (real orchestrator) | ❌ |
| Approval | source contracts | mock + scripted (policy `ask`) | ❌ |
| Error states | minimal | not asserted | ❌ |
| Cancellation | source contract | mock acceptance (`turn 3 cancelled`) | ❌ |
| Restart/restore | ✅ hydration tests | ✅ progress (reload + repeated hydration + full restart) | ❌ |
| Failure truthfulness | ❌ **missing** (`completed:false` case) | ❌ | ❌ |

Two coverage facts matter more than the counts:

1. **No DOM-level unit tests exist.** There is no jsdom/happy-dom harness in `desktop/vscode`; `test_desktop_renderer_architecture.py` asserts substrings in the TypeScript source. A rendering regression that keeps the source string intact cannot be caught.
2. **Every Electron acceptance uses a scripted or mock backend** (`CRUSORAI_ORCHESTRATOR_MOCK=1` in progress; `CRUSORAI_BRIDGE_RUNNER=scripted` in checkpoint/engineering/streaming). The only real-provider evidence is the failed qualification run. There is therefore **no end-to-end proof that a real model's output renders correctly**, which is precisely the gap that produced this audit.

The single failing test is real, not cosmetic: `test_agent_cards.py::test_all_required_card_types_are_declared` shows the Python allowlist declaring `thinking`, `read`, `search` (`src/bridge/agent_cards.py:17-25`) while the TypeScript schema declares only 9 types (`crusorAICards.ts:9-12`). Any such card would render as "Unsupported". None is emitted today, so it is latent.

---

## 12. Frontend quality scores

| Category | Score | Evidence and why |
|---|---:|---|
| Frontend architecture | **8/10** | DI-clean services, pure renderer, single state owner, transport isolated (`contribution:76-86`, `service:410-556`, `renderer:4769`). Docked for one 140 KB service and one 258 KB renderer doing too much. |
| Component organization | **7/10** | Logical split (activity/runSummary/toolCatalog/cardFormat/theme/cards), but the two monoliths and one 177 KB stylesheet make change risk high. |
| State management | **7/10** | Explicit fields, per-turn card store, dedupe, bounded memory. Docked for ad-hoc mutable fields, `turnOutcome` not derived from truth, hydration inventing success. |
| Real-time text streaming | **4/10** | Chat streams after a 160-char hold; engineering never streams; live slot rebuilt per frame (`renderer:5103`); no part identity. |
| Thinking/activity experience | **6/10** | Real reasoning + well-designed activity state machine; but engineering has no liveness between stages and 5-7 min stall thresholds. |
| Plan updates | **5/10** | Real DAG projection and dedupe; but a rejected plan leaves nothing, the strip does not restore, and the card is the only survivor. |
| Tool lifecycle rendering | **6/10** | Best-in-class on chat (args stream, live write diff, progress, tail output, grouping); zero on engineering by architecture. |
| Error handling | **4/10** | Good rows exist but in-band failures bypass them (`service:2708`); no taxonomy for "plan rejected", "contract ambiguous", "budget exhausted". |
| Cancellation | **7/10** | Correct end-to-end with landed/dropped receipt; no steer/queue in the agent composer; Enter-while-running misfires. |
| Session restoration | **7/10** | Per-turn cards, idempotent hydration, restart proven (scripted); failed/cancelled outcomes and tool failure states are lost. |
| Performance | **5/10** | rAF coalescing and fast paths are good; two full-model serialisations per frame plus O(n) markdown rebuild per frame; whole-tree repaint on structure change. |
| **Overall frontend maturity** | **6/10** | Strong deterministic scaffolding and security posture; the real-provider experience is unproven, and the two defects that produced your run (failure semantics, engineering liveness) are exactly the ones this architecture does not currently cover. |

These scores are deliberately conservative. A 6 is "credible engineering with a known-unproven critical path", not "production-ready".

---

## 13. Prioritized improvement roadmap

Four milestones. No phase sprawl.

### P0 — Truthful turns (blocking the product)

**P0.1 A failed turn must look failed.**
- **Root cause:** `turnOutcome` derives from `cancelled` + receipt only (`service:2708-2715`), while the bridge sends `completed:false` (`bridge:1724-1729`).
- **Files:** `crusorAIRendererService.ts:2677-2715`; `crusorAIRenderer.ts:3034-3046` (receipt row), `:3098-3106` (error row).
- **Change:** `turnOutcome = cancelled ? 'cancelled' : (frame.completed === false ? 'failed' : 'completed')`; when the failure has no receipt, render the existing failed row and keep the error text as its detail — not as a bare assistant paragraph.
- **UX:** the user sees a red "Run failed" receipt with the reason, instead of a confident answer that is an error string.
- **Risk:** low; the receipt override still wins. Historical turns are unaffected.
- **Tests:** new deterministic test feeding `turn_done{completed:false}`; Electron assertion that the failed row exists and the error text is not styled as the answer.
- **Dependencies:** none.

**P0.2 Restore outcome truth.**
- **Root cause:** hydration hardcodes `state:'passed'` (`:1438`) and `turnOutcome:'completed'` (`:1487`).
- **Files:** `crusorAIRendererService.ts:1397-1501`; bridge `session_messages` payload (`bridge:1986-1999`) must carry per-turn outcome and per-tool status (it already has the journal).
- **Change:** extend the hydrated message envelope with `turn_outcome` and `tool_status` (additive, optional; no schema version bump needed), consume them when present, fall back to today's behaviour otherwise.
- **UX:** reloading a session no longer turns your failed run green.
- **Risk:** medium (payload growth); backwards compatible.
- **Tests:** hydration fixture with one failed turn and one failed tool; restart assertion.
- **Dependencies:** P0.1.

**P0.3 Fix the contract gate (Agent Core prerequisite, not frontend).**
- **Root cause:** symbol regex requires `def|function` before the name (`contract.py:311-315`); line `:522` then rejects the plan.
- **Change:** accept name-first phrasing and parameter lists; add a regression test for "implement a divide(a, b) function".
- This is outside the frontend but it is the reason the frontend had nothing to show. No UI work matters until it lands.

### P1 — Make engineering feel alive

**P1.1 Emit a heartbeat during model generation.**
- **Root cause:** engineering calls are blocking and publish nothing (`model_adapter.py:1497-1503`); progress is stage-boundary only.
- **Files:** `src/orchestration/model_adapter.py`, `src/orchestration/progress_events.py`.
- **Change:** emit the existing `agent.card` activity with `percent`/elapsed from a wrapper around `invoke_model` (start, first-byte, done). Do not fabricate tool events; this is a *generation* stage, named as such.
- **UX:** the stage card stops reading "0 %" for a minute; the panel shows the node actually working.
- **Risk:** low (card is idempotent by `(turn, card)` and deduped).
- **Tests:** reporter test that start/finish produce two distinct signatures; mock acceptance sees ≥2 activity updates inside one node.
- **Dependencies:** none.

**P1.2 Stream engineering *narrative*, not raw file tokens.**
- **Root cause:** one summary chunk after the run (`chat_graph.py:5415-5416`).
- **Change (design decision to confirm):** stream a short per-node "what I am doing" line as `message.agent.chunk` at node start (e.g. "Writing src/mini_math/ops.py"), and keep the final report as the post-run summary. Do **not** stream generated file bodies into chat — that is what the file cards are for.
- **UX:** the turn reads as a sequence instead of a black box.
- **Risk:** medium (chat prose volume); bound to one line per node, deduped.
- **Tests:** node-start emission count equals node count; no duplicate lines on retry.
- **Dependencies:** P1.1.

**P1.3 Remove or reduce the 160-char text holdback.**
- **Root cause:** `hold_text=tools_bound` (`chat_graph.py:2712`) holds the first 160 chars (`:4171`).
- **Why it is now safe to reduce:** the frontend already supports withdrawal — `token_retract` removes painted chars and the pump already tracks what it painted (`chat_graph.py:4534-4539`, `service:2440-2442`, `:1994-2009`).
- **Change:** lower the hold to ~40 chars or to one line, and rely on `token_retract` for discarded attempts.
- **UX:** first visible token ~4× sooner on tools-bound answers.
- **Risk:** discarded attempts may flash briefly; mitigated by retraction.
- **Tests:** scripted provider that emits then discards; assert no residue.
- **Dependencies:** none.

**P1.4 Make the per-frame path incremental.**
- **Root cause:** `paintSignature` and `stableSignature` stringify the whole model (`renderer:4800-4803`, `5042-5080`), and the fast path rebuilds markdown (`:5103`).
- **Change:** compute a cheap structural signature (lengths + ids + statuses) instead of `JSON.stringify(model)`; on the token fast path append to a single text node, and re-parse markdown on a trailing edge (e.g. 100 ms) rather than every frame.
- **UX:** steady streaming on long answers, selectable text mid-stream, lower CPU.
- **Risk:** medium; the no-change and full paths must still agree.
- **Tests:** node-level timing harness on a synthetic 20-turn model; Electron streaming test asserting token count > 50 and no full repaint during text-only growth.
- **Dependencies:** none.

### P2 — Product quality

**P2.1 Enter while running must queue, not archive.** Use the existing `queue` frame (`crusorAIProtocol.ts:219`, bridge drain `:1918-1922`); guard `startTurn` when `running` (`service:1958`).
**P2.2 Session actions.** The protocol supports rename/pin/archive/fork/delete (`crusorAIProtocol.ts:209-213`); the UI exposes none. Either add row actions in the Manager (`renderer:4561-4605`) or stop advertising them.
**P2.3 Schema drift.** Reconcile `src/bridge/agent_cards.py:17-25` with `crusorAICards.ts:9-12` (drop `thinking/read/search` or add them to the TS schema). This also clears the one failing test.
**P2.4 Model/provider visibility.** No in-app model selection exists; only `.env` + `crusorai.engineRoot/pythonPath/autoStart` settings (`contribution:428-441`). Show the active provider/model in the engine status chip at minimum; a selector is a later feature.
**P2.5 Restore the plan strip after reload** (`service:1488` sets `plan: []`), from the journaled plan card or a persisted plan snapshot.
**P2.6 Remove the dead `notice` lane** (`renderer:128-129,3107-3110`) or wire it.

### P3 — Future

**P3.1 Event-exact history.** Add an `ordinal` to text/reasoning/tool frames and persist it in checkpoint parts; historical turns then interleave exactly, as OpenCode does.
**P3.2 Activity de-duplication.** One narrator: either the typed activity card or the tail row, not both, during engineering.
**P3.3 DOM test harness.** Without jsdom/happy-dom, every renderer change is guarded by string matching.

---

## 14. Files and functions that need attention first

| Priority | File : function / line | Why |
|---|---|---|
| 1 | `src/orchestration/contract.py:311-315,522` | blocks every task whose prompt uses natural word order |
| 2 | `desktop/.../browser/crusorAIRendererService.ts:2677-2715` (`turn_done`) | failure painted as success |
| 3 | `desktop/.../browser/crusorAIRendererService.ts:1397-1501` (`hydrateTranscript`) | invents `passed`/`completed` on restore |
| 4 | `src/orchestration/model_adapter.py:1497-1503` | blocking call, no liveness |
| 5 | `src/orchestration/progress_events.py:230-321` | only stage-boundary emissions |
| 6 | `desktop/.../browser/crusorAIRenderer.ts:4800-4803,5042-5080` | two full-model serialisations per frame |
| 7 | `desktop/.../browser/crusorAIRenderer.ts:5094-5113` (+`markdownCopy:423-520`) | full text rebuild per frame |
| 8 | `src/graphs/chat_graph.py:4171,2712,4527-4531` | 160-char holdback |
| 9 | `desktop/.../browser/crusorAIRendererService.ts:1958-1968` | archive-on-submit while running |
| 10 | `src/bridge/agent_cards.py:17-25` vs `common/crusorAICards.ts:9-12` | card-type drift |

---

## 15. Open questions / unverified areas

1. **Real-provider chunk granularity.** We have never observed a real token stream end-to-end: the chat path was not exercised with the live provider in the qualification run, and the scripted fixture emits 8 large chunks. Whether velona/GLM delivers 1-token or multi-token deltas (and how the 160-char holdback feels with it) is **unverified**.
2. **`llm.request` visibility during engineering.** The proxy emits it per attempt (`factory.py:786-800`), but the live run produced no completed engineering turn, so whether the activity card updates to "Waiting on the model" during a node is **unproven**.
3. **Light theme (B-DESK-002).** The stylesheet is token-driven (5 hardcoded dark values; one `prefers-color-scheme` block at `crusorAI.css:2749`), and `crusorTheme.ts` derives from the live theme with contrast enforcement — yet the open defect says the pane can render dark under a light theme. **Not re-verified** in this read-only audit.
4. **Manager surface parity.** `renderManager` is a separate composition (`renderer:4739-4768`); the acceptance scripts exercise the Agent pane. Manager-specific rendering is **source-verified only**.
5. **Preview/hub/A2UI behaviour** was classified from code and headers, not exercised.
6. **Restart during an in-flight engineering turn.** The checkpoint acceptance uses the scripted runner; crash-recovery of a real 60 s generation has **no evidence**.
7. **`events_replay` vs checkpoint hydration.** Resume uses journal replay (`service:1574-1575`), a fresh window uses `session_messages` (`:1586-1587`); the two restore paths are not proven equivalent for cards.
8. **Long-session performance.** The per-frame cost was measured on a synthetic 20-turn model (~0.94 ms/frame pair); no measurement exists on a real 20-turn session in the app.

---

## Closing assessment

The frontend is better built than its current reputation. It has a real state owner, a real event protocol, a safe card schema, honest activity semantics, and a working per-turn conversation model. What it lacks is **truthful failure status** and **liveness while an engineering turn is thinking**, and the engineering path's own architecture (blocking generation, stage-boundary progress) gives it very little to render.

Fix the contract gate and the failed-turn semantics first. Then give the engineering path a heartbeat and a per-node narrative. After that, the streaming refinements in P1.3/P1.4 will be felt on a product that is already telling the truth.

No product file was modified in producing this audit.
