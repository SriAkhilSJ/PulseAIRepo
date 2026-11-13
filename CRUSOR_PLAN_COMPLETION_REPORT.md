# Crusor Plan Completion Report

**Task:** make engineering plan completion reflect actual DAG task execution.
**Status:** implemented, tested against the real orchestrator, and demonstrated in the real Electron workbench (provider-free).

| Field | Value |
|---|---|
| Branch | `feat/prompt-cache-stabilization` |
| Starting HEAD | `fb5bd528b40933346c4004a1490154683dc0d40e` |
| Final HEAD | `fb5bd528b40933346c4004a1490154683dc0d40e` (no commit) |
| Dirty entries before / after | 192 / 196 (this task added `src/tests/test_plan_completion.py` and this report; all pre-existing work preserved) |
| Frontend components added | 0 |
| Card schema / protocol changes | 0 |
| New dependencies | 0 |
| Paid provider calls | 0 |

---

## 1. Previous completion behaviour

`AdaptiveContextManager.record_task_completion()` existed but had **no caller** (`rg record_task_completion src/orchestration` returned only its definition). Consequently:

- `completed_steps` was always `[]`.
- `record_task_completion` was the only writer of `completed_steps`; nothing else touched it.
- `outstanding_failures` was also never appended by the execution path.
- `EngineeringExecutionOrchestrator.emit_progress()` computed:
  - `completed_steps = context.completed_steps` → always empty;
  - `pending_steps = [plan nodes not in completed_steps]` → every node, forever;
  - `failed_steps = context.outstanding_failures` → always empty.
- The progress reporter therefore painted a plan where every step stayed `pending` (except the one currently named by `TASK_NODE_<id>`, which the projection marked `in_progress`), and `progress_percentage` was permanently 0.

The scheduler already knew the truth (`node.status = COMPLETED / FAILED / SKIPPED`), but that truth never reached the context or the plan projection.

---

## 2. Actual task completion lifecycle (established from the code)

`src/orchestration/scheduler.py:69-133` (`DependencyAwareScheduler.execute_plan`):

1. Computes safe waves from the DAG (`schedule_waves`, file-conflict serialized).
2. For each node:
   - if a dependency already failed, sets `node.status = "SKIPPED"` and calls `on_progress(node)`;
   - sets `node.status = "IN_PROGRESS"`, `started_at`, calls `on_progress(node)`;
   - calls `executor_func(node)`;
   - `True` → `node.status = "COMPLETED"`, `finished_at`;
   - `False` → `node.status = "FAILED"`, `error_message`;
   - exception → `FAILED`, `error_message` (and `PermissionError` re-raises for the approval-denied path);
   - calls `on_progress(node)` again with the settled status.
3. After a wave with failures, **halts the pipeline** (`break`), so later-wave nodes remain `PENDING`.
4. Returns `len(failed_nodes) == 0`.

`src/orchestration/model_adapter.py:801+` (`execute_node`) is the production executor: it checks cancellation, FinOps budget and RBAC, generates and validates **every** target before mutating any, applies mutations through the broker, and returns `True` only when the node's work was applied. `task_verification` is a bookkeeping node that returns `True` immediately (pre-existing behaviour).

`src/orchestration/orchestrator.py` called the scheduler with `on_progress=lambda n: emit_progress(f"TASK_NODE_{n.node_id}")`, i.e. it published the stage but **discarded the node's settled status**.

Cancellation: `chat_graph.engineering_task_node` passes `cancellation_checker`; the adapter raises `TurnCancelledError` (a `RuntimeError`, so the scheduler records `FAILED`), `execute_plan` returns `False`, and the orchestrator returns a `CANCELLED` delivery before any completion back-fill.

---

## 3. Implementation changes

### 3.1 `src/orchestration/context_manager.py`

- `record_task_completion()` (`:140`) is now explicitly idempotent and also clears a stale failure entry. It is still the only completion writer.
- New `record_task_failure(node_id)` (`:156`):
  - removes the node from `pending_steps`;
  - **never downgrades** a node already in `completed_steps` (guards late/duplicate callbacks);
  - appends to `outstanding_failures` once.
- New `record_task_outcome(node)` (`:173`) — the single decision point:
  - `COMPLETED` → completion;
  - `FAILED` / `SKIPPED` → failure;
  - `PENDING` / `IN_PROGRESS` → no mutation (a start is not an outcome);
  - returns the recorded status for tests/diagnostics.

### 3.2 `src/orchestration/orchestrator.py`

- New `_record_scheduler_progress(context_mgr, emit_progress, node)` (`:463`): records the node's settled outcome, then emits the `TASK_NODE_<id>` snapshot. This is the production callback the tests call directly, so the test seam is the same code path.
- The scheduler now receives a named `_node_progress` (`:823`) that:
  - calls `_record_scheduler_progress`;
  - journals `TASK_NODE_COMPLETED` / `TASK_NODE_FAILED` / `TASK_NODE_SKIPPED` with the node id and a bounded reason (`:826-832`).
- `emit_progress` (`:539-547`) now computes `pending_steps` as nodes not completed **and not failed**, so a failed node is not counted twice and `progress_percentage` is honest.
- Failure halt (`:859-876`): when `execute_plan` returns `False` and the turn was not cancelled, nodes the scheduler never reached (`PENDING`) are marked `SKIPPED` with `"Pipeline halted before this task ran"`, recorded as not-completed, journaled as `TASKS_BLOCKED`, and a final progress snapshot is emitted. This is a real outcome ("this work will not run"), not a fabricated completion.

No frontend, card-schema, bridge or protocol change was required. `progress_events.py` already maps the real `completed_steps` / `pending_steps` / `failed_steps` onto the plan card, and `CrusorAIPlanStepView` already supports `pending | in_progress | completed | failed`.

---

## 4. Updated plan event flow

```text
scheduler.execute_plan
  ├─ node IN_PROGRESS ──► _node_progress(node)
  │                        ├─ record_task_outcome → no mutation
  │                        └─ emit_progress("TASK_NODE_<id>")
  └─ node settled ──────► _node_progress(node)
                           ├─ record_task_outcome:
                           │    COMPLETED → completed_steps += id (deduped)
                           │    FAILED/SKIPPED → outstanding_failures += id
                           ├─ journal TASK_NODE_<STATUS>
                           └─ emit_progress → DesktopVisibilityReporter.compute_view

EngineeringProgressReporter(snapshot)
  ├─ agent.card    → activity card <turn>:activity
  └─ plan.created  → steps with real statuses  <turn>:plan>

Bridge._project_event → plan_updated → plan card + plan strip
Renderer → existing plan card (✓ / ▸ / ○ / ✕) and plan strip
```

Observed live sequence (real orchestrator, deterministic executor):

```text
(task_notes, pending)      (task_verification, pending)
(task_notes, in_progress)  (task_verification, pending)
(task_notes, completed)    (task_verification, pending)
(task_notes, completed)    (task_verification, in_progress)
(task_notes, completed)    (task_verification, completed)
```

Failure sequence (real orchestrator, executor returns False):

```text
(task_notes, pending)      (task_verification, pending)
(task_notes, in_progress)  (task_verification, pending)
(task_notes, failed)       (task_verification, pending)
(task_notes, failed)       (task_verification, failed)   ← blocked by the halt back-fill
```

---

## 5. Tests and results

All commands ran from the repository root with `.venv\Scripts\python.exe` (Python 3.14.4, Windows).

### 5.1 New focused suite — `src/tests/test_plan_completion.py` (11 tests)

```text
python -m pytest src/tests/test_plan_completion.py -q
11 passed in 5.71s
```

| # | Requirement | Test |
|---|---|---|
| 1 | Successful task completion | `test_successful_node_is_recorded_completed` (real scheduler; asserts `pending → completed`, activity-style snapshots, projected `completed`) |
| 2 | Failed task not completed | `test_failed_node_is_never_completed` |
| 3 | Cancelled task not completed | `test_cancelled_node_is_never_completed` (`TurnCancelledError` from the executor, as the adapter raises) |
| 4 | Blocked/skipped not completed | `test_blocked_dependent_is_never_completed` (dependent never runs; scheduler leaves it `PENDING`, no completion) |
| 5 | Retry without duplicate completion | `test_retry_does_not_duplicate_completion`, `test_retry_success_moves_a_failed_node_to_completed` |
| 6 | Multiple nodes complete in order | `test_multiple_nodes_complete_in_execution_order` (A→B→C) |
| 7 | Plan updates reach the reporter | `test_real_orchestrator_publishes_plan_completion_and_activity` (full `run_task`, reporter, all nodes) |
| 8 | Activity updates continue | Same test: activity cards are emitted throughout; also `test_halted_pipeline_marks_unrun_nodes_blocked` |
| 9 | Plan state survives journal replay | `test_completed_plan_survives_the_journal_projection` (bridge `plan_updated` → plan card → journal row keeps `completed`) |
| 10 | Normal chat unchanged | `test_normal_chat_turn_has_no_engineering_node_completion` (scripted chat; no `task_node_*` stages, no engineering delivery) |

Additional test: `test_halted_pipeline_marks_unrun_nodes_blocked` — a failing executor through the real orchestrator leaves no step `completed` and no step `pending`; every node ends `failed` (contract representation of failure/blocked).

The "real orchestrator" tests use `mock_mode=True` for the model adapter (its pytest default) but a **custom deterministic executor**, so node outcomes are explicit inputs, not outputs of a mock label. No provider call is made.

### 5.2 Regression

```text
python -m pytest src/tests/test_plan_completion.py \
  src/tests/test_engineering_progress_events.py \
  src/tests/test_phase_11_6_autonomous_execution.py \
  src/tests/test_bridge_orchestrator_protocol.py -q
78 passed in 15.56s

python -m pytest src/tests/test_phase_12_1_end_to_end_acceptance.py -q
5 passed in 6.56s          # full real-orchestrator acceptance matrix

python -m pytest src/tests/test_desktop_renderer_architecture.py \
  src/tests/test_invocation_reconciliation.py -q
131 passed, 1 skipped, 1 xfailed in 19.99s

python -m pytest src/tests/test_canonical_runtime_engineering_delegation.py \
  src/tests/test_bridge_protocol_v2.py src/tests/test_agent_cards.py -q
26 passed, 1 failed   (pre-existing, see below)

python -m pytest src/tests/test_bridge.py src/tests/test_bridge_transport.py \
  src/tests/test_bridge_workspace_routing.py -q
64 passed, 2 failed   (pre-existing, see below)
```

Known pre-existing failures on this working tree (unchanged by this task):

- `test_agent_cards.py::test_all_required_card_types_are_declared` — the uncommitted working tree already added `thinking`, `read`, `search` to the Python `CARD_TYPES`; the test still expects exactly nine.
- `test_bridge.py::test_sidecar_hello_then_real_runtime_shape` — the echo lane's already-present `turn_started` / `turn_done` companion `agent_card` frames push `turn_done` past the test's six-frame window.
- `test_bridge.py::test_autotitler_fires_once_after_a_full_exchange` — asserts a single-line `_maybe_autotitle_session(...)` signature; the working tree uses a multi-line one.

### 5.3 Frontend compile and card contract

```text
cd desktop/vscode && npm run typecheck-client
EXIT=0   (tsc --project ./src/tsconfig.json --noEmit --skipLibCheck)

node scripts/test_crusorai_cards.mjs
crusorai card contract ok
```

No TypeScript changed; the existing Electron build is current.

### 5.4 Real Electron acceptance (deterministic, provider-free)

```text
cd desktop/vscode && node scripts/accept-crusorai-progress.mjs
verdict: PASS   (16/16 checks)
```

Checks specific to this task:

| Check | Result |
|---|---|
| `plan steps show an executing state` | **pass** (`activeWhileRunning: true`) |
| `plan steps complete while the turn is still running` | **pass** (`completedWhileRunning: true`, `maxCompletedSteps: 2`) |
| `final plan records real completion` | **pass** (`{total: 2, completed: 2, failed: 0}`) |
| `plan card restored after reload` | **pass** (restored card text still shows `✓ task_notes`, `✓ task_verification`, `2/2 steps`) |
| `no paid provider invocation` | **pass** (`rows=0`) |

Screenshots: `bench-results/phase-3.3-canonical-runtime/logs/electron-progress/01-agent-ready.png` … `05-after-reload.png`. The completed screenshot shows the plan strip at `Plan 2/2` with both steps checked.

---

## 6. Evidence from actual orchestrator execution

### 6.1 Successful run (real orchestrator, deterministic executor)

Journal at `<workspace>/.crusorai/tenants/evidence/tasks/task_evidence/orchestration_journal.jsonl`:

```text
TASK_NODE_COMPLETED {'node_id': 'task_notes', 'reason': ''}
TASK_NODE_COMPLETED {'node_id': 'task_verification', 'reason': ''}
```

Live plan projection:

```text
(task_notes, pending)      (task_verification, pending)
(task_notes, in_progress)  (task_verification, pending)
(task_notes, completed)    (task_verification, pending)
(task_notes, completed)    (task_verification, in_progress)
(task_notes, completed)    (task_verification, completed)
```

### 6.2 Failed run (real orchestrator, executor returns False)

```text
TASK_NODE_FAILED {'node_id': 'task_notes', 'reason': 'Task execution returned False'}
TASKS_BLOCKED    {'node_ids': ['task_verification'], 'reason': 'pipeline_halted_after_failure'}
```

Projection: `task_notes` → `failed`, `task_verification` → `failed` (blocked), **no step completed**.

### 6.3 In-process mock engineering turn (`CRUSORAI_ORCHESTRATOR_MOCK=1`, through `stream_agent`)

```text
PLAN (task_notes, pending)      (task_verification, pending)
PLAN (task_notes, in_progress)  (task_verification, pending)
PLAN (task_notes, completed)    (task_verification, pending)
PLAN (task_notes, completed)    (task_verification, in_progress)
PLAN (task_notes, completed)    (task_verification, completed)
```

This is the exact stream consumed by the desktop acceptance; the UI screenshot shows `Plan 2/2` with both steps checked.

---

## 7. Remaining limitations

1. **The plan contract has no `blocked`/`skipped` status.** `CrusorAIPlanStepView` (`crusorAIRenderer.ts:35-38`) supports `pending | in_progress | completed | failed`. Blocked work is therefore represented as `failed` (✕), the closest existing state to "did not complete". Proposed smallest compatible change, **not implemented** because it would touch the card/TS contract: add `'blocked'` to the union and `PLAN_STATUSES`, a distinct glyph, and a `blocked_steps` field in `DesktopTaskProgressView`. Until then, failure and blocking share one visual state.
2. **Node completion reflects the work unit, not the final task verdict.** `execute_node` returns `True` only after its own generation/validation/mutation succeeded, so a completed step is truthful at that granularity. Global artifact validation, test execution and independent verification run later and have their own cards; a task can end `FAILED`/`NOT_VERIFIED` with honestly completed construction steps. The agentic UI shows both facts separately.
3. **Cancellation while a node is executing** is reported as `failed` (the scheduler maps the raised `TurnCancelledError` to `FAILED`). Cancellation before the pipeline reaches a node leaves it `pending`; the halt back-fill only runs for non-cancelled failures. No cancelled work is ever marked completed.
4. **`task_verification` is a bookkeeping DAG node** whose adapter returns `True` immediately (`model_adapter.py:822-823`); its completion means the node's executor accepted it, not that independent verification passed. Verification is a separate stage/card.
5. **No changes to card placement or rendering order** (still cards-after-timeline; pre-existing design, out of scope).
6. **Mock model mode** was used for the model adapter; node outcomes came from explicit deterministic executors. No paid provider call was made.

---

## 8. Acceptance statement

A deterministic execution through the actual `EngineeringExecutionOrchestrator` now produces:

- `pending → in_progress → completed` for each genuinely successful DAG node;
- `failed` for a node whose executor rejected or raised;
- `failed` (blocked representation) for work abandoned by a halted pipeline;
- no completion for cancelled, failed, skipped or unrun work;
- no duplicate completion entries on retry;
- the same updates streamed through the existing `agent.card` / `plan.created` → bridge → plan card/strip pipeline;
- durable `TASK_NODE_COMPLETED` rows and a plan card that survives reload.

The Crusor Agentic UI renders the updated plan with its existing components; no new schema or component was introduced.
