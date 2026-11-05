# CRUSOR AI IDE — PHASE 9.3.4.1 RAW TEST EVIDENCE

**Timestamp:** 2026-11-03T21:37:36Z  
**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Target Executable:** `desktop/vscode/.build/electron/CrusorAI.exe`  
**Verdict:** **`DESKTOP RUNTIME ACCEPTANCE VERIFIED`**

---

## 1. RUNTIME EVIDENCE JSON DUMP

Source: `bench-results/phase9341_runtime_evidence/runtime_evidence.json`

```json
{
  "phase": "9.3.4.1",
  "timestamp": "2026-11-03T21:37:36Z",
  "tasks": {
    "TASK_A_DESKTOP_BUILD_AND_LAUNCH": {
      "status": "PASS",
      "exit_code": 0,
      "launch_duration_ms": 6020.51,
      "artifact": "C:\\Users\\Administrator\\Downloads\\CRUSORAI\\PulseAIRepo\\desktop\\vscode\\.build\\electron\\CrusorAI.exe",
      "workbench_dom": {
        "shell": true,
        "titlebar": true,
        "activitybar": true,
        "sidebar": true,
        "editor": true,
        "statusbar": true,
        "title": "CrusorAI IDE Dev"
      }
    },
    "TASK_C_COPILOT_NETWORK_NEUTRALIZATION": {
      "status": "PASS",
      "config": {
        "extensionId": "GitHub.copilot",
        "chatExtensionId": "GitHub.copilot-chat",
        "provider": {
          "default": {
            "id": "github",
            "name": "GitHub"
          },
          "enterprise": {
            "id": "github-enterprise",
            "name": "GHE"
          },
          "google": {
            "id": "google",
            "name": "Google"
          },
          "apple": {
            "id": "apple",
            "name": "Apple"
          }
        },
        "entitlementUrl": "",
        "tokenEntitlementUrl": "",
        "mcpRegistryDataUrl": "",
        "managedSettingsUrl": "",
        "entitlementSignupLimitedUrl": ""
      },
      "outbound_copilot_requests": 0
    },
    "TASK_B_OPEN_VSX_MARKETPLACE": {
      "status": "PASS",
      "gallery": {
        "serviceUrl": "https://open-vsx.org/vscode/gallery",
        "itemUrl": "https://open-vsx.org/vscode/item",
        "resourceUrlTemplate": "https://open-vsx.org/vscode/unpkg/{publisher}/{name}/{version}/{path}",
        "controlUrl": "",
        "trustedDomains": [
          "https://www.crusor.in",
          "https://crusor.in",
          "https://crusor.ai",
          "https://open-vsx.org"
        ]
      },
      "live_query_status": "HTTP 200"
    },
    "TASK_F_CONTEXT_REFERENCES": {
      "status": "PASS",
      "suggestions": [
        "@fileReference a workspace file",
        "@folderReference current workspace directory",
        "@symbolReference active symbol or function",
        "@selectionReference currently selected editor text",
        "@diagnosticsReference active workspace problems and diagnostics"
      ],
      "chips_rendered": [
        "@diagnostics"
      ]
    },
    "TASK_G_SLASH_COMMANDS": {
      "status": "PASS",
      "suggestions": [
        "/testRun test discovery or execute workspace test suite",
        "/reviewStructured architectural code review of current changes",
        "/fixAnalyze active diagnostics and propose code corrections",
        "/clearClear conversation view and start a clean session"
      ],
      "composer_value": "/test "
    },
    "TASK_D_INLINE_COMPLETIONS": {
      "status": "PASS",
      "implementation": "CrusorAIInlineCompletionProvider",
      "monaco_interface": "InlineCompletionsProvider",
      "workspace_trust_enforced": true,
      "concurrency_bound": 8,
      "timeout_ms": 4000,
      "sensitive_file_filter": [
        ".env",
        "credentials",
        ".key",
        ".pem",
        ".git/"
      ]
    },
    "TASK_E_NEXT_EDIT_ARCHITECTURE": {
      "status": "PASS",
      "implementation": "CrusorAINextEditProvider",
      "diff_preview_pipeline": "workbenchService.openInlineDiff",
      "atomic_apply_pipeline": "workbenchService.applyWorkspaceEdit",
      "explicit_user_action_required": true,
      "stale_document_invalidation": true
    },
    "TASK_H_SECURITY_APPROVAL_ENFORCEMENT": {
      "status": "PASS",
      "reverse_rpc_allowlist": [
        "workspace.trust",
        "editor.activeSelection",
        "editor.dirtyText",
        "diagnostics.markers",
        "language.symbols",
        "language.definitions",
        "language.references",
        "search.workspace",
        "scm.state"
      ],
      "mutating_tools_blocked_without_trust": [
        "run_in_terminal",
        "code_exec_tool",
        "terminal.native",
        "edit.bulkApply",
        "tasks.run",
        "tests.run"
      ],
      "fail_closed_on_untrusted": true
    }
  },
  "screenshots": [
    "01_desktop_workbench_launched.png",
    "02_crusor_agent_panel_open.png",
    "03_at_context_palette_active.png",
    "04_diagnostics_chip_added.png",
    "05_slash_commands_palette_active.png"
  ],
  "overall_verdict": "DESKTOP RUNTIME ACCEPTANCE VERIFIED"
}
```

---

## 2. SCREENSHOT ARTIFACT MANIFEST

All images stored in `bench-results/phase9341_runtime_evidence/`:

| File Name | Size (Bytes) | Verification Description |
|---|---|---|
| `01_desktop_workbench_launched.png` | 67,018 | Full Monaco workbench shell loaded with titlebar, sidebar, editor, activity bar, status bar |
| `02_crusor_agent_panel_open.png` | 91,652 | Secondary auxiliary sidebar active with Crusor Agent view and composer input focused |
| `03_at_context_palette_active.png` | 102,999 | Interactive context popup rendered displaying `@file`, `@folder`, `@symbol`, `@selection`, `@diagnostics` |
| `04_diagnostics_chip_added.png` | 93,458 | Context chip for `@diagnostics` inserted into composer toolbar |
| `05_slash_commands_palette_active.png` | 103,919 | Slash command autocomplete popup rendered displaying `/test`, `/review`, `/fix`, `/clear` |

---

## 3. PYTEST AUTOMATED REGRESSION OUTPUT

Command:
```powershell
pytest src/tests/test_marketplace_and_copilot_neutralization.py src/tests/test_inline_completion_and_next_edit.py src/tests/test_context_picker_and_slash_commands.py src/tests/test_tool_contracts.py src/tests/test_dispatch_and_finalization.py src/tests/test_financial_accounting_closure.py src/tests/test_financial_provenance.py -v
```

Execution Result:
```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.0.2, pluggy-1.6.0
rootdir: C:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo
configfile: pytest.ini
collected 67 items

src/tests/test_marketplace_and_copilot_neutralization.py::test_product_extensions_gallery_is_configured_with_open_vsx PASSED [  1%]
src/tests/test_marketplace_and_copilot_neutralization.py::test_open_vsx_is_in_trusted_domains PASSED [  2%]
src/tests/test_marketplace_and_copilot_neutralization.py::test_copilot_default_chat_agent_structural_contract_is_preserved PASSED [  4%]
src/tests/test_marketplace_and_copilot_neutralization.py::test_copilot_network_endpoints_are_fully_neutralized PASSED [  5%]
src/tests/test_marketplace_and_copilot_neutralization.py::test_mock_marketplace_query_and_network_interception PASSED [  7%]
src/tests/test_inline_completion_and_next_edit.py::test_inline_completion_provider_implements_interface_and_bounds PASSED [  8%]
src/tests/test_inline_completion_and_next_edit.py::test_inline_completion_provider_registered_in_workbench PASSED [ 10%]
src/tests/test_inline_completion_and_next_edit.py::test_next_edit_provider_architecture_and_contract PASSED [ 11%]
src/tests/test_inline_completion_and_next_edit.py::test_next_edit_provider_registered_in_workbench PASSED [ 13%]
src/tests/test_inline_completion_and_next_edit.py::test_mock_inline_completion_and_next_edit_simulation PASSED [ 14%]
src/tests/test_context_picker_and_slash_commands.py::test_renderer_has_context_chips_and_suggestions PASSED [ 16%]
src/tests/test_context_picker_and_slash_commands.py::test_renderer_css_has_styling_for_chips_and_suggestions PASSED [ 17%]
src/tests/test_context_picker_and_slash_commands.py::test_renderer_service_handles_slash_commands PASSED [ 19%]
src/tests/test_context_picker_and_slash_commands.py::test_renderer_service_resolves_context_chips PASSED [ 20%]
src/tests/test_context_picker_and_slash_commands.py::test_cross_process_security_fail_closed PASSED [ 22%]
src/tests/test_tool_contracts.py::test_security_A_edit_file_no_runtime_config_denied PASSED [ 23%]
src/tests/test_tool_contracts.py::test_security_B_edit_file_empty_workspace_denied PASSED [ 25%]
src/tests/test_tool_contracts.py::test_security_C_edit_file_valid_workspace_succeeds PASSED [ 26%]
src/tests/test_tool_contracts.py::test_security_D_edit_file_path_escaping_workspace_denied PASSED [ 28%]
src/tests/test_tool_contracts.py::test_security_E_write_file_no_workspace_denied PASSED [ 29%]
src/tests/test_tool_contracts.py::test_security_F_copy_file_no_workspace_denied PASSED [ 31%]
src/tests/test_tool_contracts.py::test_security_G_search_files_unauthorized_workspace_denied PASSED [ 32%]
src/tests/test_tool_contracts.py::test_security_H_tool_approval_and_authorization_enforced PASSED [ 34%]
src/tests/test_tool_contracts.py::test_security_I_schemas_do_not_expose_runtime_config PASSED [ 35%]
src/tests/test_tool_contracts.py::test_security_J_no_unintended_mutations_on_rejected_calls PASSED [ 37%]
src/tests/test_tool_contracts.py::test_missing_required_arguments PASSED [ 38%]
src/tests/test_tool_contracts.py::test_invalid_parameter_types PASSED    [ 40%]
src/tests/test_tool_contracts.py::test_path_validation PASSED            [ 41%]
src/tests/test_tool_contracts.py::test_failed_edit_recovery PASSED       [ 43%]
src/tests/test_dispatch_and_finalization.py::test_safetyguard_A_constructor_exception_fails_closed PASSED [ 44%]
src/tests/test_dispatch_and_finalization.py::test_safetyguard_B_check_tool_call_exception_fails_closed PASSED [ 46%]
src/tests/test_dispatch_and_finalization.py::test_safetyguard_C_explicit_denial_stops_execution PASSED [ 47%]
src/tests/test_dispatch_and_finalization.py::test_safetyguard_D_approved_result_allows_execution PASSED [ 49%]
src/tests/test_dispatch_and_finalization.py::test_safetyguard_E_invalid_inspection_result_fails_closed PASSED [ 50%]
src/tests/test_dispatch_and_finalization.py::test_safetyguard_F_edit_file_fails_safely_no_mutation PASSED [ 52%]
src/tests/test_dispatch_and_finalization.py::test_safetyguard_G_run_terminal_fails_safely_no_execution PASSED [ 53%]
src/tests/test_dispatch_and_finalization.py::test_safetyguard_H_typed_security_failure_telemetry PASSED [ 55%]
src/tests/test_dispatch_and_finalization.py::test_safetyguard_I_circuit_breaker_prevents_retries PASSED [ 56%]
src/tests/test_dispatch_and_finalization.py::test_safetyguard_J_external_sentinel_file_cannot_be_mutated PASSED [ 58%]
src/tests/test_finalization_and_safetyguard_independence PASSED [ 59%]
src/tests/test_dispatch_and_finalization.py::test_security_A_missing_workspace_root_rejected PASSED [ 61%]
src/tests/test_dispatch_and_finalization.py::test_security_B_empty_workspace_root_rejected PASSED [ 62%]
src/tests/test_dispatch_and_finalization.py::test_security_D_no_silent_fallback_to_process_cwd PASSED [ 64%]
src/tests/test_dispatch_and_finalization.py::test_security_E_terminal_execution_uses_authorized_workspace PASSED [ 65%]
src/tests/test_dispatch_and_finalization.py::test_security_F_terminal_commands_cannot_escape_workspace PASSED [ 67%]
src/tests/test_dispatch_and_finalization.py::test_dispatch_normalization_contract PASSED [ 68%]
src/tests/test_dispatch_and_finalization.py::test_dispatch_model_schema_excludes_config PASSED [ 70%]
src/tests/test_dispatch_and_finalization.py::test_end_to_end_local_bug_fix_workflow PASSED [ 71%]
src/tests/test_financial_accounting_closure.py::test_scenario_01_raw_anthropic_exclusive_usage PASSED [ 73%]
src/tests/test_financial_accounting_closure.py::test_scenario_02_anthropic_exclusive_with_synthesized_total_tokens PASSED [ 74%]
src/tests/test_financial_accounting_closure.py::test_scenario_03_already_normalized_anthropic_with_explicit_provenance PASSED [ 76%]
src/tests/test_financial_accounting_closure.py::test_scenario_04_claude_through_openai_compatible_inclusive_response PASSED [ 77%]
src/tests/test_financial_accounting_closure.py::test_scenario_05_anthropic_aggregate_writes_plus_ttl_breakdown PASSED [ 79%]
src/tests/test_financial_accounting_closure.py::test_scenario_06_generic_cache_write_only_providers PASSED [ 80%]
src/tests/test_financial_accounting_closure.py::test_scenario_07_mixed_cache_categories_token_conservation PASSED [ 82%]
src/tests/test_financial_accounting_closure.py::test_scenario_08_multiple_cumulative_streaming_usage_events PASSED [ 83%]
src/tests/test_financial_accounting_closure.py::test_scenario_09_partial_stream_cancellation PASSED [ 85%]
src/tests/test_financial_accounting_closure.py::test_scenario_10_sqlite_persistence_and_recovery PASSED [ 86%]
src/tests/test_financial_provenance.py::test_raw_ledger_structure_and_turn_count PASSED [ 88%]
src/tests/test_financial_provenance.py::test_raw_ledger_exact_token_aggregation PASSED [ 89%]
src/tests/test_financial_provenance.py::test_json_and_csv_request_counts_match PASSED [ 91%]
src/tests/test_financial_provenance.py::test_token_totals_match PASSED   [ 92%]
src/tests/test_financial_provenance.py::test_cost_totals_match PASSED    [ 94%]
src/tests/test_financial_provenance.py::test_latency_totals_match PASSED [ 95%]
src/tests/test_financial_provenance.py::test_unknown_cache_write_values_remain_unknown PASSED [ 97%]
src/tests/test_financial_provenance.py::test_rate_card_classifications_remain_distinct PASSED [ 98%]
src/tests/test_financial_provenance.py::test_task_completion_economics PASSED [100%]

============================= 67 passed in 11.51s =============================
```

---

## 4. SELECTIVE MANIFEST VERIFICATION OUTPUT

Command:
```powershell
python scripts/refresh_selective_manifest.py
```

Execution Result:
```
desktop/SELECTIVE_MANIFEST.json: all receipts match the tree. Nothing to do.
```
- Invariant 7 is 100% compliant and intact.

