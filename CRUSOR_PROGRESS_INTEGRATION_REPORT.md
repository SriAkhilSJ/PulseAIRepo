# Crusor Progress Integration Report

**Task:** wire live engineering progress into the existing Agentic UI.
**Status:** implemented, tested, and demonstrated in the real Electron workbench with a deterministic, provider-free engineering run.

| Field | Value |
|---|---|
| Branch | `feat/prompt-cache-stabilization` |
| Starting HEAD | `fb5bd528b40933346c4004a1490154683dc0d40e` |
| Final HEAD | `fb5bd528b40933346c4004a1490154683dc0d40e` (no commit made) |
| Dirty entries before / after | 186 / 192 (4 new files by this task: module, test, acceptance script, this report; evidence under gitignored `bench-results/`) |
| Paid provider calls | 0 |
| Frontend components added | 0 |
| Card schema changes | 0 |
| Protocol frame types added | 0 |

---

## 1. Root cause and source references

`EngineeringExecutionOrchestrator` already computed a safe progress snapshot for every lifecycle stage, but nothing listened.

- `src/orchestration/orchestrator.py:516-532` — `emit_progress(step_name)` builds a `DesktopVisibilityReporter` view and calls `on_progress(view.to_safe_dict())` **only if `on_progress` is set**.
- `src/orchestration/orchestrator.py:536,542,572,580,586,609,652,664,717,735,744,782,806,887,910,961,982,1056,1105,1176,1248,1309,1330,1463` — 25 stage emissions plus one per DAG node (`TASK_NODE_<id>`).
- `src/graphs/chat_graph.py:5394-5397` (before this change) — `run_task_request(request, cancellation_checker=_cancelled)`: **no `on_progress`**.
- `src/bridge/__main__.py:651-674` — the live event projection table has no engineering-progress source, so there was nothing to project.
- `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRendererService.ts:2333-2334` — `plan_updated` is the only live plan surface; it never received an engineering event.
- `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRenderer.ts:2800-2803` — the activity card already paints `label`, `status` and `detail`; it stayed on "Understanding request" for the whole engineering run.

Consequence: during an engineering turn the UI received `turn_started`, approval requests, the final summary chunk and the terminal receipt. Plan, stage and step progress were absent while the task ran.

**Documentation discrepancy:** `PHASE_12_1_DESKTOP_PROGRESS_INTEGRATION.md:21-31` claims a live `turn_lifecycle` + `plan_updated` mapping. The live path never had it: `turn_lifecycle` exists only in the durable-replay projection (`src/bridge/__main__.py:828-833,861-869`) and the protocol type (`common/crusorAIProtocol.ts:157`); `crusorAIRendererService.acceptFrame()` has no `turn_lifecycle` branch. The snapshot was being computed and discarded, exactly as `CRUSOR_FRONTEND_UNDERSTANDING.md` §5 concluded.

---

## 2. Implementation changes

### 2.1 `src/orchestration/progress_events.py` (new, 260 lines)

A projection module that maps each genuine `DesktopTaskProgressView` snapshot onto **existing** event names and **existing** card types.

- `activity_card()` (`:177`) → existing `activity` card, stable id `<turn>:activity`, data `{stage, label, status, detail}`. The renderer already renders this card (`crusorAIRenderer.ts:2800-2803`, headline from `data.label` in `common/crusorAICards.ts:119`).
- `plan_event()` (`:197`) → existing `plan.created` event with the real DAG steps (`completed_steps`, `failed_steps`, `pending_steps`) and their real statuses. The bridge maps this to `plan_updated` (`src/bridge/__main__.py:666`), which drives both the plan strip and the plan card.
- `EngineeringProgressReporter` (`:216`) is the `on_progress` callback:
  - **exception-safe** — every failure is logged, counted and swallowed (`:239-246`); the orchestrator's inline call can never abort a run;
  - **cancellation-aware** — checks the turn's cancel predicate before every emission (`:266-269`);
  - **deduplicated** — identical consecutive snapshots emit nothing (`:279-293`, `:300-304`);
  - **bounded** — hard cap `MAX_PROGRESS_EMISSIONS = 240` per turn with a `dropped` counter (`:40`, `:271-274`);
  - **redacted** — every card/step payload passes through `redact_secrets_from_dict` and is length-bounded (`:177-213`).

Only two stage-derived surfaces are emitted. No tool, file-change, test-results, verification or cost card is ever derived from a stage label:

- Tool/file/test/verification/cost stay with their authoritative sources (real tool results, real verification, real FinOps ledger) and the terminal delivery receipt.
- `modified_files` and `test_results_summary` from the snapshot are deliberately **not** turned into file/test cards; `resource_consumption` is **not** turned into a cost card (the snapshot carries a total, not per-invocation model/cost certainty).

### 2.2 `src/graphs/chat_graph.py`

- `:5274` imports `EngineeringProgressReporter`.
- `:5352-5361` constructs the reporter with the turn's exact identity (`session_id=thread_id`, `turn_id=turn_id`, `cancelled=_cancelled`) after the pre-delegation cancellation check.
- `:5405-5409` passes it: `run_task_request(request, on_progress=progress, cancellation_checker=_cancelled)`.

### 2.3 `src/bridge/__main__.py`

The event bus already had an `agent.card → agent_card` mapping, but nothing persisted a producer-built card, so it would have been live-only.

- `:615-628` new `_journal_agent_card(card, identity)` keeps the durable row logic in one place.
- `:630-639` `_emit_companion_cards` now journals an incoming `agent_card` frame and returns (the card was already projected by its producer), and still projects/ journals companion cards for every other frame.

Result: progress cards are live **and** survive reload/replay through `session_messages` (`src/bridge/__main__.py:1839-1863`), with no new protocol frame and no renderer change.

---

## 3. Event flow before and after

### Before

```text
engineering_task_node
  → run_task_request(cancellation_checker=…)
      → emit_progress(STAGE)
          → on_progress is None → snapshot discarded
  → DeliveryContract
  → one message.agent.chunk summary
  → turn_done receipt
UI: activity card frozen on "Understanding request"; no plan until the receipt.
```

### After

```text
engineering_task_node
  → EngineeringProgressReporter(session_id=thread_id, turn_id=turn_id)
  → run_task_request(on_progress=reporter, cancellation_checker=…)
      → emit_progress(STAGE)
          → DesktopVisibilityReporter.compute_view(...).to_safe_dict()
          → reporter(snapshot)
              ├─ event_bus "agent.card"    → activity card  <turn>:activity (status/detail updated in place)
              └─ event_bus "plan.created"  → DAG steps      <turn>:plan
  → BridgeServer._forward_events (queue, identity, session filter)
      ├─ _project_event: agent.card   → agent_card frame (normalize_card)
      └─ _project_event: plan.created → plan_updated frame
  → _emit_companion_cards
      ├─ journals the agent_card frame's card (replay)
      └─ projects plan_updated → plan card, journals it
  → Electron onDidReceiveFrame → renderer acceptFrame
      ├─ agent_card → cards.set(cardId) in place → render()
      ├─ plan_updated → this.plan → plan strip (top) + plan card
      └─ turn_done → delivery / file_change / verification / cost cards (unchanged, authoritative)
```

Ordering, identity and duplicates:

- Emissions are synchronous from the orchestrator thread; the event bus queue preserves arrival order.
- Every payload carries `session_id` + `thread_id` + `turn_id`; the bridge stamps frames with the same turn identity.
- Card ids are stable (`<turn>:activity`, `<turn>:plan`), so the renderer replaces in place (`crusorAIRendererService.ts:2179-2188`); no duplicate cards appear on update or replay.
- The only terminal cards are the existing receipt projections (`src/bridge/agent_cards.py:256-398`).

---

## 4. Tests executed and results

All commands ran from `C:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo` with `.venv\Scripts\python.exe`, Python 3.14.4, Windows.

### 4.1 New deterministic suite — `src/tests/test_engineering_progress_events.py`

```text
python -m pytest src/tests/test_engineering_progress_events.py -q
19 passed in 12.37s
```

Covers, without any provider call:

| Requirement | Test |
|---|---|
| Node passes the callback | `test_engineering_node_passes_a_progress_callback` |
| Progress reaches the event bus | `test_progress_reaches_the_event_bus_with_stage_identity` |
| Bridge projects to existing frames/cards | `test_bridge_projects_progress_onto_existing_cards` |
| Frontend schema declares the card types | `test_frontend_schema_declares_the_projected_card_types` (parses `CRUSOR_CARD_TYPES`) |
| Renderer paints the projected fields | `test_renderer_paints_the_projected_fields` |
| Journal/replay row per painted card | `test_bridge_persists_activity_cards_for_replay`, `test_bridge_still_projects_and_persists_companion_plan_cards` |
| Ordering + turn identity + stable ids | `test_multiple_updates_keep_order_identity_and_stable_card_ids` |
| Duplicate snapshots suppressed | `test_repeated_snapshot_is_emitted_once` |
| Bounded emission | `test_emission_is_bounded` |
| Cancellation (before + mid-run) | `test_cancelled_turn_stops_emission`, `test_cancellation_mid_run_keeps_prior_events` |
| Callback failure containment | `test_emitter_failure_never_escapes_the_callback` |
| Failure never flips the verdict | `test_callback_failure_does_not_change_the_delivery_verdict`, `test_callback_failure_does_not_turn_a_failed_run_into_success` |
| No fabricated authoritative cards | `test_progress_never_fabricates_authoritative_cards` |
| No secret leakage | `test_stage_text_is_redacted_and_bounded` |
| Live graph run, progress before the summary | `test_mock_engineering_run_streams_progress_before_the_summary` |

The last test runs the real `stream_agent` engineering path in orchestrator mock mode and asserts that progress events appear **before** the node's final `message.agent.chunk` summary, that at least two distinct stage labels occur, and that the last activity card is `Delivered` / `completed`.

### 4.2 Regression suites

```text
python -m pytest src/tests/test_canonical_runtime_engineering_delegation.py \
  src/tests/test_canonical_runtime_increment2.py src/tests/test_agent_cards.py \
  src/tests/test_bridge_protocol_v2.py src/tests/test_bridge_orchestrator_protocol.py -q
52 passed, 1 failed
```

The single failure is pre-existing and unrelated: `test_agent_cards.py::test_all_required_card_types_are_declared` expects exactly nine types, while the **uncommitted working-tree** `src/bridge/agent_cards.py` already added `thinking`, `read`, `search` (`git diff` shows those three lines; HEAD has only the nine). Not modified by this change.

```text
python -m pytest src/tests/test_desktop_renderer_architecture.py \
  src/tests/test_invocation_reconciliation.py src/tests/test_phase_11_6_autonomous_execution.py -q
175 passed, 1 skipped, 1 xfailed
```

```text
python -m pytest src/tests/test_bridge.py src/tests/test_bridge_transport.py \
  src/tests/test_bridge_workspace_routing.py -q
64 passed, 2 failed
```

Both failures are pre-existing on this working tree and independent of this change:

- `test_sidecar_hello_then_real_runtime_shape` expects the echo lane's first six frames to be exactly `turn_started, runtime_degraded, token, turn_done`; the already-present `turn_started`/`turn_done` companion `agent_card` frames (unchanged by this diff) push `turn_done` past its six-frame window.
- `test_autotitler_fires_once_after_a_full_exchange` asserts a single-line `_maybe_autotitle_session(...)` signature; the working tree already uses a multi-line signature.

Final combined confirmation:

```text
python -m pytest src/tests/test_engineering_progress_events.py \
  src/tests/test_canonical_runtime_engineering_delegation.py \
  src/tests/test_bridge_protocol_v2.py -q
35 passed in 20.10s
```

### 4.3 Frontend compile and card contract

```text
cd desktop/vscode && npm run typecheck-client
EXIT=0   (tsc --project ./src/tsconfig.json --noEmit --skipLibCheck)

node scripts/test_crusorai_cards.mjs
crusorai card contract ok
```

No TypeScript file changed, so the existing Electron build remains valid.

### 4.4 Real Electron acceptance (deterministic, provider-free)

```text
cd desktop/vscode && node scripts/accept-crusorai-progress.mjs
verdict: PASS   (13/13 checks)
```

The app ran the **real** Python bridge and the **real** orchestration engine with `CRUSORAI_ORCHESTRATOR_MOCK=1`; the FinOps ledger recorded `rows=0` provider invocations.

Observed live activity-card titles, sampled by an in-page `MutationObserver` **while the Stop button was visible**:

```text
Understanding request → Understanding the request → Validating architecture →
Extracting contracts → Assigning files → Analyzing impact → Implementing changes →
Validating artifacts → Checking regressions → Delivered
```

The plan card appeared mid-run (`planSeenRunning: true`), the activity card settled on `Delivered`, the receipt cards (delivery/file/verification/cost) rendered, `notes.md` was created, and after a full workbench reload both the activity card and the plan card were restored from the journal.

Evidence (gitignored, produced this session):

- `bench-results/phase-3.3-canonical-runtime/logs/electron-progress/acceptance.json`
- `bench-results/phase-3.3-canonical-runtime/logs/electron-progress/progress-result.json`
- screenshots `01-agent-ready.png` … `05-after-reload.png`
- `electron.log`

### 4.5 Durable journal evidence

Querying the acceptance app-data runtime journal (`runtime_events.db`) for the single turn:

```text
turn.started : 1
agent_card   : 31
  activity   : 23   (card id <turn>:activity — updated in place)
  plan       :  4   (card id <turn>:plan — updated in place)
  delivery   :  1
  file_change:  1
  verification: 1
  cost       :  1
turn.completed: 1
```

This is the proof that progress is live *and* durable: 27 in-place progress rows share two stable card ids, and the four authoritative receipt cards remain separate, exactly as before.

---

## 5. Remaining limitations

1. **Plan step text uses DAG node ids** (`task_notes`, `task_verification`). The progress view (`src/orchestration/visibility.py:26-61`) exposes node ids, not node descriptions, and this change deliberately does not reach into the orchestrator's plan to invent labels. The terminal receipt's plan card is unchanged and still carries whatever the receipt supplies.
2. **The orchestrator never marks DAG nodes complete.** `AdaptiveContextManager.record_task_completion` (`src/orchestration/context_manager.py:140-147`) has no caller in `src/`, so `completed_steps` stays empty and the plan card shows every node as `pending` except the one currently named by a `TASK_NODE_<id>` stage (`in_progress`). This integration reports the engine's data verbatim; it does not synthesize completions, because a started node is not a verified one. Populating completion is a separate orchestrator fix.
3. **No live engineering cost card.** The snapshot's `resource_consumption` is a running total (`tokens`, `cost_inr`), not per-invocation model/provider/certainty data, so projecting it onto the `cost` card would misstate certainty. The receipt cost card remains authoritative.
4. **No live engineering test/verification/file cards.** The orchestrator does not execute tests through tool calls and the snapshot carries no per-test results; those cards stay receipt-driven. This is intentional, per the "do not fabricate authoritative events" rule.
5. **Card placement is unchanged.** Typed cards still render after the transcript timeline (`crusorAIRenderer.ts:2755-2756`). That is the pre-existing design analysed in `CRUSOR_FRONTEND_UNDERSTANDING.md` §7 and was out of scope here.
6. **No real-provider run.** Only deterministic mock-mode execution was exercised; no paid provider calls were authorised or made.
7. **Repo memory docs not updated.** `docs/CURRENT_STATE.md`, `docs/phases/PHASE_TRACKER.md`, etc. were left untouched to respect the task's "no unrelated changes" scope; this report is the deliverable.
8. **Pre-existing failures preserved.** `test_agent_cards.py` (working-tree card-type additions) and two `test_bridge.py` assertions fail on this tree for reasons documented in §4.2. They were not "fixed" or weakened.

---

## 6. Completion evidence

The completion criterion was: *a deterministic engineering execution must demonstrate real orchestrator progress travelling through the existing event pipeline and reaching the existing Agentic UI while execution is still running.*

Evidence chain, all from this session:

1. `test_engineering_node_passes_a_progress_callback` — the node passes a live callback.
2. `test_progress_reaches_the_event_bus_with_stage_identity` — the callback reaches the real bus with session/turn identity.
3. `test_bridge_projects_progress_onto_existing_cards` + `test_frontend_schema_declares_the_projected_card_types` — the bridge emits `agent_card`/`plan_updated` and the frontend schema already declares those card types.
4. `test_mock_engineering_run_streams_progress_before_the_summary` — in a real graph run, every progress event precedes the final summary chunk.
5. `accept-crusorai-progress.mjs` **PASS** — the real Electron workbench painted 10 distinct stage labels while the turn was running, showed the plan card mid-run, settled on `Delivered`, and restored both cards after reload, with zero provider invocations.

No frontend component, card schema, protocol frame or renderer path was added or replaced.
