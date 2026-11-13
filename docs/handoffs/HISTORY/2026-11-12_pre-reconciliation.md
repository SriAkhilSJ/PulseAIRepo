# CrusorAI - Latest Handoff

**Handoff date:** 2026-11-11 (backend qualification appended 2026-11-12, §8)
**Branch:** `feat/prompt-cache-stabilization`
**HEAD:** `fb5bd528b40933346c4004a1490154683dc0d40e`
**Origin:** `origin/main` is 3 commits ahead (release follow-ups); nothing pushed
**Current phase:** Agentic execution visibility: live engineering progress,
truthful plan outcomes (completed / failed / blocked / cancelled), per-turn card
ownership, and a clean chronological timeline with internal-only
verification/delivery/cost cards hidden; **backend qualification (2026-11-12)
proved the provider path and disproved engineering capability — no tools are
bound**; production readiness not claimed

> The prior handoff (Agent Runtime Increments 1–3) is archived at
> `docs/handoffs/HISTORY/2026-11-10_agent-runtime-increments.md`.
> This handoff records uncommitted working-tree work; HEAD is unchanged.

---

## 1. Where the project stands

- Production hardening phases 0–1.4 remain **WINDOWS SECURITY QUALIFIED**.
- Phase 2 r1/r2 remain `DESKTOP_PARTIAL` (light-theme and headed-GUI gaps).
- Phase 3.1/3.2 remain PASS (bounded); Agent Runtime Increments 1–3 remain
  implemented in the working tree.
- **New (2026-11-11): engineering execution is visible and truthful.**
  - Orchestrator stage snapshots reach the existing `agent.card` activity card
    and `plan.created` plan card through the event bus, bridge projection and
    renderer. Bounded (240/turn), deduplicated, cancellation-aware, redacted.
  - DAG completion is recorded only from the scheduler's real settled outcome;
    no completion is inferred from stages or from `DELIVERED`.
  - The plan card now distinguishes `completed`, `failed`, `blocked` and
    `cancelled` in addition to `pending` / `in_progress`.
  - Every engineering turn uses its own orchestration storage; the previous
    second-turn `COMPLETED → UNDERSTANDING` invalid transition is gone.
- **New (2026-11-11, later): per-turn card ownership.** Cards are stored in a
  `CrusorCardStore` keyed by `(turnId, cardId)`, historical messages are stamped
  with the turn whose prompt produced them, and each history turn renders only
  its own cards. Session switches clear the store; replay cannot duplicate;
  reload and a full application restart restore all three acceptance turns.
- **New (2026-11-11, latest): clean chronological timeline.** Verification,
  delivery and cost cards are internal-only (model/journal/receipts/FinOps keep
  them) and paint nothing. Visible cards are pinned into `CrusorAITurnPart` at
  arrival; late receipt cards go before the final answer; historical turns place
  the plan early and the rest before the final answer. Typed tool cards are
  suppressed when the matching tool row exists. **Electron 40/40 PASS,
  `rows=0`.** Report: `CRUSOR_AGENTIC_TIMELINE_REPORT.md`.
- Provider-free Electron acceptance (three real-orchestrator turns):
  completed 2/2, failed+blocked, cancelled, and all four states restored after
  reload. **32/32 checks PASS, `rows=0` provider invocations.**
- Nothing from this work has been committed or pushed.

## 2. What changed (uncommitted)

Backend:
- `src/orchestration/progress_events.py` (new; earlier task)
- `src/orchestration/context_manager.py` — blocked/cancelled buckets,
  `record_task_blocked`, `record_task_cancelled`, truthful `record_task_outcome`
- `src/orchestration/scheduler.py` — `is_cancelled`, pre-start cancellation,
  dependency blocking, approval-Stop cancellation
- `src/orchestration/orchestrator.py` — pending/outcome projection, cancellation
  and halt back-fill, `final` settled snapshot, node outcome journaling
- `src/orchestration/visibility.py` — `blocked_steps` / `cancelled_steps`
- `src/orchestration/models.py` — status comment includes `BLOCKED`/`CANCELLED`
- `src/graphs/chat_graph.py` — per-turn orchestration storage

Frontend (existing components only):
- `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRenderer.ts`
  — six-state plan union, strip glyphs, card marks; history `cards`/`turnId`,
  `data-turn-id`
- `.../crusorAIRendererService.ts` — `PLAN_STATUSES`; `CrusorCardStore`,
  `currentTurnId`, per-turn hydration/snapshot/reset
- `.../common/crusorAICards.ts` — `CrusorCardStore`; user-facing card policy
  (`CRUSOR_INTERNAL_CARD_TYPES`, `isUserFacingCard`, `userFacingCards`)
- `.../common/crusorAIProtocol.ts` — `CrusorSessionMessage.turn_id`
- `.../media/crusorAI.css` — blocked/cancelled colors
- `desktop/vscode/out/vs/workbench/contrib/crusorai/**` — regenerated panel
  (`node scripts/emit-crusorai-bundle.mjs`, 43 files, `SOURCES_HASH` current)

Tests / evidence:
- `src/tests/test_plan_outcome_semantics.py` (16)
- `src/tests/test_plan_completion.py` (11)
- `src/tests/test_engineering_progress_events.py` (19)
- `src/tests/test_turn_card_association.py` (new, 13)
- `src/tests/test_turn_card_rendering.py` (new, 7)
- `desktop/vscode/scripts/accept-crusorai-progress.mjs` (three turns, two
  reloads, full application restart)
- reports: `CRUSOR_FRONTEND_UNDERSTANDING.md`,
  `CRUSOR_PROGRESS_INTEGRATION_REPORT.md`, `CRUSOR_PLAN_COMPLETION_REPORT.md`,
  `CRUSOR_PLAN_OUTCOME_SEMANTICS_REPORT.md`,
  `CRUSOR_TURN_CARD_RESTORATION_REPORT.md`,
  `CRUSOR_AGENTIC_TIMELINE_REPORT.md`
- Electron evidence:
  `bench-results/phase-3.3-canonical-runtime/logs/electron-progress/`
  (`acceptance.json`, `progress-result.json`, screenshots 01–07)

## 3. Verification (provider-free)

Run from repo root with `.venv\Scripts\python.exe`:

```powershell
# outcome semantics (16)
python -m pytest src/tests/test_plan_outcome_semantics.py -q

# plan completion + progress + delegation + increment2 + phase 12.1 (80)
python -m pytest src/tests/test_plan_outcome_semantics.py `
  src/tests/test_plan_completion.py `
  src/tests/test_engineering_progress_events.py `
  src/tests/test_canonical_runtime_engineering_delegation.py `
  src/tests/test_canonical_runtime_increment2.py `
  src/tests/test_phase_12_1_end_to_end_acceptance.py -q

# renderer / invocation / phase 11.6 / cards / protocol
python -m pytest src/tests/test_desktop_renderer_architecture.py `
  src/tests/test_invocation_reconciliation.py `
  src/tests/test_phase_11_6_autonomous_execution.py `
  src/tests/test_agent_cards.py src/tests/test_bridge_protocol_v2.py -q

# bridge sidecar / transport / routing
python -m pytest src/tests/test_bridge.py src/tests/test_bridge_transport.py `
  src/tests/test_bridge_workspace_routing.py -q

cd desktop/vscode
npm run typecheck-client
node scripts/emit-crusorai-bundle.mjs
node scripts/test_crusorai_cards.mjs
node scripts/accept-crusorai-progress.mjs
```

Recorded results (2026-11-11):
- outcome semantics: **16 passed**
- turn-card association / rendering: **20 passed** (13 + 7)
- focused + orchestrator: **79 passed**
- renderer/protocol/cards/turn-card: **161 passed, 1 skipped, 1 xfailed,
  1 pre-existing failure**
- bridge: **73 passed, 2 pre-existing failures**
- workflow/verification/FinOps: **28 passed, 1 pre-existing failure**
- `typecheck-client`: **exit 0**
- panel emitter: **43 files**; card contract: **ok**
- Electron acceptance: **PASS 40/40, `rows=0`** (three turns, reload, repeated
  hydration, full application restart; no verification/delivery/cost cards)

Pre-existing failures (not touched):
- `test_agent_cards.py::test_all_required_card_types_are_declared` — the
  working tree already adds `thinking`, `read`, `search` to Python `CARD_TYPES`
  while the test expects exactly nine.
- `test_bridge.py::test_sidecar_hello_then_real_runtime_shape` — existing
  `turn_started`/`turn_done` companion cards push `turn_done` past the test's
  six-frame window.
- `test_bridge.py::test_autotitler_fires_once_after_a_full_exchange` — asserts a
  single-line `_maybe_autotitle_session(...)` signature; the working tree uses
  a multi-line signature.

## 4. Runtime contracts

- `engineering_task_node` constructs `EngineeringProgressReporter(session_id,
  turn_id, cancelled)` and passes `on_progress` to `run_task_request`.
- Progress events: `agent.card` (activity, `<turn>:activity`) and
  `plan.created` (plan, `<turn>:plan`). No fabricated tool/file/test/
  verification/cost events.
- `record_task_outcome` is the only plan settlement point:
  `COMPLETED → completed`, `FAILED → failed`, `SKIPPED|BLOCKED → blocked`,
  `CANCELLED → cancelled`, `PENDING|IN_PROGRESS → no-op`.
- The cancelled path marks its last snapshot `final`; the reporter forwards that
  one after Stop and suppresses further stage snapshots.
- Plan statuses: `pending | in_progress | completed | failed | blocked |
  cancelled`; card schema stays v1.
- Orchestration storage is per turn:
  `app_data_root(workspace)/orchestration/<task_id>`.
- Card identity is `(sessionId, turnId, cardId)`:
  `CrusorCardStore` is per surface/session, `cardsFor(turnId)` feeds only that
  history turn, and `resetSessionState` clears all buckets. Historical messages
  are stamped from the journal's `turn.started.request.sha256`; `session_messages`
  dedupes cards by `(session, turn, card id)` and pages the journal.

## 5. Working tree / preservation

- Status at handoff: **211 entries**, zero deletions; all pre-existing user work
  preserved (apps, diagnostics, benches, generated modules, broker wiring,
  compiled artifacts).
- `docs/` is tracked; these 2026-11-11 updates are uncommitted.
- A recovery snapshot from 2026-11-10 is preserved at
  `C:\Users\Administrator\AppData\Local\Temp\opencode\crusor-snapshot-20261110`.
- Do not clean/reset/revert/stash. No commit or push was authorized.

## 6. Open risks and next actions

1. **Real-provider verification** of progress, plan outcomes and card restoration
   requires an explicit paid-call authorization; mock-mode evidence is complete.
2. **Plan step labels** are DAG node ids; a bounded description field in the
   visibility view would improve readability.
3. **Legacy card ambiguity.** Sessions whose journal lacks `turn.started` request
   hashes and whose counts do not align leave cards unassigned (warned, never
   merged); do not claim universal legacy association.
4. **Full-suite baseline** on HEAD + working tree remains open (B-006).
5. **Working-tree disposition** (commit vs retain) remains a decision.
6. Do not claim production readiness from this work.

## 7. Landmines

- Never mark a plan node completed from a stage label, from `DELIVERED`, or from
  a terminal receipt. Completion comes only from the scheduler's settled
  `COMPLETED`.
- `blocked` and `cancelled` are not `failed`; keep the distinction. The
  scheduler has no independent intentional-skip outcome (`SKIPPED → blocked`).
- Node completion is a work-unit fact, not the final task verdict. A task can
  end `FAILED`/`NOT_VERIFIED` with honestly completed construction steps.
- Keep orchestration storage per turn. A shared directory reintroduces the
  `COMPLETED → UNDERSTANDING` invalid transition and stale completed steps.
- Never key renderer cards by `cardId` alone. Use `CrusorCardStore` /
  `(turnId, cardId)`; a global map reintroduces the shared-stack bug.
- History cards come only from `cardsFor(turn.turnId)`; do not merge unmatched
  buckets into the newest turn.
- `verification`, `delivery` and `cost` are internal-only: filter through
  `isUserFacingCard`/`userFacingCards` at paint time. Do not delete their
  records or backend projection; do not add a dedicated card for them.
- Timeline order comes from `CrusorAITurnPart` card pins; late cards belong
  before the final assistant text, and the final answer must stay last.
  Suppress a typed tool card when the existing tool row already renders it.
- Historical interleaving is anchored (plan early, other cards before the final
  answer); do not claim event-exact history without a durable sequence.
- Do not remove the `final` marker: it is the one settled snapshot allowed
  through after Stop.
- Any TypeScript change to the panel requires
  `node scripts/emit-crusorai-bundle.mjs` (updates `out/` and `SOURCES_HASH`)
  before Electron acceptance.

---

## 8. Backend qualification — 2026-11-12 (terminal, real provider)

**Scope.** The programme was switched to backend-only, so this run used no
Electron: `stream_agent(..., canonical_runtime=True)` drives the same
graph → orchestrator → adapter → gateway path the bridge uses.

**What passed.** Provider authentication and dispatch; real usage extraction;
5 settled FinOps rows (15,929 in / 5,828 out, ₹0.1815; ₹0.4207 total including
one stopped UI attempt, cap ₹50); measured `latency_ms`; `turn_id` `turn-A/B/C`;
honest receipts. The null `latency_ms` defect is fixed in
`src/orchestration/model_adapter.py`.

**What failed.** All three engineering tasks:

- **A** planned only a test node; its reply was rejected as a malformed code
  fence and the turn ended without recovery.
- **B** "completed" its plan by creating `src/req_001_module.py`,
  `src/req_003_module.py`, `tests/test_req_001_module.py` — requirement-ID
  targets. `mini_math` was never read or edited.
- **C** planned one `task_main` node and returned `BLOCKED` without running the
  failing tests; the injected `multiply()` regression remains.

**Root cause.** The engineering path binds **no tools**: no listing, reading,
searching, command execution or test execution. The planner therefore invents
file targets from requirement IDs.

**Do not claim** that engineering tasks can be completed by this build, and do
not describe verification-only outcomes as engineering success.

**Next (not authorized).** Phase 2a read-only tool binding + real-path planning;
2b one bounded format recovery; 2c bounded test-diagnose-repair loop through the
broker and approval gateway. Deterministic tests before any further paid run.

**Evidence.** `CRUSOR_AGENT_CORE_ENGINEERING_QUALIFICATION.md`,
`CRUSOR_AGENT_CORE_TERMINAL_QUALIFICATION.md`,
`%TEMP%\CrusorLiveE2E\evidence\backend-qual.json`.

---

## 9. Phase 2A — workspace discovery (2026-11-12, uncommitted)

**What changed.** The engineering lifecycle now inspects the workspace before
planning. Three bounded read-only capabilities live in
`src/workspace/discovery.py` (`workspace.list_files`, `workspace.read_file`,
`workspace.search`); `src/workspace/evidence.py` ranks the results. The contract
resolves explicit → requested → discovered → synthesis (request-named, never a
requirement id); ambiguity blocks pre-dispatch. The orchestrator runs this in
STAGE 3 before `CONTRACT_EXTRACTION`, journals every call, and reports
`workspace_discovery` in the delivery.

**Evidence.** `test_workspace_discovery_phase2a.py` 9 passed (A–H, including a
graph-level proof that discovery precedes contract/plan); 76 + 115 + 5 + 261
regression tests pass. Disposable `mini_math` acceptance: 5 files, 10 tool
calls, targets `src/mini_math/ops.py` + `tests/test_ops.py`, 0 paid calls with
repairs disabled.

**Not done.** No targeted edit of an existing file (whole-file regeneration
remains), no discovery-driven repair loop, no format recovery. Discovery is
lexical, not semantic; it blocks rather than fabricates when unsure.

**Spend.** One unintended `repair_task_ops` dispatch (₹0.0601) from a mock-mode
harness with repairs enabled; total programme ₹0.4808 / ₹50. See B-CORE-006.

**Pre-existing failures (not this phase).** `test_p0_3_orchestrator_integration`
(`turn_lifecycle`) and 3 `test_autonomous_runtime_contract` chat-prompt tests
fail from uncommitted prompt/bridge work — B-PRE-001.

**Report.** `CRUSOR_PHASE_2A_WORKSPACE_DISCOVERY.md`.

**Next (designed, not implemented).** Phase 2D — outside-workspace access with a
human grant: ask once per exact path through the existing approval queue, read
and write separate, grants expire at turn end, sensitive names still refused,
traversal never becomes a prompt. Design:
`CRUSOR_PHASE_2D_OUTSIDE_WORKSPACE_ACCESS.md`. Do not implement before owner
approval; do not widen Phase 2A's default silently.

**Update 2026-11-12.** Phase 2D **reads and writes** are implemented and
verified (`test_outside_workspace_access.py`, 17 passed): `workspace.access`
approval, turn-scoped `once`/`turn` grants, exact boundaries, sensitive veto,
external context, and create/modify through the broker with the normal
diff-bound mutation token. Delete/rename/copy outside remain unsupported
(B-CORE-007); approval wording is generic (B-CORE-008). No paid calls.
