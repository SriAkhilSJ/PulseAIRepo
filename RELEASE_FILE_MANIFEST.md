# Release File Manifest

Repository: SriAkhilSJ/PulseAIRepo
Branch: feat/prompt-cache-stabilization
HEAD: 604605b2a02b3b1b6960f7959f4c122aeeed8bd4

Classification: A Agent Core source, B desktop source, C Agent Core tests, D desktop/tests/scripts,
E documentation, F qualification evidence, G generated artifact, H diagnostics, I unrelated user work, J secrets.

| Path | Status | Class | Commit | Reason |
|---|---|---|---|---|
| `ACTUAL_EXECUTION_PATH_AUDIT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `AGENTS.md` | `??` | E | YES | canonical project instructions |
| `apps/personal_finance/backend/main.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/models.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/repositories/budget_repo.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/repositories/category_repo.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/repositories/transaction_repo.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/routers/budgets.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/routers/categories.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/routers/dashboard.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/routers/export.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/routers/transactions.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/services/budget_service.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/services/dashboard_service.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/services/export_service.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/backend/services/transaction_service.py` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/frontend/index.html` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/frontend/package-lock.json` | `??` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/frontend/package.json` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/frontend/src/api.ts` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/frontend/src/App.tsx` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/frontend/src/index.css` | `??` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/frontend/src/main.tsx` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/frontend/src/types.ts` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/frontend/tsconfig.json` | ` M` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/frontend/vite.config.ts` | `??` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/src/` | `??` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/tests/test_dashboard.py` | `??` | I | NO | unrelated user application work; preserved locally, not released |
| `apps/personal_finance/tests/test_transactions.py` | `??` | I | NO | unrelated user application work; preserved locally, not released |
| `bench-results/phase-3.3-canonical-runtime/BENCHMARK_SPEC.md` | `forced-add` | F | YES | sanitized qualification report retained for maintainers (bench-results ignored) |
| `bench-results/phase-3.3-canonical-runtime/EVALUATION_TEMPLATE.md` | `forced-add` | F | YES | sanitized qualification report retained for maintainers (bench-results ignored) |
| `bench-results/phase-3.3-canonical-runtime/FINAL_AGENT_CORE_QUALIFICATION.md` | `forced-add` | F | YES | sanitized qualification report retained for maintainers (bench-results ignored) |
| `bench-results/phase-3.3-canonical-runtime/FINAL_CLOSURE_REPORT.md` | `forced-add` | F | YES | sanitized qualification report retained for maintainers (bench-results ignored) |
| `bench-results/phase-3.3-canonical-runtime/PRODUCT_QUALITY_EVIDENCE.md` | `forced-add` | F | YES | sanitized qualification report retained for maintainers (bench-results ignored) |
| `COMPLETE_INTEGRATION_ARCHITECTURE.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `desktop/vscode/extensions/copilot/package-lock.json` | ` M` | G | NO | generated dependency lock churn, not required by this release |
| `desktop/vscode/extensions/package-lock.json` | ` M` | G | NO | generated dependency lock churn, not required by this release |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/BUILD_INFO.json` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAI.contribution.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIAccount.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIHideCopilot.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIInlineCompletionProvider.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIOneShot.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIPreviewService.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIRenderer.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIRendererService.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAISessionController.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAISkillsHub.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIUnavailableEngineService.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusorAIWorkbenchService.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/media/crusorAI.css` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/SOURCES_HASH` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/browser/SOURCES_MANIFEST.json` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/common/crusorAICards.js` | `??` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/common/crusorAIProtocol.generated.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/common/crusorAISessionProjection.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/electron-browser/crusorAI.desktop.contribution.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/out/vs/workbench/contrib/crusorai/electron-browser/crusorAIEngineService.js` | ` M` | G | YES | tracked shipped desktop panel generated from reviewed sources |
| `desktop/vscode/remote/package-lock.json` | ` M` | G | NO | generated dependency lock churn, not required by this release |
| `desktop/vscode/scripts/accept-crusorai-checkpoint.mjs` | `??` | D | YES | deterministic Electron acceptance harness |
| `desktop/vscode/scripts/accept-crusorai-engineering.mjs` | `??` | D | YES | deterministic Electron acceptance harness |
| `desktop/vscode/scripts/accept-crusorai-streaming.mjs` | `??` | D | YES | deterministic Electron acceptance harness |
| `desktop/vscode/src/vs/workbench/contrib/chat/browser/chat.contribution.ts` | ` M` | B | YES | desktop/Electron production source |
| `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRenderer.ts` | ` M` | B | YES | desktop/Electron production source |
| `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRendererService.ts` | ` M` | B | YES | desktop/Electron production source |
| `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/media/crusorAI.css` | ` M` | B | YES | desktop/Electron production source |
| `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAICards.ts` | `??` | B | YES | desktop/Electron production source |
| `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAIProtocol.generated.ts` | ` M` | B | YES | desktop/Electron production source |
| `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAIProtocol.ts` | ` M` | B | YES | desktop/Electron production source |
| `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAISessionProjection.ts` | ` M` | B | YES | desktop/Electron production source |
| `desktop/vscode/test/mcp/package-lock.json` | ` M` | G | NO | generated dependency lock churn, not required by this release |
| `DESKTOP_TO_AGENT_INTEGRATION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `diagnostics/generation_boundary/live_acceptance/live11_20261108/evidence_workspace/finops/sessions.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/generation_boundary/live_acceptance/live11_20261108/evidence_workspace/finops/sessions.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/generation_boundary/live_acceptance/live11_20261108/portable/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/LATEST_PERFORMANCE_AUDIT.md` | ` M` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4/user-data/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_1/preflight/portable/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_1/preflight_raced/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_1/preflight_run2/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt1_failed/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt2_failed/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt3_failed/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt4_failed/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt5_failed/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt6_failed/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt7_failed/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt8_failed/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_4_dev_attempts/p0_6_4_attempt9_partial_pass/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/domcheck/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/live/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/live2/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/live3/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/live4/home/runtime_events.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/live4/home/runtime_events.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/live4/home/sessions.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/live4/home/sessions.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/live4/portable/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/preflight/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/preflight_attempt1/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/preflight_final/home/sessions.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/preflight_final/home/sessions.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/preflight_final/portable/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_5/preflight_panel/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_6/live/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_6/live2/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_6/live3/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_6/live4/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_6/live5/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_6/live6/home/runtime_events.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_6/live6/home/runtime_events.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_6/live6/home/sessions.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_6/live6/home/sessions.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_6/live6/portable/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_7/live7/home/runtime_events.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_7/live7/home/runtime_events.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_7/live7/home/sessions.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_7/live7/home/sessions.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_7/live7/portable/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_8/live8/home/runtime_events.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_8/live8/home/runtime_events.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_8/live8/home/sessions.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_8/live8/home/sessions.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_8/live8/portable/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_9/live10/home/runtime_events.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_9/live10/home/runtime_events.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_9/live10/home/sessions.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_9/live10/home/sessions.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_9/live10/portable/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_9/live9/home/runtime_events.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_9/live9/home/runtime_events.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_9/live9/home/sessions.db-shm` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_9/live9/home/sessions.db-wal` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/p0_6_9/live9/portable/` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/PERFORMANCE_REPORT_cancel-test.md` | ` M` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/PERFORMANCE_REPORT_default.md` | ` M` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/PERFORMANCE_REPORT_plan-approval-test.md` | `??` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/PERFORMANCE_REPORT_s-wd.md` | ` M` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/PERFORMANCE_REPORT_t1.md` | ` M` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `diagnostics/traces/cancel-test.jsonl` | ` M` | H | NO | temporary diagnostics/runtime traces; preserved locally, not released |
| `DISCONNECTED_COMPONENTS_REPORT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `docs/ARCHITECTURE.md` | `??` | E | YES | canonical architecture/current-state/handoff documentation |
| `docs/BUGS_AND_LIMITATIONS.md` | `??` | E | YES | canonical architecture/current-state/handoff documentation |
| `docs/CURRENT_STATE.md` | `??` | E | YES | canonical architecture/current-state/handoff documentation |
| `docs/DECISIONS.md` | `??` | E | YES | canonical architecture/current-state/handoff documentation |
| `docs/handoffs/` | `??` | E | YES | canonical architecture/current-state/handoff documentation |
| `docs/phases/` | `??` | E | YES | canonical architecture/current-state/handoff documentation |
| `docs/PROJECT_MASTER.md` | `??` | E | YES | canonical architecture/current-state/handoff documentation |
| `docs/ROADMAP.md` | `??` | E | YES | canonical architecture/current-state/handoff documentation |
| `FINAL_CRUSOR_DESKTOP_ENGINEERING_DEMO.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `INTEGRATION_GAP_ANALYSIS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `MOCK_VS_REAL_TEST_EVIDENCE.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PERFORMANCE_AND_FINOPS_RESULTS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_0_1_FINAL_VERDICT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_1_DESKTOP_RUNTIME_EVIDENCE.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_1_END_TO_END_RESULTS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_1_FINAL_VERDICT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_1_IDENTITY_FINOPS_EVIDENCE.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_1_MODEL_EXECUTION_EVIDENCE.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_1_REMAINING_LIMITATIONS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_1_SECURITY_QUALIFICATION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_1_TEST_RECONCILIATION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_1_WORKSPACE_INTEGRITY.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_2_APPCONTAINER_INTEGRATION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_2_DESKTOP_END_TO_END.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_2_DESKTOP_LAUNCH_REPORT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_2_ELECTRON_ROOT_CAUSE.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_2_FAILURE_RECOVERY.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_2_FINAL_VERDICT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_2_LIVE_MODEL_EXECUTION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_2_OS_SECURITY_TESTS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_2_REGRESSION_RESULTS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_2_REMAINING_LIMITATIONS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_3_APPCONTAINER_EVIDENCE.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_3_DESKTOP_ENGINEERING_TASK.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_3_ELECTRON_RUNTIME.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_3_FINAL_VERDICT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_3_LIVE_MODEL_PROVIDER.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_3_NETWORK_ISOLATION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_3_REGRESSION_RESULTS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_3_REMAINING_LIMITATIONS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_3_REPRODUCIBLE_BUILD.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_3_WORKSPACE_INTEGRITY.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_BASELINE_AND_WORKSPACE_AUDIT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_DESKTOP_EXECUTION_ARCHITECTURE.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_DESKTOP_PROGRESS_INTEGRATION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_END_TO_END_TEST_RESULTS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_FINAL_VERDICT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_IDENTITY_FINOPS_INTEGRATION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_MODEL_EXECUTION_INTEGRATION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_MUTATION_SECURITY_REPORT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_PRODUCTION_READINESS_INTEGRATION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_12_1_REMAINING_LIMITATIONS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_CDP_DESKTOP_RUNTIME.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_CDP_UI_INTERACTION_EVIDENCE.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_LIVE_ACCEPTANCE_LIMITATIONS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_LIVE_FAILURE_RECOVERY.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_LIVE_FINOPS_ATTRIBUTION.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_LIVE_PRODUCT_ACCEPTANCE_FINAL.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_LIVE_REGRESSION_RESULTS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_LIVE_VELONA_PROVIDER_EVIDENCE.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_REAL_MODEL_ENGINEERING_TASK.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `PHASE_WORKSPACE_SECURITY_RESULTS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `REAL_RUNTIME_TEST_RESULTS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `RELEASE_FILE_MANIFEST.md` | `new` | E | YES | this release classification record |
| `REMAINING_LIMITATIONS.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `scripts/demonstrate_ui_to_ai.py` | `??` | H | NO | historical demo/evidence helper, superseded |
| `scripts/reproduce_desktop_build.mjs` | `??` | D | YES | release/verification helper |
| `scripts/test_crusorai_cards.mjs` | `??` | D | YES | release/verification helper |
| `scripts/transpile_crusorai.mjs` | ` M` | D | YES | release/verification helper |
| `scripts/verify_evidence_manifest.py` | `??` | D | YES | release/verification helper |
| `SECURITY_BOUNDARY_INTEGRATION_AUDIT.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |
| `src/agents/sub_agent.py` | ` M` | A | YES | Agent Core production source |
| `src/bridge/__main__.py` | ` M` | A | YES | Agent Core production source |
| `src/bridge/agent_cards.py` | `??` | A | YES | Agent Core production source |
| `src/bridge/protocol.py` | ` M` | A | YES | Agent Core production source |
| `src/bridge/protocol_v2.json` | ` M` | A | YES | Agent Core production source |
| `src/bridge/scripted_turn.py` | `??` | A | YES | Agent Core production source |
| `src/context/compaction.py` | ` M` | A | YES | Agent Core production source |
| `src/context/context_engine.py` | ` M` | A | YES | Agent Core production source |
| `src/finops/invocation_context.py` | ` M` | A | YES | Agent Core production source |
| `src/finops/recovery.py` | ` M` | A | YES | Agent Core production source |
| `src/graphs/chat_graph.py` | ` M` | A | YES | Agent Core production source |
| `src/graphs/state.py` | ` M` | A | YES | Agent Core production source |
| `src/graphs/tool_policy.py` | `??` | A | YES | Agent Core production source |
| `src/impact/persistence.py` | ` M` | A | YES | Agent Core production source |
| `src/intelligence/adr_manager.py` | ` M` | A | YES | Agent Core production source |
| `src/intelligence/architecture_integration.py` | ` M` | A | YES | Agent Core production source |
| `src/intelligence/persistence.py` | ` M` | A | YES | Agent Core production source |
| `src/intelligence/requirement_extractor.py` | ` M` | A | YES | Agent Core production source |
| `src/intelligence/requirement_memory.py` | ` M` | A | YES | Agent Core production source |
| `src/llm/factory.py` | ` M` | A | YES | Agent Core production source |
| `src/llm/gateway.py` | `??` | A | YES | Agent Core production source |
| `src/llm/scripted_model.py` | ` M` | A | YES | Agent Core production source |
| `src/orchestration/approval_gateway.py` | ` M` | A | YES | Agent Core production source |
| `src/orchestration/contract.py` | ` M` | A | YES | Agent Core production source |
| `src/orchestration/finops_governor.py` | ` M` | A | YES | Agent Core production source |
| `src/orchestration/implementation_engine.py` | ` M` | A | YES | Agent Core production source |
| `src/orchestration/model_adapter.py` | ` M` | A | YES | Agent Core production source |
| `src/orchestration/models.py` | ` M` | A | YES | Agent Core production source |
| `src/orchestration/orchestrator.py` | ` M` | A | YES | Agent Core production source |
| `src/orchestration/scheduler.py` | ` M` | A | YES | Agent Core production source |
| `src/orchestration/test_execution.py` | ` M` | A | YES | Agent Core production source |
| `src/p0_6_2_acceptance.py` | `??` | G | NO | generated engineering/request artifact, not release source |
| `src/regression/baseline.py` | ` M` | A | YES | Agent Core production source |
| `src/regression/persistence.py` | ` M` | A | YES | Agent Core production source |
| `src/req_001_module.py` | ` M` | G | NO | generated engineering/request artifact, not release source |
| `src/req_002_module.py` | ` M` | G | NO | generated engineering/request artifact, not release source |
| `src/req_003_module.py` | `??` | G | NO | generated engineering/request artifact, not release source |
| `src/req_004_module.py` | `??` | G | NO | generated engineering/request artifact, not release source |
| `src/req_005_module.py` | `??` | G | NO | generated engineering/request artifact, not release source |
| `src/runtime/app_paths.py` | `??` | A | YES | Agent Core production source |
| `src/runtime/evidence_manifest.py` | `??` | A | YES | Agent Core production source |
| `src/runtime/recovery_dispatcher.py` | ` M` | A | YES | Agent Core production source |
| `src/runtime/step_tracker.py` | ` M` | A | YES | Agent Core production source |
| `src/runtime/submission_ledger.py` | ` M` | A | YES | Agent Core production source |
| `src/runtime/turn_receipt.py` | `??` | A | YES | Agent Core production source |
| `src/tests/test_agent_cards.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_canonical_runtime_engineering_delegation.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_canonical_runtime_increment2.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_canonical_runtime_increment3.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_desktop_startup_registration.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_invocation_reconciliation.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_orchestrator_approval_integration.py` | ` M` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_p0_4_1_reservation_integrity.py` | ` M` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_phase_12_1_1_expense_tracker_task.py` | `??` | H | NO | historical demo/evidence helper, superseded |
| `src/tests/test_phase_12_1_1_identity_finops_production.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_phase_12_1_1_security_qualification.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_phase_12_1_2_appcontainer_terminal.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_phase_12_1_2_failure_recovery.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_phase_12_1_end_to_end_acceptance.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_scope_fidelity.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_shadow_checkpoints.py` | ` M` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_utf8_reliability.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_windows_path_alias.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tests/test_workspace_isolation.py` | `??` | C | YES | Agent Core regression/qualification test |
| `src/tools/file_tools.py` | ` M` | A | YES | Agent Core production source |
| `src/tools/terminal_tools.py` | ` M` | A | YES | Agent Core production source |
| `src/workspace/approval_context.py` | `??` | A | YES | Agent Core production source |
| `src/workspace/approval_digest.py` | `??` | A | YES | Agent Core production source |
| `src/workspace/baseline.py` | ` M` | A | YES | Agent Core production source |
| `src/workspace/journal.py` | ` M` | A | YES | Agent Core production source |
| `src/workspace/ledger.py` | ` M` | A | YES | Agent Core production source |
| `src/workspace/mutation_broker.py` | ` M` | A | YES | Agent Core production source |
| `src/workspace/path_safety.py` | ` M` | A | YES | Agent Core production source |
| `src/workspace/risk_policy.py` | ` M` | A | YES | Agent Core production source |
| `SUBSYSTEM_INTEGRATION_MATRIX.md` | `??` | F | NO | historical phase/audit evidence superseded by canonical docs; excluded to avoid competing architecture records |

## Summary

| Decision | Count |
|---|---|
| Include | 118 |
| Exclude | 169 |

Excluded by class: diagnostics/runtime data, unrelated personal-finance app work, generated request modules,
dependency-lock churn, and historical root phase reports that compete with canonical docs.
