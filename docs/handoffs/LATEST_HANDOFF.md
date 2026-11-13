# CrusorAI - Latest Handoff

**Handoff date:** 2026-11-12 (P1-A test isolation repair + R2/R3 remediation)
**Branch:** `feat/prompt-cache-stabilization`
**HEAD:** `fb5bd528b40933346c4004a1490154683dc0d40e`
**Origin:** `origin/main` is 3 commits ahead (release follow-ups); nothing pushed
**Current phase:** P1-A + R2 + R3 fix checkpoint/session test isolation and the
B-4 SQLite URI path defect; P1-B (collection errors and known test failures) is
the next gate after acceptance; production readiness is not claimed

> The prior handoff (audit + memory reconciliation) is archived at
> `docs/handoffs/HISTORY/2026-11-12_p1a-pre.md`.
> The verified condition of record is
> `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` (F-01…F-15).

---

## 0. Read this first (2026-11-12 P1-A + R2 + R3)

- **Working tree:** 272 entries — 84 modified tracked, 188 untracked, 0 staged,
  0 deletions. (264 at the audit close; P1-A added the isolation changes and a
  handoff archive; P1-A-R2 added the bridge/OTel fixes and the B-1 regression
  module; P1-A-R3 added the URI helper and the B-4 regression module.)
- **Checkpoint/session isolation:** fixed. `chat_graph` resolves
  `CRUSORAI_CHECKPOINT_DB`/`CRUSORAI_CHECKPOINT_HOME`/`CRUSORAI_SESSIONS_DB`/
  `CRUSORAI_HOME`, opens lazily, and conftest pins all three stores to a
  throwaway runtime root. The bridge's `prior_checkpoints` count and the OTel
  test cleanup now use the same resolved checkpoint DB (R2). R3 encodes that
  path with `Path.as_uri()` + `mode=ro`, so `#`, `?`, `%`, spaces and Unicode
  cannot select another database. The real
  `~/.crusorai/{sessions,runtime_events,verification}.db` main files and
  `-wal`/`-shm` sidecars were byte-identical across the final R3 run.
- **Tests (P1-A + R2 + R3):** 22 checkpoint-isolation, 4 bridge B-1 and 6 URI
  tests pass (1 Windows-only `?` end-to-end skip); core gate **366 passed / 2
  skipped / 1 xfailed** (193.28 s); targeted P1-A receipt **43 passed**
  (102.62 s); graph persistence/restart **72 passed** (27.81 s); session
  pipeline **7 passed**; OTel **7 passed**. Known red: 2 bridge frame/signature
  pins, 3 `test_runtime_evidence_capture` failures (2 Windows mode bits, 1
  pre-existing echo/degraded expectation), plus the P1-B collection errors.
- **F-05 is PARTIAL:** path/import/bridge/OTel/URI isolation fixed;
  retention/vacuum and workspace-specific placement remain open.
- **Do not begin P1-B** until this P1-A + R2 + R3 change is independently
  accepted.

---

## 1. Where the project stands

- Production hardening phases 0–1.4 remain **WINDOWS SECURITY QUALIFIED**.
- Phase 2 r1/r2 remain `DESKTOP_PARTIAL` (light-theme and headed-GUI gaps).
- Phase 3.1/3.2 remain PASS (bounded); Agent Runtime Increments 1–3 are
  committed at `5197937a` (the later visibility/card work is uncommitted).
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

- Status at handoff: **272 entries** (84 modified, 188 untracked, 0 staged, 0
  deletions); all pre-existing user work preserved. The 264-entry figure was
  the audit close; P1-A added the isolation changes and archive, P1-A-R2 added
  the bridge/OTel fixes and the B-1 regression module, and P1-A-R3 added the URI
  helper and the B-4 regression module.
- The Agent Runtime increments are committed at `5197937a`; the later
  visibility/card work, desktop artifacts and docs are uncommitted.
- `docs/` is tracked; these 2026-11-12 updates are uncommitted.
- A recovery snapshot from 2026-11-10 is preserved at
  `C:\Users\Administrator\AppData\Local\Temp\opencode\crusor-snapshot-20261110`.
- Do not clean/reset/revert/stash. No commit or push was authorized.

## 6. Open risks and next actions

The 2026-11-12 audit sets this order; do not start a later item while an earlier
one is red.

1. **Security defaults (F-03/F-04).** Default `ask`; broker + sandbox + scrubbed
   env for all process creation; approval for model-generated test execution.
2. **Engineering capability (F-01).** Phase 2B: bind tools during generation,
   targeted edits, unconditional requirement-id rejection.
3. **Test/CI baseline (P1-B, F-02/F-06).** Fix the three collection errors,
   update the two bridge pins and the card-type pin, run the full suite, gate it
   in CI. Do not start until P1-A is reviewed.
4. **Persistence/observability (F-05/F-06).** Checkpoint path/import isolation
   is fixed (P1-A); add retention/vacuum, decide workspace placement, and fix
   the `src/observability` collision.
5. **Authorization/money (F-07/F-08).** Real principal, cancellation accounting,
   pricing provenance.
6. **Working-tree disposition** (272 entries): commit reviewed work or retain
   explicitly. No commit is authorized by this handoff.
7. **Real-provider verification** of progress/outcomes/cards requires an explicit
   paid-call authorization; mock-mode evidence is complete.
8. **Legacy card ambiguity** remains: journals without request hashes leave cards
   unassigned (warned, never merged).
9. Do not claim production readiness from this work.

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
- **Do not assume `ask` is the product default.** The bridge defaults to
  `workspace_session`; the Electron acceptance scripts force `ask` (F-04).
- **Checkpoint storage is env-resolved and lazy (P1-A).** Resolution is
  `CRUSORAI_CHECKPOINT_DB` > `CRUSORAI_CHECKPOINT_HOME` >
  `CRUSORAI_SESSIONS_DB` > `CRUSORAI_HOME` > default; do not reintroduce an
  import-time `sqlite3.connect`, `os.makedirs`, or `memory.setup()`. Tests must
  keep conftest's home/sessions/checkpoint overrides.
- **Do not cite observability receipts.** `src/observability/` shadows
  `src/observability.py`; `record_turn_receipt` is unavailable and swallowed
  (F-06).
- **Do not claim engineering tool use.** Generation binds no tools and
  whole files are regenerated; requirement-id fallback is still reachable (F-01).
- **Do not claim RBAC enforcement.** The engineering adapter uses a hard-coded
  superadmin (F-07).
- **Do not claim complete spend after a cancelled paid turn.** The hold is
  released and usage is recorded as zero (F-08).
- **Do not treat `src/req_*_module.py` as product code.** They are generated
  contamination (F-11).

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
resolves explicit → requested → discovered → synthesis (request-named when a
synthesis key exists; the requirement-id fallback is still reachable — F-01);
ambiguity blocks pre-dispatch. The orchestrator runs this in
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

---

## 10. Engineering audit + memory reconciliation (2026-11-12, docs-only)

**What changed (documentation only).** `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md`
was added as the append-only findings register (F-01…F-15). `AGENTS.md`,
`docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`,
`docs/BUGS_AND_LIMITATIONS.md`, `docs/DECISIONS.md`, `docs/ROADMAP.md`,
`docs/phases/PHASE_TRACKER.md` and this handoff were reconciled to it.

**Corrected facts.**

- Working tree 262 entries at the audit, **264 after this reconciliation**
  (80 modified, 184 untracked, 0 staged, 0 deletions), not 175/195/211/247.
- Broker wired at HEAD; B-001 closed. B-DESK-001 fixed; B-015 resolved at HEAD
  for the desktop, partial for other entry points.
- Bridge always calls `stream_agent`; no `CRUSORAI_ORCHESTRATOR_ENGINE` owner
  selector.
- Test suite: 4,953 collected, 3 collection errors, 3 known failures; security
  232/3; checkup 57/5/0.
- Agent Runtime increments committed at `5197937a` (not uncommitted).

**Open (see F-IDs).** Engineering tool binding (F-01), test gate (F-02),
execution defaults (F-03), approval default (F-04), checkpoint persistence
(F-05), observability collision (F-06), RBAC (F-07), FinOps (F-08),
verification strength (F-09), entry-point parity (F-10), generated-source
contamination (F-11), streaming measurement (F-13), guard drift (F-14), stash
disposition (F-15).

**No source, dependency, git or provider change was made.** Nothing committed or
pushed. The prior handoff snapshot is archived at
`docs/handoffs/HISTORY/2026-11-12_pre-reconciliation.md`.

---

## 11. P1-A — test isolation repair (2026-11-12, verified)

**Root cause.** `chat_graph.py` hardcoded `~/.crusorai/sessions.db`, created the
directory and opened the connection at import, and ignored the test/home
overrides. In-process bridge tests also wrote `crusor_sessions` rows to the real
DB because conftest did not redirect the durable session store.

**What changed.**

- `src/runtime/app_paths.py` — `session_db_path()` and `checkpoint_db_path()`.
  Checkpoint precedence: `CRUSORAI_CHECKPOINT_DB` >
  `CRUSORAI_CHECKPOINT_HOME` > `CRUSORAI_SESSIONS_DB`/`_PATH` >
  `CRUSORAI_HOME` > default.
- `src/graphs/chat_graph.py` — lazy `_LazySqliteConnection`; import opens
  nothing; first operation creates the configured DB and applies PRAGMAs.
- `src/runtime/session_store.py` — shared path resolver (same precedence).
- `src/runtime/app_paths.py` — `workspace_app_data_root()` honours
  `CRUSORAI_HOME`, keeping per-workspace app data under the test home.
- `src/tests/conftest.py` — throwaway `CRUSORAI_HOME` / `CRUSORAI_SESSIONS_DB` /
  `CRUSORAI_CHECKPOINT_HOME`; clears `CRUSORAI_CHECKPOINT_DB`.
- `src/tests/test_checkpoint_isolation.py` — 15 tests.

**Verification.** 15 isolation tests pass; core gate 366 passed / 2 skipped / 1
xfailed (193.28 s, exit 0); graph/restart 139 passed; session/acceptance 35
passed; security 232 passed / 3 skipped; checkup 57/5/0. The real
`~/.crusorai/{sessions,runtime_events,verification}.db` were unchanged across
the gate (`sessions.db` sha256 `5fc06788…`, 937,684,992 bytes). Known red:
2 bridge pins, 3 `test_runtime_evidence_capture` failures, and the P1-B
collection errors.

**Remaining.** F-05 stays PARTIAL: no VACUUM/prune/retention; 937 MB DB and 426
index DBs; workspace placement not introduced. Do not begin P1-B until this
change is independently reviewed.

---

## 12. P1-A-R2 — independent-review remediation (2026-11-12, verified)

**Trigger.** The independent P1-A review returned **REJECT** for acceptance
(not for the lazy-checkpointer design). Two blocking leaks still reached the
real `~/.crusorai/sessions.db`:

- **B-1:** `src/bridge/__main__.py::_prior_checkpoint_count` defaulted to
  `~/.crusorai/sessions.db` and ignored every override; `session_create` called
  it with no path. Reading the real WAL changed `sessions.db-shm` mtime.
- **B-2:** `src/tests/test_otel_tracing.py::_drop_checkpoints` opened the real
  DB read-write and executed `DELETE FROM checkpoints`.

**What changed.**

- `src/bridge/__main__.py` — the default is the graph's captured
  `_CHECKPOINT_DB` when that module is already imported, otherwise
  `checkpoint_db_path()` (the graph's exact env contract); an explicit
  `db_path` remains an override for direct callers. No silent home fallback.
- `src/tests/test_otel_tracing.py` — cleanup resolves
  `chat_graph._CHECKPOINT_DB`, refuses the real home DB, and uses
  `SqliteSaver.delete_thread()` on the graph's own saver (direct SQL against the
  isolated file only as fallback). Stale import-time-binding comments removed.
- `src/tests/test_checkpoint_isolation.py` — 22 tests. The real-data check now
  covers nine main/sidecar files (`sessions`, `runtime_events`, `verification`
  × `.db`, `-wal`, `-shm`) plus journal files, using full SHA-256 +
  existence/size/mtime. Added directory-target, parent-is-file, nested-parent,
  writable-custom-location and fail-closed-without-fallback tests, plus a B-2
  cleanup regression.
- `src/tests/test_prior_checkpoint_isolation.py` (new, 4 tests) — real stdio
  bridge subprocesses prove `session_create`/`session_resume` read the custom
  checkpoint DB (2 rows) over the custom session DB (7 rows), use a custom
  session DB when no checkpoint override exists, report zero for a missing
  override instead of reading a decoy home DB, and leave the real DB untouched.

**Error contract (documented, fail-closed).**

| Invalid checkpoint location | Observed |
|---|---|
| Path is an existing directory | `sqlite3.OperationalError: unable to open database file` |
| Parent path is a regular file | `FileExistsError` / `NotADirectoryError` (`OSError`) |
| Nested parent missing | parent created lazily, then DB created |
| Unwritable/invalid override | graph setup raises; no home-DB fallback |

**Verification receipts.**

| Command | Result | Exit |
|---|---|---|
| `pytest src/tests/test_checkpoint_isolation.py` | **22 passed**, 56.50 s | 0 |
| `pytest src/tests/test_prior_checkpoint_isolation.py` | **4 passed**, 26.10 s | 0 |
| P1-A targeted receipt (22 isolation + 11 plan completion + 1 workspace isolation + 2 bridge transport + 7 session pipeline) | **43 passed**, 102.62 s | 0 |
| Final R2 receipt (43 + 4 B-1 bridge tests) | **47 passed**, 181.89 s | 0 |
| Persistence/restart subset (increment 2/3, invocation reconciliation, session store/search) | **72 passed**, 27.81 s | 0 |
| B-2 regression + real-data immutability + B-1 suite re-run | **6 passed**, 40.26 s | 0 |

**Real-data evidence.** Full SHA-256 + size + mtime for all nine files and three
journal paths were identical before/after the final 47-test run; all 61
workspace directories were unchanged. Current values are in
`docs/CURRENT_STATE.md`. During an early B-1 draft the test omitted
`CRUSORAI_HOME`, so `session_resume` opened the real journal and changed only
`runtime_events.db-shm` mtime (content hash stayed
`67dea1a5…`). The test was corrected to pin `CRUSORAI_HOME`; the final run shows
no changes at all.

**Remaining.** F-05 stays PARTIAL (no VACUUM/prune/retention; 937 MB DB and 426
index DBs; workspace placement not introduced). The full `test_otel_tracing.py`
module was **not** executed in R2; the corrected cleanup was exercised through
the new B-2 regression instead. P1-A + R2 must pass another independent review
before P1-B starts. No commits or pushes were made.

---

## 13. P1-A-R3 — SQLite URI path correction (2026-11-12, verified)

**Trigger.** The final independent review rejected P1-A on **B-4**:
`_prior_checkpoint_count` built `f"file:{db}?mode=ro"`. A legal `#` in the path
started a URI fragment. With intended DB `cp#frag/sessions.db` = 2 checkpoints
and a decoy file `cp` = 1, `session_create` returned 1.

**What changed.**

- `src/runtime/app_paths.py` — new `sqlite_readonly_uri(db_path)`:
  `Path(db_path).resolve().as_uri() + "?mode=ro"`. It preserves absolute path
  resolution, Windows/POSIX path handling, read-only mode and the 2.0 s timeout,
  while encoding `#`, `?`, `%`, spaces and Unicode.
- `src/bridge/__main__.py` — `_prior_checkpoint_count` uses the helper. Path
  precedence, captured-graph preference and no-home-fallback behavior are
  unchanged. The lazy `_LazySqliteConnection` was not touched.
- `src/tests/test_checkpoint_uri_isolation.py` (new, 7 tests) — real bridge
  subprocesses for `#` + decoy, spaces, `%`, Unicode; URI encoding assertion for
  `?`; POSIX-only actual `?` filename; read-only write rejection + hash
  unchanged.

**Verification receipts.**

| Command | Result | Exit |
|---|---|---|
| `pytest src/tests/test_checkpoint_uri_isolation.py` | **6 passed, 1 skipped**, 25.55 s | 0 |
| URI + prior-checkpoint + isolation suite | **32 passed, 1 skipped**, 109.47 s | 0 |
| `pytest src/tests/test_session_pipeline.py` | **7 passed**, 51.52 s | 0 |
| `pytest src/tests/test_otel_tracing.py` | **7 passed**, 8.96 s | 0 |

**B-4 repro.** Intended 2 rows vs pre-`#` decoy 1 row now reports
`prior_checkpoints = 2`; the old construction returned 1. Read-only mode rejects
`DELETE` and leaves the DB hash unchanged.

**Real-data evidence.** Full SHA-256 + size + mtime for all nine main/sidecar
files and three journal paths, plus all 61 workspace directories, were identical
before/after the R3 verification run.

**Remaining.** F-05 stays PARTIAL (no VACUUM/prune/retention; 937 MB DB, 426
index DBs, workspace placement). The literal `?` end-to-end bridge case cannot
run on Windows because the filesystem forbids `?`; the URI assertion always runs
and the end-to-end case runs on POSIX. P1-A + R2 + R3 must pass independent
acceptance before P1-B starts. No commits or pushes were made.


---

## 2026-11-12 (later) — Implementation start

**Branch:** `wip/working-tree-2026-11-12` · **HEAD:** see `git rev-parse HEAD` (not pinned here to avoid drift)
**State:** reconciliation R1–R4 committed; T-06 done; T-17 part 1 done (collection clean).
**Next unblocked ticket:** T-18 (move full suite into `.github/workflows`, red/green proof), then T-07
(receipt emission) now that T-06 unblocked it.
**Constraints unchanged:** no merge to main; no public release; no expensive provider runs until a spending
limit is confirmed; generated `req_*` modules and private runtime data stay out of git (R0 has them).
**Landmine:** `src/observability/` is a package — never re-create `src/observability.py`, or F-06 returns.



---

## 2026-11-12 (T-18) — CI truth gate PARTIAL, T-07 not started

**Branch:** `wip/working-tree-2026-11-12` · **Commits:** `caeca301`, `1ddb6143`

**Done:** workflow relocated to `.github/workflows/agent-core.yml`; concealment removed; red-on-red proven
(exit 1 on a deliberate failure, temp file removed); parity-test drift fixed (`test_hermes_activity_parity`
now 120 passed / 8 skipped / 1 xfailed).

**Blocking green-on-green:**
1. Approval-dock contract test expects an inline `crusorai-approval-diff-preview`; the dock now uses a
   "Review change" button + native diff. Needs a product decision (restore inline preview vs update contract).
2. `test_degraded_memory.py` hangs >120 s alone (both HOME modes). Likely a lazy initialisation inside
   `finalize_node`; must be diagnosed before any full-suite run can complete.

**T-07 status:** investigation complete, **no code written** — its gate is T-18. Findings: receipts are emitted
only from `finalize_node`; `recovery_limit` and `tool_cycle_limit` go straight to `END` with no receipt; no
duplicate guard; missing usage coerced to zero; `error` text unredacted; write failures swallowed.

**Next authorised action:** none until the founder decides on the two blockers or authorises T-07 past the gate.



---

## 2026-11-12 (T-18 continued)

**Commit:** `c2a36e32` — inline approval diff restored (Option B) + degraded-memory test bounded.

**T-18 still PARTIAL.** Remaining blocker is not CI wiring: 7 pre-existing failures in
`test_unknown_tool_validation` (1) and `test_user_interest` (6), plus a >40-minute suite runtime against a
30-minute workflow timeout. Red-on-red is proven. Green-on-green is not.

**Next:** triage the 7 failures (product behaviour, likely from the R2 task-manager changes), then measure the
suite on a real Linux runner. Do not start T-07 until the gate is met or the founder authorises past it.



---

## 2026-11-12 (T-22)

**Commit:** `242decbb`. Seven failures fixed; origin proven to pre-date R2.

**Two regressions worth remembering:**
1. A `**` expansion placed after explicit keys silently overwrote them (`task_action` became `""` every turn).
2. Policy classified tool names before canonicalization, letting an alias reach an approval prompt instead of a
   denial. Canonicalize first; deny by the canonical name.

**Linux runtime:** unmeasured (no WSL distro, no Docker). Do not claim the 30-minute CI timeout is safe.
**T-18:** PARTIAL until the full suite is green. **T-07:** still gated.



---

## 2026-11-12 (T-23)

**Commits:** `20a5cbe0`, `702d6f3f`, `8b2fad9e`.
Baseline: 105 failures / 41 modules at HEAD vs 100 / 40 at `7e4bb7ad`; R2 caused one.

**Next minimum for a defensible T-18 gate:**
1. Decide P1 (shell boundary): xfail-with-T-10-reference vs re-enable after T-11/T-10.
2. Fix P5 (write refusal) and P4 (prompt shape) — both product, both independent.
3. Add `pytest-timeout` and `--durations` to get attributed runtime.
4. Install desktop node deps in CI so parity modules fail instead of skipping.
5. Obtain a real Linux run before claiming green; 30-minute timeout is unvalidated.

**Do not claim Linux verification from a Windows run.**



---

## 2026-11-13 (T-23 continuation)

**P5 fixed:** `f2660e9f`. **P4 blocked on a founder decision:** re-pin shape tests vs revert `09462482`.
**T-24 opened:** finalization audit cost (4–7 audits/turn; repo root >120 s; `desktop/` is the cost centre).

**Before any push:** decide P4, then run one focused wave (P5 done; next are the write-refusal/approval-token
defect and the prompt-shape choice), then a real Linux run. 30-minute timeout stays unvalidated.



---

## 2026-11-13 (T-23 finalization)

**P4:** `b151a746` (79 passed). **P5:** `f2660e9f`. **Token policy tests:** `fe5faf14`. **CI prep:** `5414ee16`.

**Next blocker:** the write-refusal defect needs a two-file security change — `file_tools.py` must route an
existing target to `modify_file`, and `chat_graph.py` must derive `CREATE`/`MODIFY` from `payload["action"]`.
Landing only one of them breaks canonical-runtime writes; relaxing the broker breaks two security suites.
This needs its own focused session plus a security review, not a tail-end patch.

**Linux:** still unmeasured. Do not claim green from Windows.



---

## 2026-11-13 (T-23 closure)

Operation contract fixed in `f7992f74` (92 passed, 1 skipped). P4 `b151a746`. P5 `f2660e9f`. CI `5414ee16`.

**Remaining T-18 blockers:** genuine Linux run; shell-boundary tests pending T-10/T-11; P2/P3/P6/P7/P8/P9
classes from the T-23 inventory; T-24 performance work (separate). No push.

