# P1-A Independent Review Bundle

**Generated:** 2026-11-12  
**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Purpose:** Export the actual P1-A/R2/R3 implementation changes for independent review by ChatGPT.  
**Mode:** Investigation/export only. No commits, pushes, resets, cleans, stashes, rebases, or branch switches. No existing project memory was modified. Only this bundle file was created.  

---

## 1. Repository state

- **Branch:** `feat/prompt-cache-stabilization`
- **HEAD:** `fb5bd528b40933346c4004a1490154683dc0d40e`
- **Staged files:** 0
- **Modified tracked files:** 84
- **Untracked status entries:** 188 (the `git status --porcelain` count; `git ls-files --others --exclude-standard` enumerates 1,638 individual files because some untracked directories are collapsed in status)
- **Dirty entries:** 272 (84 modified, 188 untracked status entries, 0 staged, 0 deletions), matching the R3 handoff. **Status was captured before this bundle file was created; including the bundle itself, the final tree has 273 entries (84 modified, 189 untracked status entries).**

### `git status --porcelain=v1`

```text
 M AGENTS.md
 M apps/personal_finance/backend/main.py
 M apps/personal_finance/backend/models.py
 M apps/personal_finance/backend/repositories/budget_repo.py
 M apps/personal_finance/backend/repositories/category_repo.py
 M apps/personal_finance/backend/repositories/transaction_repo.py
 M apps/personal_finance/backend/routers/budgets.py
 M apps/personal_finance/backend/routers/categories.py
 M apps/personal_finance/backend/routers/dashboard.py
 M apps/personal_finance/backend/routers/export.py
 M apps/personal_finance/backend/routers/transactions.py
 M apps/personal_finance/backend/services/budget_service.py
 M apps/personal_finance/backend/services/dashboard_service.py
 M apps/personal_finance/backend/services/export_service.py
 M apps/personal_finance/backend/services/transaction_service.py
 M apps/personal_finance/frontend/index.html
 M apps/personal_finance/frontend/package.json
 M apps/personal_finance/frontend/src/App.tsx
 M apps/personal_finance/frontend/src/api.ts
 M apps/personal_finance/frontend/src/main.tsx
 M apps/personal_finance/frontend/src/types.ts
 M apps/personal_finance/frontend/tsconfig.json
 M desktop/vscode/extensions/copilot/package-lock.json
 M desktop/vscode/extensions/package-lock.json
 M desktop/vscode/out/vs/workbench/contrib/crusorai/browser/BUILD_INFO.json
 M desktop/vscode/out/vs/workbench/contrib/crusorai/browser/SOURCES_HASH
 M desktop/vscode/out/vs/workbench/contrib/crusorai/browser/SOURCES_MANIFEST.json
 M desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIActivity.js
 M desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIRenderer.js
 M desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIRendererService.js
 M desktop/vscode/out/vs/workbench/contrib/crusorai/browser/media/crusorAI.css
 M desktop/vscode/out/vs/workbench/contrib/crusorai/common/crusorAICards.js
 M desktop/vscode/remote/package-lock.json
 M desktop/vscode/scripts/accept-crusorai-engineering.mjs
 M desktop/vscode/scripts/accept-crusorai-streaming.mjs
 M desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIActivity.ts
 M desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRenderer.ts
 M desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRendererService.ts
 M desktop/vscode/src/vs/workbench/contrib/crusorai/browser/media/crusorAI.css
 M desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAICards.ts
 M desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAIProtocol.ts
 M desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAISessionProjection.ts
 M desktop/vscode/test/mcp/package-lock.json
 M diagnostics/LATEST_PERFORMANCE_AUDIT.md
 M diagnostics/PERFORMANCE_REPORT_cancel-test.md
 M diagnostics/PERFORMANCE_REPORT_default.md
 M diagnostics/PERFORMANCE_REPORT_s-wd.md
 M diagnostics/PERFORMANCE_REPORT_t1.md
 M diagnostics/traces/cancel-test.jsonl
 M docs/ARCHITECTURE.md
 M docs/BUGS_AND_LIMITATIONS.md
 M docs/CURRENT_STATE.md
 M docs/DECISIONS.md
 M docs/ROADMAP.md
 M docs/handoffs/HISTORY/README.md
 M docs/handoffs/LATEST_HANDOFF.md
 M docs/phases/PHASE_TRACKER.md
 M scripts/test_crusorai_cards.mjs
 M src/bridge/__main__.py
 M src/bridge/agent_cards.py
 M src/graphs/chat_graph.py
 M src/llm/factory.py
 M src/llm/gateway.py
 M src/llm/scripted_model.py
 M src/orchestration/approval_gateway.py
 M src/orchestration/context_manager.py
 M src/orchestration/contract.py
 M src/orchestration/model_adapter.py
 M src/orchestration/models.py
 M src/orchestration/orchestrator.py
 M src/orchestration/planner.py
 M src/orchestration/scheduler.py
 M src/orchestration/visibility.py
 M src/req_001_module.py
 M src/req_002_module.py
 M src/runtime/app_paths.py
 M src/runtime/session_store.py
 M src/tests/conftest.py
 M src/tests/test_desktop_renderer_architecture.py
 M src/tests/test_desktop_session_pipeline.py
 M src/tests/test_otel_tracing.py
 M src/verification/authority.py
 M src/verification/engine.py
 M src/workspace/mutation_broker.py
?? ACTUAL_EXECUTION_PATH_AUDIT.md
?? COMPLETE_INTEGRATION_ARCHITECTURE.md
?? CRUSOR_AGENTIC_TIMELINE_REPORT.md
?? CRUSOR_AGENT_CORE_ENGINEERING_QUALIFICATION.md
?? CRUSOR_AGENT_CORE_TERMINAL_QUALIFICATION.md
?? CRUSOR_COMPLETE_FRONTEND_ARCHITECTURE_AUDIT.md
?? CRUSOR_CONVERSATIONAL_UI_RESTORATION_REPORT.md
?? CRUSOR_CONVERSATIONAL_UI_RESTORE.md
?? CRUSOR_FRONTEND_UNDERSTANDING.md
?? CRUSOR_P0_CONTRACT_AND_FAILURE_REPORT.md
?? CRUSOR_P1A_ENGINEERING_STREAMING_REPORT.md
?? CRUSOR_PACED_STREAMING_EXPERIMENT.md
?? CRUSOR_PHASE_2A_WORKSPACE_DISCOVERY.md
?? CRUSOR_PHASE_2D_OUTSIDE_WORKSPACE_ACCESS.md
?? CRUSOR_PLAN_COMPLETION_REPORT.md
?? CRUSOR_PLAN_OUTCOME_SEMANTICS_REPORT.md
?? CRUSOR_PROGRESS_INTEGRATION_REPORT.md
?? CRUSOR_REAL_PROVIDER_E2E_QUALIFICATION.md
?? CRUSOR_STREAMING_REPAINT_DIAGNOSTIC.md
?? CRUSOR_TURN_CARD_RESTORATION_REPORT.md
?? DESKTOP_TO_AGENT_INTEGRATION.md
?? DISCONNECTED_COMPONENTS_REPORT.md
?? FINAL_CRUSOR_DESKTOP_ENGINEERING_DEMO.md
?? INTEGRATION_GAP_ANALYSIS.md
?? MOCK_VS_REAL_TEST_EVIDENCE.md
?? OPENCODE_EXECUTION_ARCHITECTURE_COMPARISON.md
?? PERFORMANCE_AND_FINOPS_RESULTS.md
?? PHASE_12_0_1_FINAL_VERDICT.md
?? PHASE_12_1_1_DESKTOP_RUNTIME_EVIDENCE.md
?? PHASE_12_1_1_END_TO_END_RESULTS.md
?? PHASE_12_1_1_FINAL_VERDICT.md
?? PHASE_12_1_1_IDENTITY_FINOPS_EVIDENCE.md
?? PHASE_12_1_1_MODEL_EXECUTION_EVIDENCE.md
?? PHASE_12_1_1_REMAINING_LIMITATIONS.md
?? PHASE_12_1_1_SECURITY_QUALIFICATION.md
?? PHASE_12_1_1_TEST_RECONCILIATION.md
?? PHASE_12_1_1_WORKSPACE_INTEGRITY.md
?? PHASE_12_1_2_APPCONTAINER_INTEGRATION.md
?? PHASE_12_1_2_DESKTOP_END_TO_END.md
?? PHASE_12_1_2_DESKTOP_LAUNCH_REPORT.md
?? PHASE_12_1_2_ELECTRON_ROOT_CAUSE.md
?? PHASE_12_1_2_FAILURE_RECOVERY.md
?? PHASE_12_1_2_FINAL_VERDICT.md
?? PHASE_12_1_2_LIVE_MODEL_EXECUTION.md
?? PHASE_12_1_2_OS_SECURITY_TESTS.md
?? PHASE_12_1_2_REGRESSION_RESULTS.md
?? PHASE_12_1_2_REMAINING_LIMITATIONS.md
?? PHASE_12_1_3_APPCONTAINER_EVIDENCE.md
?? PHASE_12_1_3_DESKTOP_ENGINEERING_TASK.md
?? PHASE_12_1_3_ELECTRON_RUNTIME.md
?? PHASE_12_1_3_FINAL_VERDICT.md
?? PHASE_12_1_3_LIVE_MODEL_PROVIDER.md
?? PHASE_12_1_3_NETWORK_ISOLATION.md
?? PHASE_12_1_3_REGRESSION_RESULTS.md
?? PHASE_12_1_3_REMAINING_LIMITATIONS.md
?? PHASE_12_1_3_REPRODUCIBLE_BUILD.md
?? PHASE_12_1_3_WORKSPACE_INTEGRITY.md
?? PHASE_12_1_BASELINE_AND_WORKSPACE_AUDIT.md
?? PHASE_12_1_DESKTOP_EXECUTION_ARCHITECTURE.md
?? PHASE_12_1_DESKTOP_PROGRESS_INTEGRATION.md
?? PHASE_12_1_END_TO_END_TEST_RESULTS.md
?? PHASE_12_1_FINAL_VERDICT.md
?? PHASE_12_1_IDENTITY_FINOPS_INTEGRATION.md
?? PHASE_12_1_MODEL_EXECUTION_INTEGRATION.md
?? PHASE_12_1_MUTATION_SECURITY_REPORT.md
?? PHASE_12_1_PRODUCTION_READINESS_INTEGRATION.md
?? PHASE_12_1_REMAINING_LIMITATIONS.md
?? PHASE_CDP_DESKTOP_RUNTIME.md
?? PHASE_CDP_UI_INTERACTION_EVIDENCE.md
?? PHASE_LIVE_ACCEPTANCE_LIMITATIONS.md
?? PHASE_LIVE_FAILURE_RECOVERY.md
?? PHASE_LIVE_FINOPS_ATTRIBUTION.md
?? PHASE_LIVE_PRODUCT_ACCEPTANCE_FINAL.md
?? PHASE_LIVE_REGRESSION_RESULTS.md
?? PHASE_LIVE_VELONA_PROVIDER_EVIDENCE.md
?? PHASE_REAL_MODEL_ENGINEERING_TASK.md
?? PHASE_WORKSPACE_SECURITY_RESULTS.md
?? REAL_RUNTIME_TEST_RESULTS.md
?? REMAINING_LIMITATIONS.md
?? SECURITY_BOUNDARY_INTEGRATION_AUDIT.md
?? SUBSYSTEM_INTEGRATION_MATRIX.md
?? apps/personal_finance/frontend/package-lock.json
?? apps/personal_finance/frontend/src/index.css
?? apps/personal_finance/frontend/vite.config.ts
?? apps/personal_finance/src/
?? apps/personal_finance/tests/test_dashboard.py
?? apps/personal_finance/tests/test_transactions.py
?? desktop/vscode/out/vs/workbench/contrib/crusorai/common/crusorAITurnOutcome.js
?? desktop/vscode/scripts/accept-crusorai-conversation.mjs
?? desktop/vscode/scripts/accept-crusorai-p0.mjs
?? desktop/vscode/scripts/accept-crusorai-progress.mjs
?? desktop/vscode/scripts/accept-crusorai-streaming-engine.mjs
?? desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAITurnOutcome.ts
?? diagnostics/PERFORMANCE_REPORT_plan-approval-test.md
?? diagnostics/generation_boundary/live_acceptance/live11_20261108/evidence_workspace/finops/sessions.db-shm
?? diagnostics/generation_boundary/live_acceptance/live11_20261108/evidence_workspace/finops/sessions.db-wal
?? diagnostics/generation_boundary/live_acceptance/live11_20261108/portable/
?? diagnostics/p0_6_4/user-data/
?? diagnostics/p0_6_4_1/preflight/portable/
?? diagnostics/p0_6_4_1/preflight_raced/
?? diagnostics/p0_6_4_1/preflight_run2/
?? diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt1_failed/
?? diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt2_failed/
?? diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt3_failed/
?? diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt4_failed/
?? diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt5_failed/
?? diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt6_failed/
?? diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt7_failed/
?? diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt8_failed/
?? diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt9_partial_pass/
?? diagnostics/p0_6_5/domcheck/
?? diagnostics/p0_6_5/live/
?? diagnostics/p0_6_5/live2/
?? diagnostics/p0_6_5/live3/
?? diagnostics/p0_6_5/live4/home/runtime_events.db-shm
?? diagnostics/p0_6_5/live4/home/runtime_events.db-wal
?? diagnostics/p0_6_5/live4/home/sessions.db-shm
?? diagnostics/p0_6_5/live4/home/sessions.db-wal
?? diagnostics/p0_6_5/live4/portable/
?? diagnostics/p0_6_5/preflight/
?? diagnostics/p0_6_5/preflight_attempt1/
?? diagnostics/p0_6_5/preflight_final/home/sessions.db-shm
?? diagnostics/p0_6_5/preflight_final/home/sessions.db-wal
?? diagnostics/p0_6_5/preflight_final/portable/
?? diagnostics/p0_6_5/preflight_panel/
?? diagnostics/p0_6_6/live/
?? diagnostics/p0_6_6/live2/
?? diagnostics/p0_6_6/live3/
?? diagnostics/p0_6_6/live4/
?? diagnostics/p0_6_6/live5/
?? diagnostics/p0_6_6/live6/home/runtime_events.db-shm
?? diagnostics/p0_6_6/live6/home/runtime_events.db-wal
?? diagnostics/p0_6_6/live6/home/sessions.db-shm
?? diagnostics/p0_6_6/live6/home/sessions.db-wal
?? diagnostics/p0_6_6/live6/portable/
?? diagnostics/p0_6_7/live7/home/runtime_events.db-shm
?? diagnostics/p0_6_7/live7/home/runtime_events.db-wal
?? diagnostics/p0_6_7/live7/home/sessions.db-shm
?? diagnostics/p0_6_7/live7/home/sessions.db-wal
?? diagnostics/p0_6_7/live7/portable/
?? diagnostics/p0_6_8/live8/home/runtime_events.db-shm
?? diagnostics/p0_6_8/live8/home/runtime_events.db-wal
?? diagnostics/p0_6_8/live8/home/sessions.db-shm
?? diagnostics/p0_6_8/live8/home/sessions.db-wal
?? diagnostics/p0_6_8/live8/portable/
?? diagnostics/p0_6_9/live10/home/runtime_events.db-shm
?? diagnostics/p0_6_9/live10/home/runtime_events.db-wal
?? diagnostics/p0_6_9/live10/home/sessions.db-shm
?? diagnostics/p0_6_9/live10/home/sessions.db-wal
?? diagnostics/p0_6_9/live10/portable/
?? diagnostics/p0_6_9/live9/home/runtime_events.db-shm
?? diagnostics/p0_6_9/live9/home/runtime_events.db-wal
?? diagnostics/p0_6_9/live9/home/sessions.db-shm
?? diagnostics/p0_6_9/live9/home/sessions.db-wal
?? diagnostics/p0_6_9/live9/portable/
?? docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md
?? docs/handoffs/HISTORY/2026-11-10_agent-runtime-increments.md
?? docs/handoffs/HISTORY/2026-11-12_p1a-pre.md
?? docs/handoffs/HISTORY/2026-11-12_pre-reconciliation.md
?? scripts/demonstrate_ui_to_ai.py
?? scripts/streaming_provider_stub.py
?? scripts/test_crusorai_turn_outcome.mjs
?? src/orchestration/generation_progress.py
?? src/orchestration/progress_events.py
?? src/p0_6_2_acceptance.py
?? src/req_003_module.py
?? src/req_004_module.py
?? src/req_005_module.py
?? src/tests/test_checkpoint_isolation.py
?? src/tests/test_checkpoint_uri_isolation.py
?? src/tests/test_contract_natural_language.py
?? src/tests/test_engineering_progress_events.py
?? src/tests/test_engineering_streaming.py
?? src/tests/test_gateway_streaming.py
?? src/tests/test_generation_progress_events.py
?? src/tests/test_outside_workspace_access.py
?? src/tests/test_phase_12_1_1_expense_tracker_task.py
?? src/tests/test_plan_completion.py
?? src/tests/test_plan_outcome_semantics.py
?? src/tests/test_prior_checkpoint_isolation.py
?? src/tests/test_scripted_model_pacing.py
?? src/tests/test_turn_card_association.py
?? src/tests/test_turn_card_rendering.py
?? src/tests/test_turn_outcome_semantics.py
?? src/tests/test_workspace_discovery_phase2a.py
?? src/workspace/access_grants.py
?? src/workspace/discovery.py
?? src/workspace/evidence.py
```

### Files included in this bundle

| Path | Status | Attribution | Included content |
|---|---|---|---|
| `src/runtime/app_paths.py` | modified tracked | P1-A + R3 | full diff |
| `src/bridge/__main__.py` | modified tracked | R2 + R3 (mixed with pre-existing work) | full diff, annotated |
| `src/runtime/session_store.py` | modified tracked | P1-A | full diff |
| `src/graphs/chat_graph.py` | modified tracked | P1-A checkpoint hunk + pre-existing work | full diff, annotated |
| `src/tests/conftest.py` | modified tracked | P1-A | full diff |
| `src/tests/test_checkpoint_isolation.py` | untracked/new | P1-A + R2 | complete file |
| `src/tests/test_prior_checkpoint_isolation.py` | untracked/new | R2 | complete file |
| `src/tests/test_checkpoint_uri_isolation.py` | untracked/new | R3 | complete file |
| `src/tests/test_otel_tracing.py` | modified tracked | R2 | full diff |

## 2. Review boundaries

### 2.1 P1-A (original isolation repair)
- `src/runtime/app_paths.py`: `session_db_path()`, `checkpoint_db_path()`, and the `CRUSORAI_HOME` change in `workspace_app_data_root()`.
- `src/runtime/session_store.py`: durable session store now uses the shared `session_db_path()`.
- `src/graphs/chat_graph.py`: `_LazySqliteConnection`, `_CHECKPOINT_DB = str(checkpoint_db_path())`, lazy `SqliteSaver`, and removal of import-time `memory.setup()`.
- `src/tests/conftest.py`: per-run `CRUSORAI_HOME` / `CRUSORAI_SESSIONS_DB` / `CRUSORAI_CHECKPOINT_HOME` isolation and clearing `CRUSORAI_CHECKPOINT_DB`.
- `src/tests/test_checkpoint_isolation.py`: original 15-test isolation suite (later expanded by R2).
- Documentation updates for P1-A.

### 2.2 R2 (independent-review remediation)
- `src/bridge/__main__.py::_prior_checkpoint_count`: default path changed from hardcoded `~/.crusorai/sessions.db` to the graph's captured `_CHECKPOINT_DB` or `checkpoint_db_path()`.
- `src/tests/test_otel_tracing.py::_drop_checkpoints`: cleanup now targets the graph's resolved checkpoint DB and uses `SqliteSaver.delete_thread()`.
- `src/tests/test_checkpoint_isolation.py`: sidecar/full-hash immutability, invalid-path tests, and B-2 cleanup regression (expanded from 15 to 22 tests).
- `src/tests/test_prior_checkpoint_isolation.py`: 4 bridge B-1 subprocess tests.
- Documentation updates for R2.

### 2.3 R3 (B-4 SQLite URI correction)
- `src/runtime/app_paths.py::sqlite_readonly_uri`: absolute `Path.as_uri()` + `?mode=ro`.
- `src/bridge/__main__.py::_prior_checkpoint_count`: now uses `sqlite_readonly_uri(db)` with the existing `uri=True, timeout=2.0`.
- `src/tests/test_checkpoint_uri_isolation.py`: `#`, space, `%`, Unicode, `?` URI encoding, decoy-at-truncated-path, and read-only write-rejection regressions.
- Documentation updates for R3.

### 2.4 Pre-existing or not attributable to P1-A/R2/R3
- `src/graphs/chat_graph.py` contains large pre-existing engineering-progress/orchestration changes around lines 5271-5432 (progress reporter, generation observer, per-turn storage). These are **not** P1-A/R2/R3 changes and are preserved user work.
- `src/bridge/__main__.py` contains large pre-existing journal/card/transcript work outside `_prior_checkpoint_count`. The full diff is included, but only the `_prior_checkpoint_count` hunk belongs to R2/R3.
- The wider working tree contains 84 modified tracked files and 188 untracked status entries (1,638 individual untracked files); most are unrelated to P1-A/R2/R3. The full `git status` above is the authoritative inventory.
- `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` is an untracked baseline audit/memory artifact, broader than R3. It is cited as evidence but not included as an R3 diff.

### 2.5 Mixed files
- `src/bridge/__main__.py` — mixed (R2/R3 + pre-existing).
- `src/graphs/chat_graph.py` — mixed (P1-A checkpoint hunk + pre-existing).
- Documentation files — mixed memory updates from P1-A/R2/R3 and earlier reconciliation.

### 2.6 Ownership that cannot be established from the working tree alone
- Any uncommitted change outside the explicitly named P1-A/R2/R3 files is treated as pre-existing user work. It is not attributed to R3.
- The `workspace_app_data_root()` production behavior change is attributed to P1-A by the repository memory, but it is a broader path-contract change than the checkpoint fix.

## 3. Technical evidence

### 3.1 `session_db_path()`, `checkpoint_db_path()`, and `sqlite_readonly_uri()`
```python
def session_db_path() -> Path:
    """Resolve the canonical conversation database (sessions + checkpoints).

    Precedence matches the durable session store:
    ``CRUSORAI_SESSIONS_DB`` > ``CRUSORAI_SESSIONS_DB_PATH`` >
    ``CRUSORAI_HOME`` > ``~/.crusorai/sessions.db``.
    """
    explicit = os.environ.get("CRUSORAI_SESSIONS_DB") or os.environ.get(
        "CRUSORAI_SESSIONS_DB_PATH"
    )
    if explicit:
        return Path(explicit).expanduser()
    home = os.environ.get("CRUSORAI_HOME", "").strip()
    if home:
        return Path(home).expanduser() / "sessions.db"
    return Path.home() / ".crusorai" / "sessions.db"


def checkpoint_db_path() -> Path:
    """Resolve the LangGraph checkpoint database path.

    A checkpoint-specific override wins over the shared conversation DB so a
    test (or an isolated run) can relocate checkpoints without moving session
    rows or any other runtime state:

    1. ``CRUSORAI_CHECKPOINT_DB`` — exact file path.
    2. ``CRUSORAI_CHECKPOINT_HOME`` — directory; ``<home>/sessions.db``.
    3. ``session_db_path()`` — the normal shared database.

    Defaults are unchanged: with no environment overrides this returns
    ``~/.crusorai/sessions.db``.
    """
    explicit = os.environ.get("CRUSORAI_CHECKPOINT_DB", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    home = os.environ.get("CRUSORAI_CHECKPOINT_HOME", "").strip()
    if home:
        return Path(home).expanduser() / "sessions.db"
    return session_db_path()


def sqlite_readonly_uri(db_path: str | Path) -> str:
    """Return an absolute, percent-encoded SQLite URI in read-only mode.

    ``Path.as_uri()`` encodes legal filename characters that SQLite would
    otherwise treat as URI delimiters — ``#`` (fragment), ``?`` (query),
    ``%`` (escape), spaces and non-ASCII text — so the connection can never
    silently resolve to a different database.
    """
    return f"{Path(db_path).resolve().as_uri()}?mode=ro"

```

### 3.2 `_LazySqliteConnection` and lazy checkpointer
```python
# Persistent session checkpointer — thread state survives restarts.
# NOTE: SqliteSaver.from_conn_string() returns a context manager (verified),
# so for a module-level saver we hold a direct connection instead.
# check_same_thread=False is required: the dashboard server runs the graph
# from worker threads, and sqlite connections are thread-bound by default.
# The connection is LAZY: importing this module must not create or open a
# database. Tests (and isolated runs) set CRUSORAI_CHECKPOINT_DB /
# CRUSORAI_CHECKPOINT_HOME / CRUSORAI_SESSIONS_DB / CRUSORAI_HOME before the
# import; the first checkpoint read/write opens that path. Defaults are
# unchanged: ~/.crusorai/sessions.db.
_CHECKPOINT_DB = str(checkpoint_db_path())


class _LazySqliteConnection:
    """A sqlite3.Connection-shaped proxy that opens on first use.

    SqliteSaver stores ``conn`` and calls ``execute``/``executescript``/
    ``cursor``/``commit``. Forwarding through ``__getattr__`` keeps that
    contract while deferring the file creation, parent mkdir and PRAGMAs to
    the first actual checkpoint operation.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _get(self) -> sqlite3.Connection:
        if self._conn is None:
            with self._lock:
                if self._conn is None:
                    path = Path(self._db_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(self._db_path, check_same_thread=False)
                    # Windows field failure (2026-09-04): the turn died BETWEEN
                    # finalize's return and the stream generator ending - the
                    # state commit / post-loop checkpoint reads. Default
                    # rollback-journal SQLite lets one writer EXCLUDE all
                    # readers during a commit and vice versa; with several
                    # threads on this one shared connection that is a stall
                    # class, not a crash. WAL makes readers and the writer
                    # concurrent; an explicit busy_timeout turns any residual
                    # contention into a bounded wait instead of an instant
                    # error.
                    try:
                        conn.execute("PRAGMA journal_mode=WAL")
                        conn.execute("PRAGMA busy_timeout=10000")
                        conn.execute("PRAGMA synchronous=NORMAL")
                    except Exception:
                        pass  # an unhardened checkpointer still works
                    self._conn = conn
        return self._conn

    def __getattr__(self, name: str):
        return getattr(self._get(), name)

    def __enter__(self):
        return self._get().__enter__()

    def __exit__(self, *args):
        return self._get().__exit__(*args)


_checkpoint_conn = _LazySqliteConnection(_CHECKPOINT_DB)
memory = SqliteSaver(_checkpoint_conn)

graph = builder.compile(
    checkpointer=memory
)

```

### 3.3 `_prior_checkpoint_count()`
```python
    @staticmethod
    def _prior_checkpoint_count(sid: str, db_path: str | None = None) -> int | None:
        """Count durable checkpoints for a thread id (read-only, no engine
        import). None = unknown (db unreadable/schema changed) — never
        reported as 0 when unknown.

        The checkpoint rows live wherever the graph's ``SqliteSaver`` writes
        them, so the default is the graph's captured ``_CHECKPOINT_DB`` when
        that module is already imported, otherwise ``checkpoint_db_path()`` —
        the exact same environment contract (``CRUSORAI_CHECKPOINT_DB`` >
        ``CRUSORAI_CHECKPOINT_HOME`` > shared sessions DB > ``CRUSORAI_HOME``
        > ``~/.crusorai/sessions.db``). An explicit ``db_path`` is only used by
        direct callers/tests; there is no silent fallback to the developer's
        home database when an override is configured.
        """
        if db_path is None:
            # Prefer the already-imported graph's captured path: that is the
            # exact file its SqliteSaver writes, even if the environment
            # changed after import. Otherwise resolve the same contract
            # without paying for an engine import.
            graph_module = sys.modules.get("src.graphs.chat_graph")
            captured = getattr(graph_module, "_CHECKPOINT_DB", None) if graph_module else None
            if captured:
                db_path = str(captured)
            else:
                from src.runtime.app_paths import checkpoint_db_path

                db_path = str(checkpoint_db_path())
        db = db_path
        if not os.path.exists(db):
            return 0
        try:
            import sqlite3

            from src.runtime.app_paths import sqlite_readonly_uri

            conn = sqlite3.connect(sqlite_readonly_uri(db), uri=True, timeout=2.0)
            try:
                table = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
                ).fetchone()
                if table is None:
                    # A sessions.db without the checkpointer table was minted
                    # by the session/subagent stores before any turn ran —
                    # that is honestly zero checkpoints, not unknown.
                    return 0
                row = conn.execute(
                    "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (sid,)
                ).fetchone()
                return int(row[0])
            finally:
                conn.close()
```

### 3.4 `_drop_checkpoints()`
```python
def _drop_checkpoints(thread_id: str) -> None:
    """Remove this run's checkpoint rows from the SAME database the graph uses.

    The graph resolves its ``SqliteSaver`` path from the environment
    (``CRUSORAI_CHECKPOINT_DB`` / ``CRUSORAI_CHECKPOINT_HOME`` /
    ``CRUSORAI_SESSIONS_DB`` / ``CRUSORAI_HOME``); pytest's conftest pins that
    to a per-run temp root. Never touch the developer's real
    ``~/.crusorai/sessions.db``, even if this module is imported without the
    fixture.
    """
    try:
        import sqlite3
        from pathlib import Path

        from src.graphs import chat_graph

        db = Path(chat_graph._CHECKPOINT_DB).resolve()
        real = (Path.home() / ".crusorai" / "sessions.db").resolve()
        if db == real or not db.exists():
            return
        saver = getattr(chat_graph, "memory", None)
        if saver is not None and hasattr(saver, "delete_thread"):
            try:
                saver.delete_thread(thread_id)
                return
            except Exception:
                pass  # fall back to the isolated file below
        conn = sqlite3.connect(str(db), timeout=5)
        try:
            conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # test hygiene only — never fail the test over it

```

### 3.5 SQLite URI construction and read-only enforcement
- R3 helper: `Path(db_path).resolve().as_uri() + "?mode=ro"`.
- The bridge calls `sqlite3.connect(sqlite_readonly_uri(db), uri=True, timeout=2.0)`.
- `Path.as_uri()` percent-encodes `#` as `%23`, `?` as `%3F`, `%` as `%25`, spaces as `%20`, and Unicode as UTF-8 percent escapes.
- `mode=ro` is preserved; a write attempt raises `sqlite3.OperationalError: attempt to write a readonly database`.
- Regression: `test_readonly_uri_rejects_writes_and_keeps_database_hash` in `src/tests/test_checkpoint_uri_isolation.py` (complete file below).

## 4. Actual implementation diffs and complete new files


### 4.1 `src/runtime/app_paths.py`

**Status:** modified tracked  
**Attribution:** P1-A + R3

```diff
diff --git a/src/runtime/app_paths.py b/src/runtime/app_paths.py
index 2137510b..ac56f606 100644
--- a/src/runtime/app_paths.py
+++ b/src/runtime/app_paths.py
@@ -27,9 +27,68 @@ def app_data_root(workspace: str | Path) -> Path:
 
 
 def workspace_app_data_root(workspace: str | Path) -> Path:
-    """Deterministic per-workspace root under the application home."""
+    """Deterministic per-workspace root under the application home.
+
+    ``CRUSORAI_HOME`` relocates the application home (packaging/tests) while
+    keeping the per-workspace subtree, so isolated runs do not write under the
+    developer's real ``~/.crusorai/workspaces``.
+    """
     digest = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:16]
-    return Path.home() / ".crusorai" / "workspaces" / digest
+    home = os.environ.get("CRUSORAI_HOME", "").strip()
+    base = Path(home).expanduser() if home else Path.home() / ".crusorai"
+    return base / "workspaces" / digest
+
+
+def session_db_path() -> Path:
+    """Resolve the canonical conversation database (sessions + checkpoints).
+
+    Precedence matches the durable session store:
+    ``CRUSORAI_SESSIONS_DB`` > ``CRUSORAI_SESSIONS_DB_PATH`` >
+    ``CRUSORAI_HOME`` > ``~/.crusorai/sessions.db``.
+    """
+    explicit = os.environ.get("CRUSORAI_SESSIONS_DB") or os.environ.get(
+        "CRUSORAI_SESSIONS_DB_PATH"
+    )
+    if explicit:
+        return Path(explicit).expanduser()
+    home = os.environ.get("CRUSORAI_HOME", "").strip()
+    if home:
+        return Path(home).expanduser() / "sessions.db"
+    return Path.home() / ".crusorai" / "sessions.db"
+
+
+def checkpoint_db_path() -> Path:
+    """Resolve the LangGraph checkpoint database path.
+
+    A checkpoint-specific override wins over the shared conversation DB so a
+    test (or an isolated run) can relocate checkpoints without moving session
+    rows or any other runtime state:
+
+    1. ``CRUSORAI_CHECKPOINT_DB`` — exact file path.
+    2. ``CRUSORAI_CHECKPOINT_HOME`` — directory; ``<home>/sessions.db``.
+    3. ``session_db_path()`` — the normal shared database.
+
+    Defaults are unchanged: with no environment overrides this returns
+    ``~/.crusorai/sessions.db``.
+    """
+    explicit = os.environ.get("CRUSORAI_CHECKPOINT_DB", "").strip()
+    if explicit:
+        return Path(explicit).expanduser()
+    home = os.environ.get("CRUSORAI_CHECKPOINT_HOME", "").strip()
+    if home:
+        return Path(home).expanduser() / "sessions.db"
+    return session_db_path()
+
+
+def sqlite_readonly_uri(db_path: str | Path) -> str:
+    """Return an absolute, percent-encoded SQLite URI in read-only mode.
+
+    ``Path.as_uri()`` encodes legal filename characters that SQLite would
+    otherwise treat as URI delimiters — ``#`` (fragment), ``?`` (query),
+    ``%`` (escape), spaces and non-ASCII text — so the connection can never
+    silently resolve to a different database.
+    """
+    return f"{Path(db_path).resolve().as_uri()}?mode=ro"
 
 
 def activate_workspace_app_data(workspace: str | Path):
```

### 4.2 `src/bridge/__main__.py`

**Status:** modified tracked  
**Attribution:** R2 + R3 (mixed with pre-existing work)

> Only the `_prior_checkpoint_count` hunk belongs to R2/R3. The journal/card/transcript hunks are pre-existing user work; they are included so the reviewer can see the complete file diff.

```diff
diff --git a/src/bridge/__main__.py b/src/bridge/__main__.py
index a26d203e..4482c750 100644
--- a/src/bridge/__main__.py
+++ b/src/bridge/__main__.py
@@ -13,6 +13,7 @@ import re
 import queue
 import sys
 import threading
+import hashlib
 from pathlib import Path
 
 os.environ["OPENBLAS_NUM_THREADS"] = "1"
@@ -52,6 +53,17 @@ from src.runtime.identity import TurnIdentity, normalize_id
 
 ENGINE_VERSION = "0.2.0-runtime"
 
+# Durable terminal lifecycle rows (written by TurnEvidenceRecorder) are the
+# only authority on how a restored turn ended. The renderer must never infer
+# success from the absence of a row (B-LIVE-002).
+_TERMINAL_TURN_OUTCOMES = {
+    "turn.completed": "completed",
+    "turn.cancelled": "cancelled",
+    "turn.failed": "failed",
+    "turn.interrupted": "incomplete",
+    "turn.watchdog": "incomplete",
+}
+
 # A session is only ever bound to a real project folder. The renderer disables
 # prompt submission without one; the bridge enforces the same contract so no
 # client can silently run against ".", the engine root, or the bundled app dir.
@@ -165,13 +177,39 @@ class BridgeServer:
     def _prior_checkpoint_count(sid: str, db_path: str | None = None) -> int | None:
         """Count durable checkpoints for a thread id (read-only, no engine
         import). None = unknown (db unreadable/schema changed) — never
-        reported as 0 when unknown."""
-        db = db_path or os.path.join(os.path.expanduser("~"), ".crusorai", "sessions.db")
+        reported as 0 when unknown.
+
+        The checkpoint rows live wherever the graph's ``SqliteSaver`` writes
+        them, so the default is the graph's captured ``_CHECKPOINT_DB`` when
+        that module is already imported, otherwise ``checkpoint_db_path()`` —
+        the exact same environment contract (``CRUSORAI_CHECKPOINT_DB`` >
+        ``CRUSORAI_CHECKPOINT_HOME`` > shared sessions DB > ``CRUSORAI_HOME``
+        > ``~/.crusorai/sessions.db``). An explicit ``db_path`` is only used by
+        direct callers/tests; there is no silent fallback to the developer's
+        home database when an override is configured.
+        """
+        if db_path is None:
+            # Prefer the already-imported graph's captured path: that is the
+            # exact file its SqliteSaver writes, even if the environment
+            # changed after import. Otherwise resolve the same contract
+            # without paying for an engine import.
+            graph_module = sys.modules.get("src.graphs.chat_graph")
+            captured = getattr(graph_module, "_CHECKPOINT_DB", None) if graph_module else None
+            if captured:
+                db_path = str(captured)
+            else:
+                from src.runtime.app_paths import checkpoint_db_path
+
+                db_path = str(checkpoint_db_path())
+        db = db_path
         if not os.path.exists(db):
             return 0
         try:
             import sqlite3
-            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
+
+            from src.runtime.app_paths import sqlite_readonly_uri
+
+            conn = sqlite3.connect(sqlite_readonly_uri(db), uri=True, timeout=2.0)
             try:
                 table = conn.execute(
                     "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
@@ -213,8 +251,149 @@ class BridgeServer:
         )
         return {key: row.get(key) for key in safe if key in row}
 
+    @staticmethod
+    def _journal_events(journal: object, session_id: str, *, page: int = 2000) -> list[dict]:
+        """Every journal row for one session, paged (cards/turns are unbounded
+        by a single 2000-row window)."""
+        events: list[dict] = []
+        after = 0
+        while True:
+            batch = journal.list_events(session_id, after_seq=after, limit=page)  # type: ignore[attr-defined]
+            if not batch:
+                return events
+            events.extend(batch)
+            if len(batch) < page:
+                return events
+            next_after = int(batch[-1].get("seq") or 0)
+            if next_after <= after:
+                return events
+            after = next_after
+
+    @staticmethod
+    def _turn_request_rows(events: list[dict]) -> list[tuple[str, str]]:
+        """(request sha256, turn_id) for each turn.started journal row, in order."""
+        rows: list[tuple[str, str]] = []
+        for event in events:
+            if str(event.get("type") or "") != "turn.started":
+                continue
+            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
+            request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
+            digest = str(request.get("sha256") or "")
+            turn_id = str(event.get("turn_id") or "")
+            if turn_id:
+                # An empty digest is kept: a legacy journal with turn.started
+                # rows but no request hash can still use the ordinal fallback.
+                rows.append((digest, turn_id))
+        return rows
+
+    @staticmethod
+    def _turn_outcomes(events: list[dict]) -> dict[str, str]:
+        """turn_id -> durable terminal outcome for every turn the journal settled.
+
+        The journal enforces one terminal row per turn, so the first match wins;
+        a turn with no terminal row is deliberately absent (the client must treat
+        it as unknown, never as completed).
+        """
+        outcomes: dict[str, str] = {}
+        for event in events:
+            outcome = _TERMINAL_TURN_OUTCOMES.get(str(event.get("type") or ""))
+            turn_id = str(event.get("turn_id") or "")
+            if outcome and turn_id and turn_id not in outcomes:
+                outcomes[turn_id] = outcome
+        return outcomes
+
+    @staticmethod
+    def _assign_transcript_turn_ids(
+        projected: list[dict], turn_rows: list[tuple[str, str]],
+    ) -> None:
+        """Stamp each projected message with the turn that produced it.
+
+        Primary rule: the journal's turn.started request hash equals the hash
+        of the persisted human message, so a prompt's group is unambiguous even
+        when earlier turns failed or produced no assistant text. A user message
+        that matches no turn (a steer) inherits the open turn. Legacy journals
+        without request hashes fall back to ordinal association ONLY when the
+        number of user messages equals the number of turns (never a "newest
+        turn" guess).
+        """
+        if not projected or not turn_rows:
+            return
+        by_hash: dict[str, list[str]] = {}
+        for digest, turn_id in turn_rows:
+            by_hash.setdefault(digest, []).append(turn_id)
+
+        used: set[str] = set()
+        current = ""
+        matched_any = False
+        for entry in projected:
+            if entry.get("role") == "user":
+                content = str(entry.get("content") or "")
+                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
+                candidate = next(
+                    (turn_id for turn_id in by_hash.get(digest, []) if turn_id not in used),
+                    "",
+                )
+                if candidate:
+                    current = candidate
+                    used.add(candidate)
+                    matched_any = True
+            if current:
+                entry["turn_id"] = current
+        if matched_any:
+            return
+
+        users = [entry for entry in projected if entry.get("role") == "user"]
+        turn_ids = [turn_id for _digest, turn_id in turn_rows]
+        if len(users) != len(turn_ids) or len(set(turn_ids)) != len(turn_ids):
+            return
+        current = ""
+        index = 0
+        for entry in projected:
+            if entry.get("role") == "user":
+                current = turn_ids[index]
+                index += 1
+                entry["turn_id"] = current
+            elif current:
+                entry["turn_id"] = current
+
+    @staticmethod
+    def _latest_agent_cards(events: list[dict], fallback_session: str) -> list[dict]:
+        """Latest card per (session, turn, card id), in first-arrival order.
+
+        Keying by card id alone lets a turn with the same id replace another
+        turn's card; the journal's full identity prevents that. Replaying the
+        same identity updates in place (no duplicate).
+        """
+        from src.bridge.agent_cards import normalize_card
+
+        latest: dict[tuple[str, str, str], dict] = {}
+        for event in events:
+            if str(event.get("type") or "") != "agent_card":
+                continue
+            raw = (event.get("payload") or {}).get("card")
+            card = normalize_card(
+                raw,
+                session_id=str(event.get("session_id") or fallback_session),
+                turn_id=str(event.get("turn_id") or ""),
+            )
+            if card is None:
+                continue
+            card_session = str(card.get("session_id") or "")
+            if card_session and fallback_session and card_session != fallback_session:
+                # The journal query is session-scoped; this guard makes the
+                # projection safe even if a foreign row leaks into the batch.
+                continue
+            key = (
+                str(card.get("session_id") or ""),
+                str(card.get("turn_id") or ""),
+                str(card.get("card_id") or ""),
+            )
+            latest[key] = card
+        return list(latest.values())
+
     def _transcript_messages(
         self, sid: str, *, limit: int, offset: int, order: str,
+        turn_rows: list[tuple[str, str]] | None = None,
     ) -> tuple[list[dict], dict]:
         """Paged transcript from the checkpointer (Hermes messages paging).
 
@@ -354,6 +533,10 @@ class BridgeServer:
             if name:
                 entry["tool_name"] = str(name)
             projected.append(entry)
+        # Turn ownership is assigned on the FULL list (before paging) so a
+        # page boundary can never split a turn's messages from its prompt.
+        if turn_rows:
+            self._assign_transcript_turn_ids(projected, turn_rows)
         total = len(projected)
         if order == "latest":
             start = max(0, total - offset - limit)
@@ -612,9 +795,38 @@ class BridgeServer:
                 print(f"[bridge][recovery] shutdown sweep failed for {workspace}: {exc!r}",
                       file=sys.stderr, flush=True)
 
+    def _journal_agent_card(self, card: dict, identity: TurnIdentity) -> None:
+        """Persist one painted card so session replay can restore it."""
+        try:
+            from src.runtime.factory import get_runtime_services
+
+            get_runtime_services().journal.append(
+                "agent_card",
+                {"card": card},
+                session_id=str(card.get("session_id") or identity.session_id),
+                turn_id=str(card.get("turn_id") or identity.turn_id),
+                workspace_id=str(identity.workspace_id or ""),
+            )
+        except Exception:
+            pass
+
     def _emit_companion_cards(self, frame: dict, identity: TurnIdentity) -> None:
         """Project a canonical frame onto typed UI cards (presentation only)."""
         try:
+            if str(frame.get("type") or "") == "agent_card":
+                # A producer already built this card (engineering progress).
+                # It needs the same durable row the projected cards get,
+                # otherwise the card is live-only and replay loses it.
+                card = frame.get("card")
+                if frame.get("ephemeral") is True:
+                    # In-flight generation heartbeats are live-only: the stage
+                    # reporter's snapshots are the replayable record, and
+                    # journaling every heartbeat would bloat the journal with
+                    # rows that must never win a replay.
+                    return
+                if isinstance(card, dict):
+                    self._journal_agent_card(card, identity)
+                return
             from src.bridge.agent_cards import card_frames_for_frame
 
             for card in card_frames_for_frame(frame, turn_id=identity.turn_id):
@@ -625,18 +837,7 @@ class BridgeServer:
                     "card": card,
                 }
                 self.emit(payload)
-                try:
-                    from src.runtime.factory import get_runtime_services
-
-                    get_runtime_services().journal.append(
-                        "agent_card",
-                        {"card": card},
-                        session_id=str(card.get("session_id") or identity.session_id),
-                        turn_id=str(card.get("turn_id") or identity.turn_id),
-                        workspace_id=str(identity.workspace_id or ""),
-                    )
-                except Exception:
-                    pass
+                self._journal_agent_card(card, identity)
         except Exception as exc:  # noqa: BLE001 - cards never block a turn
             print(
                 f"[CrusorAI bridge] companion card skipped: {type(exc).__name__}: {exc}",
@@ -1834,32 +2035,31 @@ class BridgeServer:
             except (TypeError, ValueError):
                 offset = 0
             order = str(frame.get("order") or "latest").strip().lower()
-            messages, pagination = self._transcript_messages(
-                tip, limit=limit, offset=offset, order=order)
-            cards: list[dict] = []
+            events: list[dict] = []
             try:
                 from src.runtime.factory import get_runtime_services
-                from src.bridge.agent_cards import normalize_card
 
-                latest: dict[str, dict] = {}
-                for event in get_runtime_services().journal.list_events(tip):
-                    if str(event.get("type") or "") != "agent_card":
-                        continue
-                    raw = (event.get("payload") or {}).get("card")
-                    card = normalize_card(
-                        raw,
-                        session_id=str(event.get("session_id") or tip),
-                        turn_id=str(event.get("turn_id") or ""),
-                    )
-                    if card is not None:
-                        latest[card["card_id"]] = card
-                cards = list(latest.values())
+                events = self._journal_events(get_runtime_services().journal, tip)
+            except Exception:
+                events = []
+            messages, pagination = self._transcript_messages(
+                tip, limit=limit, offset=offset, order=order,
+                turn_rows=self._turn_request_rows(events),
+            )
+            cards: list[dict] = []
+            try:
+                cards = self._latest_agent_cards(events, tip)
             except Exception:
                 cards = []
+            try:
+                turn_outcomes = self._turn_outcomes(events)
+            except Exception:
+                turn_outcomes = {}
             self.emit({
                 "type": "session_messages", "session_id": tip,
                 "requested_session_id": sid, "messages": messages,
                 "pagination": pagination, "cards": cards,
+                "turn_outcomes": turn_outcomes,
             })
             return True
         if kind == "session_delete":
```

### 4.3 `src/runtime/session_store.py`

**Status:** modified tracked  
**Attribution:** P1-A

```diff
diff --git a/src/runtime/session_store.py b/src/runtime/session_store.py
index 709e4efb..3a02c552 100644
--- a/src/runtime/session_store.py
+++ b/src/runtime/session_store.py
@@ -43,16 +43,12 @@ import time
 from pathlib import Path
 from typing import Any, Literal, Optional
 
+from src.runtime.app_paths import session_db_path
+
 # Same env resolution as the subagent store so tests and containers can
 # redirect the whole conversation state with one variable.
 def _default_db_path() -> Path:
-    custom = os.getenv("CRUSORAI_SESSIONS_DB") or os.getenv("CRUSORAI_SESSIONS_DB_PATH")
-    if custom:
-        return Path(custom).expanduser()
-    home_override = os.getenv("CRUSORAI_HOME")
-    if home_override:
-        return Path(home_override).expanduser() / "sessions.db"
-    return Path.home() / ".crusorai" / "sessions.db"
+    return session_db_path()
 
 
 _TITLE_MAX_CHARS = 200
```

### 4.4 `src/graphs/chat_graph.py`

**Status:** modified tracked  
**Attribution:** P1-A checkpoint hunk + pre-existing work

> Only the checkpoint hunk near `_CHECKPOINT_DB` / `_LazySqliteConnection` belongs to P1-A. The engineering-progress/orchestration hunks around lines 5271-5432 are pre-existing user work.

```diff
diff --git a/src/graphs/chat_graph.py b/src/graphs/chat_graph.py
index 3cb2b437..ccafaa22 100644
--- a/src/graphs/chat_graph.py
+++ b/src/graphs/chat_graph.py
@@ -1,8 +1,9 @@
 
-from src.runtime.app_paths import app_data_root
+from src.runtime.app_paths import app_data_root, checkpoint_db_path
 import json
 import os
 import re
+from pathlib import Path
 
 import contextvars
 import sqlite3
@@ -5271,6 +5272,7 @@ def engineering_task_node(state: AgentState, config: RunnableConfig):
         ExecutionLimits,
     )
     from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
+    from src.orchestration.progress_events import EngineeringProgressReporter
     from src.runtime.turn_control import turn_controls
 
     configurable = (config or {}).get("configurable", {}) or {}
@@ -5349,6 +5351,42 @@ def engineering_task_node(state: AgentState, config: RunnableConfig):
             "workspace": workspace,
         }
 
+    # Live progress: the orchestrator's stage snapshots are projected onto the
+    # existing activity card and plan event (same bus, same cards, same
+    # renderer). Stages never impersonate tool/file/test/verification/cost
+    # events -- those keep their own authoritative sources.
+    progress = EngineeringProgressReporter(
+        session_id=thread_id,
+        turn_id=turn_id,
+        cancelled=_cancelled,
+    )
+
+    # In-flight generation facts (elapsed time, characters received) ride the
+    # SAME activity card while the provider is streaming. They are ephemeral:
+    # the bridge must not journal a heartbeat as a durable card, because the
+    # stage reporter's snapshots are the replayable record.
+    def _generation_activity(update) -> None:
+        if update.phase not in {"started", "delta", "heartbeat"}:
+            return
+        try:
+            # The node is generating: mark it in the plan so the plan card and
+            # the activity card agree. Only at "started" — this is a status
+            # annotation of the last real snapshot, not a new stage.
+            if update.phase == "started" and getattr(update, "node_id", ""):
+                progress.mark_generating(update.node_id)
+            from src.orchestration.generation_progress import generation_card
+
+            card = generation_card(update, session_id=thread_id, turn_id=turn_id)
+            event_bus.emit("agent.card", {
+                "card": card,
+                "session_id": thread_id,
+                "thread_id": thread_id,
+                "turn_id": turn_id,
+                "ephemeral": True,
+            })
+        except Exception:
+            pass
+
     task_id = f"turn_{turn_id}"
     max_dispatch_env = os.environ.get("CRUSORAI_ACCEPTANCE_MAX_DISPATCHES", "").strip()
     output_cap_env = os.environ.get("CRUSORAI_MAX_OUTPUT_TOKENS_PER_NODE", "").strip()
@@ -5381,7 +5419,11 @@ def engineering_task_node(state: AgentState, config: RunnableConfig):
             workspace_root=workspace,
             tenant_id="default_tenant",
             limits=limits,
-            storage_dir=str(app_data_root(workspace) / "orchestration"),
+            # Per-turn storage: the state machine, authoritative context and
+            # journal are task-scoped. A shared directory made the next turn
+            # load the previous turn's terminal state ("cannot move from
+            # COMPLETED to UNDERSTANDING") and its completed steps.
+            storage_dir=str(app_data_root(workspace) / "orchestration" / task_id),
             provider=configurable.get("provider"),
             model=configurable.get("model"),
             mock_mode=request.mock_mode,
@@ -5390,9 +5432,11 @@ def engineering_task_node(state: AgentState, config: RunnableConfig):
             session_id=thread_id,
             cancellation_checker=_cancelled,
             turn_id=turn_id,
+            generation_observer=_generation_activity,
         )
         delivery = orchestrator.run_task_request(
             request,
+            on_progress=progress,
             cancellation_checker=_cancelled,
         )
         payload = delivery.to_dict()
@@ -8224,24 +8268,66 @@ def get_context_engine(
 # so for a module-level saver we hold a direct connection instead.
 # check_same_thread=False is required: the dashboard server runs the graph
 # from worker threads, and sqlite connections are thread-bound by default.
-_CHECKPOINT_DB = os.path.join(os.path.expanduser("~"), ".crusorai", "sessions.db")
-os.makedirs(os.path.dirname(_CHECKPOINT_DB), exist_ok=True)
-_checkpoint_conn = sqlite3.connect(_CHECKPOINT_DB, check_same_thread=False)
-# Windows field failure (2026-09-04): the turn died BETWEEN finalize's return
-# and the stream generator ending - the state commit / post-loop checkpoint
-# reads. Default rollback-journal SQLite lets one writer EXCLUDE all readers
-# during a commit and vice versa; with several threads on this one shared
-# connection that is a stall class, not a crash. WAL makes readers and the
-# writer concurrent; an explicit busy_timeout turns any residual contention
-# into a bounded wait instead of an instant error.
-try:
-    _checkpoint_conn.execute("PRAGMA journal_mode=WAL")
-    _checkpoint_conn.execute("PRAGMA busy_timeout=10000")
-    _checkpoint_conn.execute("PRAGMA synchronous=NORMAL")
-except Exception:
-    pass  # an unhardened checkpointer still works; never block graph compile
+# The connection is LAZY: importing this module must not create or open a
+# database. Tests (and isolated runs) set CRUSORAI_CHECKPOINT_DB /
+# CRUSORAI_CHECKPOINT_HOME / CRUSORAI_SESSIONS_DB / CRUSORAI_HOME before the
+# import; the first checkpoint read/write opens that path. Defaults are
+# unchanged: ~/.crusorai/sessions.db.
+_CHECKPOINT_DB = str(checkpoint_db_path())
+
+
+class _LazySqliteConnection:
+    """A sqlite3.Connection-shaped proxy that opens on first use.
+
+    SqliteSaver stores ``conn`` and calls ``execute``/``executescript``/
+    ``cursor``/``commit``. Forwarding through ``__getattr__`` keeps that
+    contract while deferring the file creation, parent mkdir and PRAGMAs to
+    the first actual checkpoint operation.
+    """
+
+    def __init__(self, db_path: str) -> None:
+        self._db_path = db_path
+        self._conn: sqlite3.Connection | None = None
+        self._lock = threading.Lock()
+
+    def _get(self) -> sqlite3.Connection:
+        if self._conn is None:
+            with self._lock:
+                if self._conn is None:
+                    path = Path(self._db_path)
+                    path.parent.mkdir(parents=True, exist_ok=True)
+                    conn = sqlite3.connect(self._db_path, check_same_thread=False)
+                    # Windows field failure (2026-09-04): the turn died BETWEEN
+                    # finalize's return and the stream generator ending - the
+                    # state commit / post-loop checkpoint reads. Default
+                    # rollback-journal SQLite lets one writer EXCLUDE all
+                    # readers during a commit and vice versa; with several
+                    # threads on this one shared connection that is a stall
+                    # class, not a crash. WAL makes readers and the writer
+                    # concurrent; an explicit busy_timeout turns any residual
+                    # contention into a bounded wait instead of an instant
+                    # error.
+                    try:
+                        conn.execute("PRAGMA journal_mode=WAL")
+                        conn.execute("PRAGMA busy_timeout=10000")
+                        conn.execute("PRAGMA synchronous=NORMAL")
+                    except Exception:
+                        pass  # an unhardened checkpointer still works
+                    self._conn = conn
+        return self._conn
+
+    def __getattr__(self, name: str):
+        return getattr(self._get(), name)
+
+    def __enter__(self):
+        return self._get().__enter__()
+
+    def __exit__(self, *args):
+        return self._get().__exit__(*args)
+
+
+_checkpoint_conn = _LazySqliteConnection(_CHECKPOINT_DB)
 memory = SqliteSaver(_checkpoint_conn)
-memory.setup()
 
 graph = builder.compile(
     checkpointer=memory
```

### 4.5 `src/tests/conftest.py`

**Status:** modified tracked  
**Attribution:** P1-A

```diff
diff --git a/src/tests/conftest.py b/src/tests/conftest.py
index b54d2f7d..0e92a41c 100644
--- a/src/tests/conftest.py
+++ b/src/tests/conftest.py
@@ -17,9 +17,15 @@ guard. Delete entries from this list as each test is migrated.
 import os as _os
 import tempfile as _tempfile
 
-_os.environ.setdefault(
-    "CRUSORAI_CHECKPOINT_HOME",
-    _tempfile.mkdtemp(prefix="crusorai-test-checkpoints-"),
+_TEST_RUNTIME_ROOT = _tempfile.mkdtemp(prefix="crusorai-test-runtime-")
+_os.environ["CRUSORAI_HOME"] = _TEST_RUNTIME_ROOT
+_os.environ["CRUSORAI_CHECKPOINT_HOME"] = _TEST_RUNTIME_ROOT
+_os.environ.pop("CRUSORAI_CHECKPOINT_DB", None)
+# The durable session rows and the LangGraph checkpoints share one database in
+# production. Point BOTH at the throwaway root so an in-process `_run_turn`
+# cannot write `crusor_sessions` rows to the developer's real sessions.db.
+_os.environ["CRUSORAI_SESSIONS_DB"] = _os.path.join(
+    _TEST_RUNTIME_ROOT, "sessions.db"
 )
 
 # The engine starts the preview proxy the first time a session binds a workspace
```

### 4.6 `src/tests/test_checkpoint_isolation.py`

**Status:** untracked/new  
**Attribution:** P1-A + R2

```python
"""P1-A: checkpoint storage must be hermetic and lazy.

The graph checkpointer used to open ``~/.crusorai/sessions.db`` at import time
and ignore every test/home override. These tests pin the contract:

* path precedence: CRUSORAI_CHECKPOINT_DB > CRUSORAI_CHECKPOINT_HOME >
  CRUSORAI_SESSIONS_DB/_PATH > CRUSORAI_HOME > ~/.crusorai/sessions.db;
* importing the graph must not create or open a database;
* the first checkpoint operation creates the configured database only;
* real LangGraph checkpoint tables still exist (persistence is not disabled);
* the developer's real databases and all SQLite sidecars are byte-identical
  (full SHA-256 + size + mtime) before/after an isolated run;
* invalid checkpoint paths fail closed without a home fallback.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.runtime.app_paths import checkpoint_db_path, session_db_path

REPO = Path(__file__).resolve().parents[2]
_ENV_KEYS = (
    "CRUSORAI_CHECKPOINT_DB",
    "CRUSORAI_CHECKPOINT_HOME",
    "CRUSORAI_SESSIONS_DB",
    "CRUSORAI_SESSIONS_DB_PATH",
    "CRUSORAI_HOME",
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _clean_subprocess_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in _ENV_KEYS:
        env.pop(key, None)
    env.update(overrides)
    env["PYTHONPATH"] = str(REPO)
    env.setdefault("CRUSORAI_MEMORY", "off")
    return env


def _run_isolated(code: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO),
        env=_clean_subprocess_env(**env_overrides),
        text=True,
        capture_output=True,
        timeout=120,
    )


def _full_hash(path: Path) -> str:
    """Hash the complete file (not a sample) so sidecar content is covered."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Main databases + every SQLite sidecar named by the P1-A review contract.
_DB_FILES = (
    "sessions.db",
    "sessions.db-wal",
    "sessions.db-shm",
    "runtime_events.db",
    "runtime_events.db-wal",
    "runtime_events.db-shm",
    "verification.db",
    "verification.db-wal",
    "verification.db-shm",
)
# A rollback-journal file is absent while WAL is active; snapshot it too so an
# unexpected journal can never slip past the immutability check.
_JOURNAL_FILES = (
    "sessions.db-journal",
    "runtime_events.db-journal",
    "verification.db-journal",
)


# ---------------------------------------------------------------------------
# Path precedence
# ---------------------------------------------------------------------------
def test_explicit_checkpoint_db_wins(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CRUSORAI_CHECKPOINT_DB", str(tmp_path / "explicit.db"))
    monkeypatch.setenv("CRUSORAI_CHECKPOINT_HOME", str(tmp_path / "ckpt"))
    monkeypatch.setenv("CRUSORAI_SESSIONS_DB", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
    assert checkpoint_db_path() == tmp_path / "explicit.db"


def test_checkpoint_home_wins_over_sessions_db(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CRUSORAI_CHECKPOINT_HOME", str(tmp_path / "ckpt"))
    monkeypatch.setenv("CRUSORAI_SESSIONS_DB", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
    assert checkpoint_db_path() == tmp_path / "ckpt" / "sessions.db"


def test_sessions_db_override_is_used_without_checkpoint_override(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CRUSORAI_SESSIONS_DB", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
    assert checkpoint_db_path() == tmp_path / "sessions.db"


def test_app_home_override_is_used_without_sessions_override(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
    assert checkpoint_db_path() == tmp_path / "home" / "sessions.db"


def test_default_path_is_unchanged(monkeypatch):
    _clear_env(monkeypatch)
    expected = Path.home() / ".crusorai" / "sessions.db"
    assert checkpoint_db_path() == expected
    assert session_db_path() == expected


def test_session_db_path_keeps_existing_precedence(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
    assert session_db_path() == tmp_path / "home" / "sessions.db"
    monkeypatch.setenv("CRUSORAI_SESSIONS_DB", str(tmp_path / "custom.db"))
    assert session_db_path() == tmp_path / "custom.db"


# ---------------------------------------------------------------------------
# Import-time behaviour
# ---------------------------------------------------------------------------
def test_import_does_not_create_or_open_checkpoint_db(tmp_path):
    ckpt = tmp_path / "ckpt"
    home = tmp_path / "home"
    code = f"""
import pathlib
import src.graphs.chat_graph as g
p = pathlib.Path(g._CHECKPOINT_DB)
print(p)
print("exists", p.exists())
print("is_setup", g.memory.is_setup)
assert p == pathlib.Path({str(ckpt / 'sessions.db')!r}), p
assert not p.exists(), p
assert g.memory.is_setup is False, g.memory.is_setup
"""
    result = _run_isolated(
        code,
        CRUSORAI_CHECKPOINT_HOME=str(ckpt),
        CRUSORAI_HOME=str(home),
    )
    assert result.returncode == 0, result.stderr
    assert "exists False" in result.stdout
    assert "is_setup False" in result.stdout
    assert not (ckpt / "sessions.db").exists()


def test_checkpoint_home_override_creates_only_the_isolated_db(tmp_path):
    ckpt = tmp_path / "ckpt"
    home = tmp_path / "home"
    code = f"""
import pathlib, sqlite3
import src.graphs.chat_graph as g
p = pathlib.Path(g._CHECKPOINT_DB)
g.memory.setup()
print("db", p)
print("exists", p.exists())
con = sqlite3.connect(str(p))
tables = {{r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}}
con.close()
print("tables", sorted(tables))
assert p == pathlib.Path({str(ckpt / 'sessions.db')!r}), p
assert p.exists(), p
assert {{"checkpoints", "writes"}} <= tables, tables
assert not pathlib.Path({str(home / 'sessions.db')!r}).exists()
"""
    result = _run_isolated(
        code,
        CRUSORAI_CHECKPOINT_HOME=str(ckpt),
        CRUSORAI_HOME=str(home),
    )
    assert result.returncode == 0, result.stderr
    assert "exists True" in result.stdout
    assert "checkpoints" in result.stdout and "writes" in result.stdout


def test_sessions_db_override_names_the_checkpoint_file(tmp_path):
    db = tmp_path / "custom-sessions.db"
    code = f"""
import pathlib
import src.graphs.chat_graph as g
p = pathlib.Path(g._CHECKPOINT_DB)
print(p)
assert p == pathlib.Path({str(db)!r}), p
"""
    result = _run_isolated(
        code,
        CRUSORAI_SESSIONS_DB=str(db),
        CRUSORAI_HOME=str(tmp_path / "home"),
    )
    assert result.returncode == 0, result.stderr
    assert str(db) in result.stdout


# ---------------------------------------------------------------------------
# Actual checkpoint storage still works
# ---------------------------------------------------------------------------
def test_lazy_connection_defers_file_creation(tmp_path):
    from src.graphs.chat_graph import _LazySqliteConnection

    db = tmp_path / "lazy.db"
    conn = _LazySqliteConnection(str(db))
    assert not db.exists()
    assert conn.execute("SELECT 1").fetchone() == (1,)
    assert db.exists()


def test_invalid_checkpoint_path_directory_target_fails_closed(tmp_path):
    """A path that is an existing directory is not silently replaced."""
    from src.graphs.chat_graph import _LazySqliteConnection

    target = tmp_path / "as-directory"
    target.mkdir()
    conn = _LazySqliteConnection(str(target))
    with pytest.raises((sqlite3.OperationalError, OSError)):
        conn.execute("SELECT 1")
    assert target.is_dir()
    # No sibling database was invented as a fallback.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["as-directory"]


def test_invalid_checkpoint_path_parent_is_a_file_fails_closed(tmp_path):
    """A file where a parent directory is required fails closed."""
    from src.graphs.chat_graph import _LazySqliteConnection

    parent = tmp_path / "parent-file"
    parent.write_text("not a directory", encoding="utf-8")
    target = parent / "sessions.db"
    conn = _LazySqliteConnection(str(target))
    with pytest.raises((FileExistsError, NotADirectoryError, OSError)):
        conn.execute("SELECT 1")
    assert parent.is_file()
    assert not target.exists()


def test_nested_missing_parent_is_created_lazily(tmp_path):
    """A writable nested path is created on first use, not at construction."""
    from src.graphs.chat_graph import _LazySqliteConnection

    db = tmp_path / "one" / "two" / "three" / "sessions.db"
    conn = _LazySqliteConnection(str(db))
    assert not db.parent.exists()
    assert conn.execute("SELECT 1").fetchone() == (1,)
    assert db.exists()
    assert db.parent.is_dir()


def test_writable_custom_checkpoint_location_is_used(tmp_path):
    """CRUSORAI_CHECKPOINT_DB can point at a fresh nested directory."""
    ckpt = tmp_path / "custom" / "nested" / "sessions.db"
    code = f"""
import pathlib
import src.graphs.chat_graph as g
g.memory.setup()
p = pathlib.Path(g._CHECKPOINT_DB)
print(p)
assert p == pathlib.Path({str(ckpt)!r}), p
assert p.exists(), p
"""
    result = _run_isolated(
        code,
        CRUSORAI_CHECKPOINT_DB=str(ckpt),
        CRUSORAI_HOME=str(tmp_path / "home"),
    )
    assert result.returncode == 0, result.stderr
    assert ckpt.exists()


def test_invalid_checkpoint_location_fails_closed_without_home_fallback(tmp_path):
    """An unusable override must fail; it must never fall back to the home DB."""
    bad = tmp_path / "not-a-database"
    bad.mkdir()
    home = tmp_path / "home"
    before = _snapshot_real_databases()
    code = """
import src.graphs.chat_graph as g
g.memory.setup()
"""
    result = _run_isolated(
        code,
        CRUSORAI_CHECKPOINT_DB=str(bad),
        CRUSORAI_HOME=str(home),
    )
    assert result.returncode != 0
    assert "OperationalError" in result.stderr or "unable to open" in result.stderr
    assert not (home / "sessions.db").exists()
    after = _snapshot_real_databases()
    for name in before:
        assert after[name] == before[name], (
            f"real database/sidecar {name} changed after a failed override: "
            f"{before[name]} -> {after[name]}"
        )


def test_snapshot_treats_previously_absent_sidecars_as_absent(tmp_path):
    """Absent sidecars are tracked explicitly, so a later creation is visible."""
    missing = tmp_path / "never-created.db-wal"
    assert _db_snapshot(missing) == {"exists": False}
    missing.write_bytes(b"")
    snapshot = _db_snapshot(missing)
    assert snapshot["exists"] is True
    assert snapshot["size"] == 0


def test_sqlite_saver_setup_and_read_write_tables(tmp_path):
    from langgraph.checkpoint.sqlite import SqliteSaver

    from src.graphs.chat_graph import _LazySqliteConnection

    db = tmp_path / "saver.db"
    saver = SqliteSaver(_LazySqliteConnection(str(db)))
    saver.setup()
    with sqlite3.connect(str(db)) as con:
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"checkpoints", "writes"} <= tables


def test_checkpoint_survives_a_process_restart_in_isolated_storage(tmp_path):
    ckpt = tmp_path / "ckpt"
    write_code = """
import src.graphs.chat_graph as g
cfg = {"configurable": {"thread_id": "restart-probe"}}
g.graph.update_state(cfg, {"turn_receipt": {"probe": 1}})
print(g._CHECKPOINT_DB)
"""
    written = _run_isolated(
        write_code,
        CRUSORAI_CHECKPOINT_HOME=str(ckpt),
        CRUSORAI_HOME=str(tmp_path / "home"),
    )
    assert written.returncode == 0, written.stderr
    assert (ckpt / "sessions.db").exists()

    read_code = """
import src.graphs.chat_graph as g
cfg = {"configurable": {"thread_id": "restart-probe"}}
state = g.graph.get_state(cfg)
print(state.values)
assert state.values.get("turn_receipt") == {"probe": 1}, state.values
"""
    read = _run_isolated(
        read_code,
        CRUSORAI_CHECKPOINT_HOME=str(ckpt),
        CRUSORAI_HOME=str(tmp_path / "home"),
    )
    assert read.returncode == 0, read.stderr
    assert "probe" in read.stdout


# ---------------------------------------------------------------------------
# The fixture and the real user database
# ---------------------------------------------------------------------------
def test_fixture_checkpoint_home_is_isolated():
    configured = os.environ.get("CRUSORAI_CHECKPOINT_HOME", "").strip()
    assert configured, "conftest must set CRUSORAI_CHECKPOINT_HOME"
    import src.graphs.chat_graph as chat_graph

    path = Path(chat_graph._CHECKPOINT_DB).resolve()
    real = (Path.home() / ".crusorai" / "sessions.db").resolve()
    assert path != real
    assert path.is_relative_to(Path(configured).resolve())


def test_fixture_sessions_db_and_checkpoint_share_the_isolated_root():
    configured_home = Path(os.environ["CRUSORAI_CHECKPOINT_HOME"]).resolve()
    configured_db = Path(os.environ["CRUSORAI_SESSIONS_DB"]).resolve()
    real = (Path.home() / ".crusorai" / "sessions.db").resolve()
    assert configured_db != real
    assert configured_db.parent == configured_home
    assert session_db_path().resolve() == configured_db
    assert checkpoint_db_path().resolve() == configured_db
    from src.runtime.session_store import get_session_store

    store = get_session_store()
    assert Path(store.db_path).resolve() == configured_db
    from src.runtime.app_paths import workspace_app_data_root

    isolated_workspace_root = workspace_app_data_root("/any/workspace").resolve()
    assert isolated_workspace_root.is_relative_to(
        Path(os.environ["CRUSORAI_HOME"]).resolve()
    )
    assert isolated_workspace_root != (
        Path.home() / ".crusorai" / "workspaces"
    ).resolve()


def _db_snapshot(path: Path) -> dict:
    """Existence + size + mtime + full SHA-256 (absent files stay absent)."""
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _full_hash(path),
    }


def _snapshot_real_databases() -> dict[str, dict]:
    real_dir = Path.home() / ".crusorai"
    return {
        name: _db_snapshot(real_dir / name)
        for name in (*_DB_FILES, *_JOURNAL_FILES)
    }


def test_real_user_database_is_not_modified_by_an_isolated_run(tmp_path):
    before = _snapshot_real_databases()
    if not before["sessions.db"].get("exists"):
        pytest.skip("no developer database on this host")

    ckpt = tmp_path / "ckpt"
    code = """
import pathlib
import src.graphs.chat_graph as g
g.memory.setup()
from src.runtime.factory import get_runtime_services
services = get_runtime_services()
from src.runtime.session_store import get_session_store
store = get_session_store()
store.create_session("isolation-probe", str(pathlib.Path.cwd()), title="probe")
print(g._CHECKPOINT_DB)
print(store.db_path)
print(services.journal.path)
print(services.verification.path)
"""
    result = _run_isolated(
        code,
        CRUSORAI_CHECKPOINT_HOME=str(ckpt),
        CRUSORAI_HOME=str(tmp_path / "home"),
    )
    assert result.returncode == 0, result.stderr
    assert (ckpt / "sessions.db").exists()
    assert (tmp_path / "home" / "sessions.db").exists()
    assert (tmp_path / "home" / "runtime_events.db").exists()
    assert (tmp_path / "home" / "verification.db").exists()

    after = _snapshot_real_databases()
    for name in before:
        assert after[name] == before[name], (
            f"real database/sidecar {name} changed during an isolated run: "
            f"{before[name]} -> {after[name]}"
        )


def test_otel_cleanup_targets_the_isolated_db_and_never_the_real_db():
    """B-2: test hygiene deletes from the graph's resolved DB, not home."""
    from src.graphs import chat_graph
    from src.tests.test_otel_tracing import _drop_checkpoints

    configured = Path(os.environ["CRUSORAI_CHECKPOINT_HOME"]).resolve()
    db = Path(chat_graph._CHECKPOINT_DB).resolve()
    real = (Path.home() / ".crusorai" / "sessions.db").resolve()
    assert db != real
    assert db.is_relative_to(configured)

    before = _snapshot_real_databases()
    chat_graph.memory.setup()
    thread = "p1a-b2-cleanup-probe"
    with sqlite3.connect(str(db)) as con:
        con.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread,))
        con.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, "
            "parent_checkpoint_id, type, checkpoint, metadata) "
            "VALUES (?, '', '1', NULL, NULL, NULL, NULL)",
            (thread,),
        )
        con.commit()

    _drop_checkpoints(thread)

    with sqlite3.connect(str(db)) as con:
        remaining = con.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (thread,)
        ).fetchone()[0]
    assert remaining == 0

    after = _snapshot_real_databases()
    for name in before:
        assert after[name] == before[name], (
            f"real database/sidecar {name} changed during OTel cleanup: "
            f"{before[name]} -> {after[name]}"
        )

```

### 4.7 `src/tests/test_prior_checkpoint_isolation.py`

**Status:** untracked/new  
**Attribution:** R2

```python
"""P1-A-R2 B-1: ``session_create`` must count checkpoints in the SAME database
the graph checkpointer writes.

The bridge used to fall back to ``~/.crusorai/sessions.db`` regardless of
``CRUSORAI_CHECKPOINT_DB`` / ``CRUSORAI_CHECKPOINT_HOME`` /
``CRUSORAI_SESSIONS_DB`` / ``CRUSORAI_HOME``. These regressions drive a real
stdio bridge subprocess (echo runner, zero provider traffic) and assert:

* a custom checkpoint database wins over the shared session database;
* a custom session database is used when there is no checkpoint override;
* ``session_resume`` works against the isolated stores;
* a missing checkpoint database yields zero, never a silent home fallback;
* the developer's real database and all sidecars stay untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from src.bridge.protocol import PROTOCOL_VERSION

REPO = Path(__file__).resolve().parents[2]

_DB_FILES = (
    "sessions.db",
    "sessions.db-wal",
    "sessions.db-shm",
    "runtime_events.db",
    "runtime_events.db-wal",
    "runtime_events.db-shm",
    "verification.db",
    "verification.db-wal",
    "verification.db-shm",
)


def _full_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _db_snapshot(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _full_hash(path),
    }


def _real_snapshot() -> dict[str, dict]:
    real_dir = Path.home() / ".crusorai"
    return {name: _db_snapshot(real_dir / name) for name in _DB_FILES}


def _assert_real_db_unchanged(before: dict[str, dict]) -> None:
    after = _real_snapshot()
    for name in before:
        assert after[name] == before[name], (
            f"real database/sidecar {name} changed during a custom-DB run: "
            f"{before[name]} -> {after[name]}"
        )


def _make_checkpoint_db(path: Path, rows: dict[str, int]) -> None:
    """Create a LangGraph-schema checkpoint DB with a known row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints ("
            "thread_id TEXT NOT NULL, "
            "checkpoint_ns TEXT NOT NULL DEFAULT '', "
            "checkpoint_id TEXT NOT NULL, "
            "parent_checkpoint_id TEXT, type TEXT, checkpoint BLOB, "
            "metadata BLOB, "
            "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS writes ("
            "thread_id TEXT NOT NULL, "
            "checkpoint_ns TEXT NOT NULL DEFAULT '', "
            "checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL, "
            "idx INTEGER NOT NULL, channel TEXT NOT NULL, type TEXT, "
            "value BLOB, "
            "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx))"
        )
        for thread_id, count in rows.items():
            for index in range(count):
                con.execute(
                    "INSERT INTO checkpoints "
                    "(thread_id, checkpoint_ns, checkpoint_id, "
                    "parent_checkpoint_id, type, checkpoint, metadata) "
                    "VALUES (?, '', ?, NULL, NULL, NULL, NULL)",
                    (thread_id, str(index)),
                )
        con.commit()


def _bridge_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    env["CRUSORAI_BRIDGE_RUNNER"] = "echo"
    # Never let the developer's shell override the test's explicit stores.
    for key in (
        "CRUSORAI_CHECKPOINT_DB",
        "CRUSORAI_CHECKPOINT_HOME",
        "CRUSORAI_SESSIONS_DB",
        "CRUSORAI_SESSIONS_DB_PATH",
        "CRUSORAI_HOME",
    ):
        env.pop(key, None)
    env.update(overrides)
    return env


class _Bridge:
    def __init__(self, env: dict[str, str]) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "src.bridge"],
            cwd=str(REPO),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

    def send(self, frame: dict, timeout_s: float = 60.0) -> dict:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(frame) + "\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout_s
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"no reply to {frame.get('type')}")
            line = self.proc.stdout.readline()
            if not line:
                stderr = self.proc.stderr.read() if self.proc.stderr else ""
                raise AssertionError(f"bridge closed stdout; stderr={stderr[-2000:]}")
            reply = json.loads(line)
            if reply.get("type") not in {"workspace.bound", "llm.request"}:
                return reply

    def close(self) -> None:
        try:
            self.proc.kill()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            pass


def _start(env: dict[str, str]) -> _Bridge:
    bridge = _Bridge(env)
    hello = bridge.send({"type": "hello", "protocol": PROTOCOL_VERSION})
    assert hello["type"] == "hello", hello
    return bridge


def test_session_create_reads_checkpoints_from_custom_checkpoint_db(tmp_path):
    """An explicit checkpoint DB wins over the checkpoint home and sessions DB."""
    sid = "b1-checkpoint-home"
    ckpt_home = tmp_path / "ckpt"
    checkpoint_db = ckpt_home / "sessions.db"
    decoy_home = tmp_path / "decoy-ckpt"
    session_db = tmp_path / "sessions.db"
    _make_checkpoint_db(checkpoint_db, {sid: 2})
    _make_checkpoint_db(decoy_home / "sessions.db", {sid: 5})  # must NOT win
    _make_checkpoint_db(session_db, {sid: 7})  # must NOT be read
    before = _real_snapshot()

    bridge = _start(
        _bridge_env(
            CRUSORAI_CHECKPOINT_DB=str(checkpoint_db),
            CRUSORAI_CHECKPOINT_HOME=str(decoy_home),
            CRUSORAI_SESSIONS_DB=str(session_db),
            CRUSORAI_HOME=str(tmp_path / "home"),
        )
    )
    try:
        created = bridge.send(
            {"type": "session_create", "session_id": sid, "workspace": str(tmp_path)}
        )
    finally:
        bridge.close()

    assert created["type"] == "session_info", created
    assert created["prior_checkpoints"] == 2, created
    _assert_real_db_unchanged(before)


def test_session_create_uses_custom_session_db_without_checkpoint_override(tmp_path):
    """With only CRUSORAI_SESSIONS_DB set, checkpoints share that database."""
    sid = "b1-session-db"
    session_db = tmp_path / "custom-sessions.db"
    _make_checkpoint_db(session_db, {sid: 3})
    before = _real_snapshot()

    bridge = _start(
        _bridge_env(
            CRUSORAI_SESSIONS_DB=str(session_db),
            CRUSORAI_HOME=str(tmp_path / "home"),
        )
    )
    try:
        created = bridge.send(
            {"type": "session_create", "session_id": sid, "workspace": str(tmp_path)}
        )
    finally:
        bridge.close()

    assert created["type"] == "session_info", created
    assert created["prior_checkpoints"] == 3, created
    _assert_real_db_unchanged(before)


def test_session_resume_uses_isolated_stores_and_leaves_real_db_alone(tmp_path):
    """session_resume must not reopen the developer's real checkpoint DB."""
    sid = "b1-resume"
    ckpt_home = tmp_path / "ckpt"
    _make_checkpoint_db(ckpt_home / "sessions.db", {sid: 1})
    session_db = tmp_path / "session" / "sessions.db"
    before = _real_snapshot()

    bridge = _start(
        _bridge_env(
            CRUSORAI_CHECKPOINT_HOME=str(ckpt_home),
            CRUSORAI_SESSIONS_DB=str(session_db),
            CRUSORAI_HOME=str(tmp_path / "home"),
        )
    )
    try:
        created = bridge.send(
            {"type": "session_create", "session_id": sid, "workspace": str(tmp_path)}
        )
        resumed = bridge.send(
            {"type": "session_resume", "session_id": sid, "workspace": str(tmp_path)}
        )
    finally:
        bridge.close()

    assert created["type"] == "session_info", created
    assert resumed["type"] == "session_info", resumed
    assert resumed["resumed"] is True, resumed
    assert resumed["resolved_session_id"] == sid, resumed
    _assert_real_db_unchanged(before)


def test_missing_checkpoint_db_does_not_fall_back_to_home(tmp_path):
    """A missing custom path reports zero, never the developer's home DB."""
    sid = "b1-no-fallback"
    fake_home = tmp_path / "fake-home"
    decoy_db = fake_home / ".crusorai" / "sessions.db"
    _make_checkpoint_db(decoy_db, {sid: 9})  # a fallback would report 9
    missing = tmp_path / "missing" / "sessions.db"
    before = _real_snapshot()

    env = _bridge_env(
        CRUSORAI_CHECKPOINT_DB=str(missing),
        CRUSORAI_HOME=str(tmp_path / "app-home"),
        HOME=str(fake_home),
        USERPROFILE=str(fake_home),
    )
    bridge = _start(env)
    try:
        created = bridge.send(
            {"type": "session_create", "session_id": sid, "workspace": str(tmp_path)}
        )
    finally:
        bridge.close()

    assert created["type"] == "session_info", created
    assert created["prior_checkpoints"] == 0, created
    assert not missing.exists(), "counting must not create the override DB"
    _assert_real_db_unchanged(before)

```

### 4.8 `src/tests/test_checkpoint_uri_isolation.py`

**Status:** untracked/new  
**Attribution:** R3

```python
"""P1-A-R3 B-4: checkpoint count must use a correctly encoded SQLite URI.

A filesystem path is not a URI. The old construction
``f"file:{db}?mode=ro"`` let ``#`` start a URI fragment, so a path such as
``cp#frag/sessions.db`` was truncated to ``cp``. If a decoy database existed
there, the bridge silently reported another database's checkpoint count.

These regressions drive the real stdio bridge and prove the intended database
(2 checkpoints) wins over a decoy at the incorrectly truncated path
(1 checkpoint), for ``#``, spaces, ``%`` and Unicode. ``?`` is covered at the
URI-encoding layer everywhere and end-to-end on platforms that allow it in a
filename (Windows does not).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from src.runtime.app_paths import sqlite_readonly_uri
from src.tests.test_prior_checkpoint_isolation import (
    _assert_real_db_unchanged,
    _bridge_env,
    _full_hash,
    _make_checkpoint_db,
    _real_snapshot,
    _start,
)


def _assert_bridge_reads_intended_db(tmp_path, checkpoint_db: Path, sid: str) -> None:
    """Run session_create through the real bridge and assert 2, not the decoy."""
    before_real = _real_snapshot()
    before_db = _full_hash(checkpoint_db)
    bridge = _start(
        _bridge_env(
            CRUSORAI_CHECKPOINT_DB=str(checkpoint_db),
            CRUSORAI_HOME=str(tmp_path / "home"),
            CRUSORAI_SESSIONS_DB=str(tmp_path / "sessions.db"),
        )
    )
    try:
        created = bridge.send(
            {"type": "session_create", "session_id": sid, "workspace": str(tmp_path)}
        )
    finally:
        bridge.close()

    assert created["type"] == "session_info", created
    assert created["prior_checkpoints"] == 2, created
    # The count path is read-only; the selected database must be unchanged.
    assert _full_hash(checkpoint_db) == before_db
    _assert_real_db_unchanged(before_real)


def test_hash_in_path_uses_intended_db_not_truncated_decoy(tmp_path):
    """B-4 repro: intended=2, decoy at the pre-# path=1, bridge must say 2."""
    sid = "uri-hash-probe"
    decoy = tmp_path / "cp"
    intended = tmp_path / "cp#frag" / "sessions.db"
    _make_checkpoint_db(decoy, {sid: 1})  # the old URI would open this file
    _make_checkpoint_db(intended, {sid: 2})

    _assert_bridge_reads_intended_db(tmp_path, intended, sid)
    assert decoy.exists()


def test_space_in_path_uses_intended_db(tmp_path):
    sid = "uri-space-probe"
    intended = tmp_path / "cp space" / "sessions.db"
    _make_checkpoint_db(intended, {sid: 2})
    _assert_bridge_reads_intended_db(tmp_path, intended, sid)


def test_percent_in_path_uses_intended_db(tmp_path):
    sid = "uri-percent-probe"
    intended = tmp_path / "cp%percent" / "sessions.db"
    _make_checkpoint_db(intended, {sid: 2})
    _assert_bridge_reads_intended_db(tmp_path, intended, sid)


def test_unicode_in_path_uses_intended_db(tmp_path):
    sid = "uri-unicode-probe"
    intended = tmp_path / "caf\u00e9-\u65e5\u672c" / "sessions.db"
    _make_checkpoint_db(intended, {sid: 2})
    _assert_bridge_reads_intended_db(tmp_path, intended, sid)


def test_question_mark_is_percent_encoded_and_never_a_query_delimiter(tmp_path):
    """A literal ? in the filename must become %3F before ?mode=ro is appended."""
    db = tmp_path / "cp?frag" / "sessions.db"
    uri = sqlite_readonly_uri(db)
    assert "%3F" in uri
    assert uri.endswith("?mode=ro")
    assert uri.count("?") == 1  # only the read-only query delimiter
    assert "%23" not in uri  # no accidental fragment


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows does not allow '?' in a filename; the URI encoding test above covers it",
)
def test_question_mark_in_path_uses_intended_db(tmp_path):
    sid = "uri-question-probe"
    intended = tmp_path / "cp?frag" / "sessions.db"
    _make_checkpoint_db(intended, {sid: 2})
    _assert_bridge_reads_intended_db(tmp_path, intended, sid)


def test_readonly_uri_rejects_writes_and_keeps_database_hash(tmp_path):
    sid = "uri-readonly-probe"
    db = tmp_path / "readonly" / "sessions.db"
    _make_checkpoint_db(db, {sid: 2})
    before = _full_hash(db)

    conn = sqlite3.connect(sqlite_readonly_uri(db), uri=True, timeout=2.0)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM checkpoints")
    finally:
        conn.close()

    assert _full_hash(db) == before

```

### 4.9 `src/tests/test_otel_tracing.py`

**Status:** modified tracked  
**Attribution:** R2

```diff
diff --git a/src/tests/test_otel_tracing.py b/src/tests/test_otel_tracing.py
index b76db141..894262b4 100644
--- a/src/tests/test_otel_tracing.py
+++ b/src/tests/test_otel_tracing.py
@@ -202,16 +202,33 @@ def _stub_factory():
 
 
 def _drop_checkpoints(thread_id: str) -> None:
-    """Remove a thread's checkpoint rows from the shared sessions DB (best
-    effort; the graph's SqliteSaver is bound to ~/.crusorai at import time)."""
+    """Remove this run's checkpoint rows from the SAME database the graph uses.
+
+    The graph resolves its ``SqliteSaver`` path from the environment
+    (``CRUSORAI_CHECKPOINT_DB`` / ``CRUSORAI_CHECKPOINT_HOME`` /
+    ``CRUSORAI_SESSIONS_DB`` / ``CRUSORAI_HOME``); pytest's conftest pins that
+    to a per-run temp root. Never touch the developer's real
+    ``~/.crusorai/sessions.db``, even if this module is imported without the
+    fixture.
+    """
     try:
-        import os
         import sqlite3
+        from pathlib import Path
 
-        db = os.path.join(os.path.expanduser("~"), ".crusorai", "sessions.db")
-        if not os.path.exists(db):
+        from src.graphs import chat_graph
+
+        db = Path(chat_graph._CHECKPOINT_DB).resolve()
+        real = (Path.home() / ".crusorai" / "sessions.db").resolve()
+        if db == real or not db.exists():
             return
-        conn = sqlite3.connect(db, timeout=5)
+        saver = getattr(chat_graph, "memory", None)
+        if saver is not None and hasattr(saver, "delete_thread"):
+            try:
+                saver.delete_thread(thread_id)
+                return
+            except Exception:
+                pass  # fall back to the isolated file below
+        conn = sqlite3.connect(str(db), timeout=5)
         try:
             conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
             conn.commit()
@@ -242,9 +259,10 @@ def test_real_turn_produces_trace_tree(tmp_path, monkeypatch, otel_env):
 
     ws = tmp_path / "ws"
     ws.mkdir()
-    # UNIQUE thread id: the graph's SqliteSaver persists to the shared
-    # ~/.crusorai/sessions.db at import time — a fixed id would resume a
-    # stale checkpoint from an earlier run and loop on its state.
+    # UNIQUE thread id: the graph's SqliteSaver persists to the configured
+    # checkpoint DB (conftest pins it to a per-run temp root) — a fixed id
+    # would resume a stale checkpoint from an earlier run and loop on its
+    # state.
     thread = f"otel-trace-test-{uuid.uuid4().hex[:8]}"
     config = {
         "configurable": {
@@ -276,8 +294,9 @@ def test_real_turn_produces_trace_tree(tmp_path, monkeypatch, otel_env):
     finally:
         turn_controls.end(thread)
         set_active_session(None)  # unbind the thread-local
-        # Best-effort: drop this run's checkpoint rows so repeated test runs
-        # don't accumulate in the shared ~/.crusorai/sessions.db.
+        # Best-effort: drop this run's checkpoint rows from the graph's
+        # configured (isolated) checkpoint DB so repeated test runs don't
+        # accumulate there.
         _drop_checkpoints(thread)
     assert (ws / "hello.py").exists(), "the real tool must have written the file"
 
```

## 5. New regression tests (complete files)

The three new/untracked test modules are reproduced in full in section 4. Summary of coverage:

- `test_checkpoint_isolation.py` (22 tests): path precedence, import laziness, real `SqliteSaver` tables, cross-process restart, fixture isolation, full SHA-256 + existence/size/mtime for nine DB/sidecar files plus journals, invalid paths, B-2 cleanup regression.
- `test_prior_checkpoint_isolation.py` (4 tests): bridge `session_create`/`session_resume`, custom checkpoint DB vs custom session DB, missing-override no-home-fallback, real DB immutability.
- `test_checkpoint_uri_isolation.py` (7 tests): `#` with a decoy at the truncated path, spaces, `%`, Unicode, `?` URI encoding, POSIX-only `?` filename case, read-only write rejection and hash unchanged.

## 6. Verification receipts

### 6.1 R3 verification performed this session
| Command | Result | Exit |
|---|---|---:|
| `pytest -q --no-header -p no:cacheprovider src/tests/test_checkpoint_uri_isolation.py` | **6 passed, 1 skipped**, 25.55 s | 0 |
| `pytest -q --no-header -p no:cacheprovider src/tests/test_checkpoint_uri_isolation.py src/tests/test_prior_checkpoint_isolation.py src/tests/test_checkpoint_isolation.py` | **32 passed, 1 skipped**, 109.47 s | 0 |
| `pytest -q --no-header -p no:cacheprovider src/tests/test_session_pipeline.py` | **7 passed**, 51.52 s | 0 |
| `pytest -q --no-header -p no:cacheprovider src/tests/test_otel_tracing.py` | **7 passed**, 8.96 s | 0 |
| AST parse of `app_paths.py`, `bridge/__main__.py`, `test_checkpoint_uri_isolation.py` | **AST OK** | 0 |
| `git diff --check` on touched files | clean (line-ending warnings only) | 0 |

The single skip is the literal `?` filename end-to-end bridge case; Windows forbids `?` in filenames. The URI-encoding assertion always runs, and the end-to-end case runs on POSIX.

### 6.2 B-4 repro (before vs after)
- Intended DB: `cp#frag/sessions.db` with **2** checkpoints.
- Decoy DB: `cp` (the path before the old URI fragment) with **1** checkpoint.
- Old raw URI `f"file:{db}?mode=ro"`: returned **1** — silent cross-database count. The final independent review rejected P1-A on this evidence.
- R3 `sqlite_readonly_uri()`: returns **2**, the intended database.

### 6.3 Independent final review receipts (prior review, recorded evidence)
| Command | Result | Exit |
|---|---|---:|
| `pytest -q --no-header -p no:cacheprovider src/tests/test_otel_tracing.py` | **7 passed**, 12.89 s | 0 |
| `pytest ... test_prior_checkpoint_isolation.py test_checkpoint_isolation.py` | **26 passed**, 116.24 s | 0 |
| `pytest ... test_session_pipeline.py` | **7 passed**, 54.14 s | 0 |
| Invalid-path probe (five scenarios) | all behaved as documented | — |
| B-4 `#` bridge probe | old code `prior_checkpoints=1`, expected `2` | **blocking / REJECT** |

### 6.4 R2 receipts (recorded in the R2 handoff; not re-run as a separate R2 suite in R3)
| Command | Result | Exit |
|---|---|---:|
| `pytest src/tests/test_checkpoint_isolation.py` | **22 passed**, 56.50 s | 0 |
| `pytest src/tests/test_prior_checkpoint_isolation.py` | **4 passed**, 26.10 s | 0 |
| P1-A targeted receipt (22 isolation + 11 plan completion + 1 workspace isolation + 2 bridge transport + 7 session pipeline) | **43 passed**, 102.62 s | 0 |
| Final R2 receipt (43 + 4 B-1 bridge tests) | **47 passed**, 181.89 s | 0 |
| Persistence/restart subset (increment 2/3, invocation reconciliation, session store/search) | **72 passed**, 27.81 s | 0 |
| B-2 regression + real-data immutability + B-1 suite re-run | **6 passed**, 40.26 s | 0 |

### 6.5 Known failures / red tests (not hidden)
- 2 bridge frame/signature pin tests remain known red.
- `test_runtime_evidence_capture.py` retains 3 pre-existing failures (2 Windows mode-bit assertions, 1 echo/`runtime_degraded` expectation).
- P1-B collection baseline: 3 collection errors remain (missing `deduplicate_streaming_usage`, shadowed `record_turn_receipt`).
- The full test suite was **not** run. No paid provider tests were run.

## 7. Database and sidecar immutability evidence

Full SHA-256 + existence + size + mtime were captured before and after the R3 verification run.

```text
FILES CHANGED:
WORKSPACES CHANGED:
```

| File | Size (bytes) | mtime_ns | SHA-256 |
|---|---:|---:|---|
| `sessions.db` | 937,684,992 | 1794499990403343400 | `5fc06788a9ad9928dc5a127d4bb9fc0ec3b50706733722540e26df321bf4b4ec` |
| `sessions.db-wal` | 0 | 1794502143976032500 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `sessions.db-shm` | 32,768 | 1794503871329186200 | `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb` |
| `runtime_events.db` | 44,466,176 | 1794500418798410200 | `d6e879239e9a6772dfd55e8ceb2241e687f4e7bb5d6220054f46e3ed84bb1543` |
| `runtime_events.db-wal` | 725,152 | 1794500576503332000 | `df9f74873aa3db6aa612198ec6c53b2fdaf3aa3030a1f1ce1075eeeaf46b2e45` |
| `runtime_events.db-shm` | 32,768 | 1794504487985532100 | `67dea1a5af83ccf148aa47b395c9cdf8bc6acb4243c02cda64374dac32f41948` |
| `verification.db` | 835,584 | 1794500242548333800 | `719066a8ca60ff48c1b15270bdcd9d866d7829afdcd363c4ba32339c5c05acb3` |
| `verification.db-wal` / `-shm` | absent | — | — |
| `*.db-journal` (all three) | absent | — | — |

All 61 `~/.crusorai/workspaces/*` directories were unchanged. Long-running application processes were not terminated; no external writes were observed during the verification window.

## 8. Invalid-path evidence (B-3; independently verified, unchanged by R3)

| Scenario | Result |
|---|---|
| Existing directory as the checkpoint path | `sqlite3.OperationalError`; directory preserved; no sibling DB invented |
| Regular file as a parent path | `FileExistsError` / `NotADirectoryError` (`OSError`); target not created |
| Nested parent missing | parent and DB created lazily on first use |
| Writable custom checkpoint location | `SqliteSaver.setup()` creates the DB successfully |
| Unusable override | graph setup exits non-zero; home DB not created; error visible |

No silent fallback to the production home database was observed.

## 9. Remaining limitations
- **F-05 remains PARTIAL:** no VACUUM/prune/retention; `sessions.db` is 937 MB with 426 index DBs; workspace-specific checkpoint placement is not introduced.
- The literal `?` end-to-end bridge case cannot run on Windows because the filesystem forbids `?`; the URI-encoding assertion always runs and the end-to-end case runs on POSIX.
- `conftest.py` unconditionally overrides `CRUSORAI_HOME`, `CRUSORAI_CHECKPOINT_HOME`, and `CRUSORAI_SESSIONS_DB`; external harnesses cannot choose their own runtime root.
- Setting both checkpoint home and session DB intentionally splits checkpoints from session rows.
- `workspace_app_data_root()` follows `CRUSORAI_HOME`; this is a production path change beyond the checkpoint fix.
- The R2 direct-SQL fallback in `_drop_checkpoints` deletes only `checkpoints`, not `writes`; it remains restricted to the non-real DB and is harmless for unique test thread ids.
- Concurrent application writes cannot be fully excluded in future runs; none were observed here.

## 10. Preservation confirmation
- No commits or pushes were made.
- No reset, clean, stash, rebase, or branch switch was performed.
- No existing user work was overwritten.
- No existing project memory was modified during this export.
- The only created file is this bundle: `docs/reviews/P1_A_INDEPENDENT_REVIEW_BUNDLE.md`.
