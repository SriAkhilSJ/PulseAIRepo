# Crusor Plan Outcome Semantics Report

**Task:** make the existing plan card represent real engineering outcomes truthfully — completed, failed, blocked and cancelled — without a second plan component.

| Field | Value |
|---|---|
| Branch | `feat/prompt-cache-stabilization` |
| Starting HEAD | `fb5bd528b40933346c4004a1490154683dc0d40e` |
| Final HEAD | `fb5bd528b40933346c4004a1490154683dc0d40e` (no commit) |
| New plan components / schemas | 0 |
| Paid provider calls in the final acceptance | 0 (`rows=0`) |
| Card schema version | unchanged (v1) |

---

## 1. Previous behaviour

The plan contract had four states:

```ts
'pending' | 'in_progress' | 'completed' | 'failed'
```

and the backend collapsed everything that was not pending/completed into `failed`:

- `scheduler.execute_plan` wrote `SKIPPED` for a failed prerequisite, but in practice a failed wave **halts** the pipeline before later waves run, so unreached nodes stayed `PENDING`.
- The orchestrator's halt back-fill (`orchestrator.py:864-880` in the previous change) marked unreached nodes `SKIPPED` and the projector rendered them as `failed`.
- Cancellation marked the interrupted node `FAILED` (generic exception path); nodes never reached were left `PENDING`.

So "blocked" and "cancelled" were indistinguishable from a genuine failure or from work still waiting.

---

## 2. Truthful states and where they come from

| State | Provenance (real execution path) |
|---|---|
| `pending` | Node not settled (scheduler `PENDING`), inside a live turn. |
| `in_progress` | Scheduler set `IN_PROGRESS` and called the executor; the progress snapshot's `current_step` names the node. |
| `completed` | Executor returned `True` (the adapter validated every target before mutating). `record_task_completion`, idempotent. |
| `failed` | Executor returned `False` or raised a non-cancellation error. `record_task_failure`. |
| `blocked` | (a) a dependency failed/was cancelled (`scheduler` sets `BLOCKED`), or (b) the pipeline halted and the node was never reached (orchestrator back-fill sets `BLOCKED`). `record_task_blocked`. Never a completion. |
| `cancelled` | The turn's cancellation predicate was true before a node started, the executor raised while the turn was cancelled (including Stop during an approval wait), or the turn cancelled and the node was never reached (orchestrator back-fill). `record_task_cancelled`. |

Intentional skip: the scheduler has **no** independent "intentional skip" outcome. Its only `SKIPPED` case was "prerequisite task failed"; that is now `BLOCKED`. `record_task_outcome` still maps legacy `SKIPPED` to `blocked` so no persisted state is lost.

No state is inferred from a lifecycle label, from `DELIVERED`, or from the terminal receipt.

---

## 3. Contract changes

### 3.1 Backend execution state

`src/orchestration/context_manager.py`

- `AuthoritativeTaskContext` gains `blocked_steps` and `cancelled_steps` (persisted in `authoritative_context.json`; old files load `[]`).
- `record_task_completion` is idempotent and clears any failure/blocked/cancelled entry (a successful retry is genuinely completed).
- `record_task_failure` is attempted-and-failed only; it never downgrades a completed node.
- New `record_task_blocked` / `record_task_cancelled`.
- `record_task_outcome` maps `COMPLETED → completed`, `FAILED → failed`, `SKIPPED|BLOCKED → blocked`, `CANCELLED → cancelled`, `PENDING|IN_PROGRESS → no-op`.

`src/orchestration/scheduler.py`

- `execute_plan(..., is_cancelled=...)` receives the turn's real cancellation predicate.
- A node stopped before it starts is `CANCELLED` (executor not called).
- A dependency failure/cancellation blocks dependents (`BLOCKED`) instead of mislabelling them failed.
- An exception while the turn is cancelled → `CANCELLED` (including `ApprovalDenied` raised by a Stop that abandoned the approval wait); a genuine `ApprovalDenied` without cancellation is still re-raised as the security verdict.
- The wave halts on failed **or** cancelled work and returns false.

`src/orchestration/orchestrator.py`

- `emit_progress` excludes completed, failed, blocked and cancelled nodes from pending and passes all four outcome buckets to the visibility reporter.
- Cancellation branch: records the interrupted/unrun nodes as `CANCELLED`, journals `TASKS_CANCELLED`, emits one final snapshot.
- Approval-cancel (`PermissionError` + cancelled): records unrun nodes `CANCELLED`, journals, emits the final snapshot, then re-raises the verdict.
- Failure halt: records unreached nodes `BLOCKED`, journals `TASKS_BLOCKED`, and emits the final snapshot.
- `_node_progress` journals `TASK_NODE_COMPLETED/FAILED/SKIPPED/BLOCKED/CANCELLED`.
- The final cancelled snapshot is marked `final` so the progress reporter forwards **only** that settled snapshot after Stop (new stage progress is still suppressed).

`src/orchestration/visibility.py`

- `DesktopTaskProgressView` carries `blocked_steps` and `cancelled_steps`; `to_safe_dict()` includes them.
- `compute_view(..., blocked_steps=None, cancelled_steps=None)` is additive (existing calls unchanged); totals/percentages include the new buckets.

`src/orchestration/progress_events.py`

- `_steps` emits `completed / failed / blocked / cancelled / in_progress / pending` in that settled-first order.
- `_detail` reports `N failed`, `N blocked`, `N cancelled` alongside the step count.
- The cancellation gate lets the one `final` snapshot through; other post-Stop stage snapshots remain suppressed.

### 3.2 Frontend (existing card only)

`desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRenderer.ts`

- `CrusorAIPlanStepView.status`: `'pending' | 'in_progress' | 'completed' | 'failed' | 'blocked' | 'cancelled'`.
- Plan strip glyphs: `debug-pause` for blocked, `stop-circle` for cancelled (existing pass-filled / circle-slash / spinner / ring retained).
- Plan card glyphs via `planStepMark`: `✓ ▸ ✕ ⊘ – ○`.

`desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRendererService.ts`

- `PLAN_STATUSES` includes `blocked` and `cancelled`, so `planStepView` preserves them instead of falling back to `pending`.

`desktop/vscode/src/vs/workbench/contrib/crusorai/browser/media/crusorAI.css`

- `.crusorai-agent-card-step.is-blocked/.is-cancelled` and `.crusorai-plan-strip-list li.is-blocked/.is-cancelled` use the theme's warning/disabled colors.

No new card type, schema version, renderer or component. `common/crusorAICards.ts` and `src/bridge/agent_cards.py` already pass plan steps through generically; the envelope stays v1.

### 3.3 Related correctness fix found by the multi-turn acceptance

`src/graphs/chat_graph.py` passed a **single shared** `app_data_root(workspace)/orchestration` storage dir to every engineering turn. Because `TaskStateMachine`, `AdaptiveContextManager` and the journal use that dir directly, the second engineering turn loaded the first turn's terminal state and failed with:

```text
Invalid state transition for task turn_t2: cannot move from COMPLETED to UNDERSTANDING.
```

(the user-visible "Engineering execution failed: Invalid state transition…" notification). The storage is now per turn:

```python
storage_dir=str(app_data_root(workspace) / "orchestration" / task_id)
```

This also stops one turn's completed steps leaking into the next turn's plan.

---

## 4. Updated flow

```text
scheduler node
  ├─ cancelled before start ──► CANCELLED
  ├─ dependency failed ───────► BLOCKED
  ├─ executor True ───────────► COMPLETED
  ├─ executor False / raise ──► FAILED  (or CANCELLED while the turn is cancelled)
  └─ Stop abandons approval ──► CANCELLED (verdict re-raised)

orchestrator back-fill
  ├─ failure halt: PENDING/IN_PROGRESS → BLOCKED
  └─ cancellation: PENDING/IN_PROGRESS → CANCELLED, final snapshot

progress snapshot → reporter → plan.created
  → bridge plan_updated → plan card + plan strip
  → Electron renderer: ✓ / ▸ / ✕ / ⊘ / – / ○, classes is-completed/is-failed/is-blocked/is-cancelled
  → journal agent_card → reload restores the same statuses
```

---

## 5. Tests and results

All commands ran from the repository root with `.venv\Scripts\python.exe` (Python 3.14.4, Windows).

### 5.1 New focused suite — `src/tests/test_plan_outcome_semantics.py` (16 tests)

```text
python -m pytest src/tests/test_plan_outcome_semantics.py -q
16 passed
```

| Requirement | Test |
|---|---|
| Successful execution | `test_successful_execution_is_completed` |
| Genuine failure | `test_genuine_failure_is_failed`, `test_exception_without_cancellation_is_failed` |
| Dependency-blocked | `test_halted_pipeline_blocks_unrun_work` (real orchestrator; failed + blocked, zero completed) |
| Cancellation during execution | `test_cancellation_during_execution_is_cancelled` |
| Cancellation before execution | `test_cancellation_before_execution_is_cancelled_without_running` |
| Cancellation between nodes | `test_cancellation_between_planned_nodes_cancels_remaining` |
| Cancellation during an approval wait | `test_cancellation_while_awaiting_approval_is_cancelled` (real orchestrator + `ApprovalDenied`) |
| Intentional skip | `test_skipped_is_not_conflated_with_failure` (scheduler has none; `SKIPPED` → blocked) |
| Retry after failure | `test_retry_moves_failed_blocked_and_cancelled_to_completed`, `test_retry_does_not_duplicate_completion` |
| Journal + replay | `test_all_outcome_states_survive_the_journal_projection`, `test_outcome_buckets_survive_context_reload` |
| Backward compatibility | `test_legacy_four_status_plan_cards_stay_valid`, `test_frontend_contract_lists_all_six_states_and_marks`, `test_missing_outcome_keys_in_an_old_snapshot_do_not_break_projection` |

### 5.2 Regression

```text
python -m pytest src/tests/test_plan_outcome_semantics.py \
  src/tests/test_plan_completion.py src/tests/test_engineering_progress_events.py \
  src/tests/test_canonical_runtime_engineering_delegation.py \
  src/tests/test_canonical_runtime_increment2.py \
  src/tests/test_phase_12_1_end_to_end_acceptance.py -q
80 passed in 24.15s

python -m pytest src/tests/test_desktop_renderer_architecture.py \
  src/tests/test_invocation_reconciliation.py src/tests/test_phase_11_6_autonomous_execution.py \
  src/tests/test_agent_cards.py src/tests/test_bridge_protocol_v2.py -q
194 passed, 1 skipped, 1 xfailed, 1 failed
```

The one failure is pre-existing and unrelated: `test_agent_cards.py::test_all_required_card_types_are_declared` expects exactly nine Python card types, while the uncommitted working tree already added `thinking`, `read`, `search`.

```text
python -m pytest src/tests/test_bridge.py src/tests/test_bridge_transport.py \
  src/tests/test_bridge_workspace_routing.py -q
64 passed, 2 failed   (same two pre-existing test_bridge.py failures documented before)
```

Frontend:

```text
cd desktop/vscode && npm run typecheck-client
EXIT=0

node scripts/emit-crusorai-bundle.mjs
[emit] wrote 43 file(s)   (panel JS + media + SOURCES_HASH)

node scripts/test_crusorai_cards.mjs
crusorai card contract ok
```

### 5.3 Real Electron acceptance (provider-free)

`desktop/vscode/scripts/accept-crusorai-progress.mjs` now runs three turns against the **real** orchestrator, scheduler, approval gateway, bridge, cards, renderer and journal, with `CRUSORAI_ORCHESTRATOR_MOCK=1` and approval policy `ask`:

```text
verdict: PASS   (21/21 checks)
no paid provider invocation: rows=0
```

| Turn | How the outcome is produced | UI evidence |
|---|---|---|
| 1. completed | Prompt creates `notes.md`; real approval dock → approve | Plan card `2/2`, both steps `is-completed`; activity live; delivery card |
| 2. failed + blocked | Prompt targets `notes.md/greeting.py` (nested under an existing file); approve the mutation; the filesystem error fails the node | Last plan card: `{completed: 0, failed: 1, blocked: 1}`; no completion claimed |
| 3. cancelled | Prompt creates `notes2.md`; Stop is clicked while the approval wait is pending | Last plan card: `{completed: 0, failed: 0, cancelled: 2}` |
| Reload | Workbench reload, Agent pane reopened | All four states present: `{completed: 2, failed: 1, blocked: 1, cancelled: 2}` |

Screenshots (gitignored evidence):

- `bench-results/phase-3.3-canonical-runtime/logs/electron-progress/04-complete.png` — plan strip `Plan 2/2`, both steps checked.
- `.../05-failed-blocked.png` — `task_greeting` failed glyph, `task_verification` blocked glyph, "Run failed".
- `.../06-cancelled.png` — both steps cancelled glyphs, "Run cancelled".
- `.../05-after-reload.png` — restored conversation.
- `acceptance.json` / `progress-result.json` — full check payloads.

The journal rows for each turn carry the same statuses (`agent_card` → plan card), which is why the states survive reload.

---

## 6. Notes on the earlier multi-turn failure and provider safety

- The "Invalid state transition" notification the owner saw was the shared orchestration storage bug in §3.3, exposed when a second engineering turn ran in the same workspace. Fixed; the two-turn regression (`test_canonical_runtime_engineering_delegation` + the acceptance) now reports the real failure ("Implementation task node execution failed: …") instead of a state-machine error.
- The final acceptance uses the mock adapter: the FinOps ledger is empty (`rows=0`), so no provider call of any kind occurred.
- An intermediate scripted-seam experiment produced one **local** FinOps attribution row (₹0.000555) from the scripted model's usage metadata. The scripted seam is network-free; it was not used for the final acceptance or the focused tests.

---

## 7. Remaining limitations

1. **Blocked vs. skipped collapse intentionally.** The scheduler has no intentional-skip outcome; `blocked` is the single truthful state for "did not run because of a dependency/upstream halt". Persisted `SKIPPED` values map to `blocked`.
2. **Overall task verdict is separate.** A node can be `completed` (its work unit executed and validated) while the final delivery is `FAILED`/`NOT_VERIFIED` because later global gates failed. The plan and the delivery/verification cards state those facts separately; completion is not back-filled from the verdict, and the verdict is not masked.
3. **Plan cards from several turns can share the post-reload stack.** `session_messages` returns the latest card per `card_id`, so multiple turns' plan cards may render together after reload (existing renderer behaviour). The acceptance scopes the current turn to the last card and counts all cards for replay.
4. **The plan strip summary counts completed/total only**; blocked/cancelled counts are shown in the activity detail line and in the step states, not in the strip header.
5. **No change to card placement** (cards still render after the transcript timeline; pre-existing design).
6. **Pre-existing failures** remain exactly as before: `test_agent_cards` (working-tree card-type additions) and two `test_bridge.py` assertions.

---

## 8. Completion statement

A deterministic, provider-free execution through the real orchestrator now drives the existing plan card through:

- `pending → in_progress → completed` for genuinely successful work;
- `failed` for attempted-and-failed work;
- `blocked` for dependency/upstream halted work;
- `cancelled` for Stop-interrupted and Stop-prevented work.

The same statuses travel orchestrator → progress reporter → bridge `plan_updated` → existing plan card/strip → Electron, and survive a full workbench reload through the journal. No new plan component, schema, renderer or dependency was introduced.
