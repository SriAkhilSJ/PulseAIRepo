# P0.6.5 — Genuine Desktop End-to-End Acceptance

## Executive verdict

**`P0.6.5_ACCEPTANCE_FAILED`**

The real UI → worker → bridge → orchestrator → provider chain is **proven**, with
authentic process ownership, session/turn correlation and an active dispatch
guard inside the application's own bridge. The turn itself **failed**, twice
over, on real product limits:

1. the implementation node's provider output was truncated at the **2048-token
   ceiling** (`finish_reason='length'`), and the P0.5.1 integrity gate correctly
   refused to mutate the workspace;
2. the orchestrator's plan for this task needed **7 dispatches**, while the
   acceptance budget is **5**.

No workspace mutation occurred, so no artifact, test execution or final answer
can be claimed. Financial reservation/settlement is **not implemented on the
orchestrator path** either (see §7), so that criterion is unprovable despite
five real paid dispatches.

## 1. Starting and ending commit

- Start / end: `f781d7d9b20e739ac7e3930ef6fcc746e9af54fe` on
  `feat/prompt-cache-stabilization` (repository clean in `desktop/vscode`;
  pre-existing user changes elsewhere untouched).
- Local == `origin/feat/prompt-cache-stabilization` at start (fetched).

## 2. Repository and environment

- Provider `custom` / `z-ai/glm-5.3-flash`, pricing verified in the P0.6.4.1
  preflight (in $0.05/1M, out $0.20/1M).
- Isolated workspace `<temp>/crusor_p0_6_5_ws_2moklko9` (git init + baseline
  commit; inventory recorded before submission).
- Isolated app profile + state: `CRUSORAI_HOME=<evidence>/home`,
  `CRUSORAI_EVIDENCE_DIR=<home>/evidence`, `VSCODE_PORTABLE` owned by the run.

## 3. Actual Electron process

| Fact | Value |
| --- | --- |
| Executable | `desktop/vscode/.build/electron/CrusorAI.exe` |
| Main PID | 13856 |
| CDP | loopback dynamic port, target `vscode-file://…/workbench-dev.html` |
| Workbench | `.monaco-workbench` ready, title `crusor_p0_6_5_ws_wfyav8cm - CrusorAI IDE Dev` |
| Engine | chip reached **"Crusor ready"** (screenshot `preflight_final/screenshots/01-engine-ready.png`) |

## 4. Worker → bridge ownership (the P0.6.4.1 weakness, fixed)

```
CrusorAI.exe (main 13856)
  └─ --type=utility (workers: 15200,15544,20560,21756,22764,22928)
       └─ .venv\Scripts\python.exe -m src.bridge   (launcher shim)
            └─ ...uv\python\cpython-3.14...\python.exe -m src.bridge  (PID 18920, real interpreter)
```

Ownership is decided by **ancestry** (any ancestor is one of the app's utility
processes), not by a name match; both the venv shim and the real interpreter are
accepted. The acceptance ledger's `pid` (18920) equals the real bridge PID, and
that process printed the guard banner into the app's renderer console:

```
[CrusorAI Engine] [bridge][acceptance] run=p0_6_5_20261107T144026_2df6d6e2
max_dispatches=5 attempts_per_dispatch=1
```

## 5. Session / turn / workspace correlation

| Field | Value |
| --- | --- |
| run_id | `p0_6_5_20261107T144026_2df6d6e2` |
| session_id | `session-6917426bee6f4fd6bbd632db5ece6a71` |
| turn_id | `turn-720fb1c4354645618aaa9592b645325d` |
| workspace_id | `ws-9bd3d627ac6a443e` |
| orchestrator task | `turn_turn-720fb1c4354645618aaa9592b645325d` |

All three IDs come from the bridge's own turn manifest
(`home/evidence/session-…/turn-….json`, verified against its `.sha256`
sidecar). The manifest's `request.sha256` equals `sha256(prompt)` typed into the
composer — the submission is tied to this exact prompt.

## 6. Actual UI submission

- Composer `textarea.crusorai-composer-input` focused via DOM, text inserted with
  `Input.insertText` (real input events), verified byte-identical to the prompt.
- Submitted with **`rawKeyDown` Enter** (the composer's own handler calls
  `preventDefault()` and submits). The earlier `char`-event variant inserted a
  literal newline; that bug is fixed and covered by a test.
- Composer cleared after submit → submission confirmed, then the turn manifest
  appeared with the matching prompt hash.

## 7. Provider dispatches, guard and finance

- **Dispatches: 5. Attempts per dispatch: 1.** Every claim came from the app's
  bridge (`pid 18920`), model `z-ai/glm-5.3-flash`, sequence 1…5. The sixth
  stage never got a claim — the turn failed first.
- The orchestrator journal shows the work it did before failing:
  `TASK_INITIALIZED → REQUEST_UNDERSTOOD → DISCOVERY_COMPLETED →
  ARCHITECTURE_ESTABLISHED → PLAN_GENERATED (nodes_count: 7) →
  IMPACT_EVALUATED → BASELINE_CAPTURED`.
- **Financial reservation/settlement: NOT PERFORMED.** The orchestrator path
  (`EngineeringExecutionOrchestrator` → `ModelExecutionAdapter`) never calls the
  cost governor, so the isolated `home/sessions.db` contains only
  `crusor_sessions` — no `financial_reservations` / `financial_call_ledger`.
  Verified separately that `FinancialStore` + `cost_governor.reserve()` do work
  when called directly with the same `CRUSORAI_HOME`; the missing integration is
  in the orchestrator path, not the store.
- Consequence: no usage receipt, no settled cost, no reconciliation. The five
  dispatches are real but **unmetered by the product**. Bounded worst-case spend
  for the run (bound 859 in + 2048 out × 5) is ≈ ₹0.04, far below ₹5, but that
  is an arithmetic bound, not a receipt.

## 8. Why the turn failed (the P0.5.1 gate doing its job)

```
[bridge] turn FAILED after 57.9s:
RuntimeError("Implementation task node execution failed: Provider stopped before
completing output for 'src/req_001_module.py': finish_reason='length'.")
```

`model_adapter` used `max_output_tokens = getattr(node, "max_tokens", None) or 2048`.
The generated module exceeded 2048 tokens, `assert_provider_output_complete()`
raised, and **no mutation reached the workspace** — the workspace still contains
only `README.md` plus engine diagnostics; `git status` shows only `.crusorai/`
and `diagnostics/`. Zero broker mutations. This is the integrity gate working,
not a silent corruption.

## 9. Renderer health

- Unhandled errors: **0**; unhandled rejections: **0**.
- Warnings: the known upstream `vscode.theme-defaults` configuration-defaults
  warnings (3), plus bridge log lines forwarded to the console by design.
- The upstream `chat.contextContributions` error (`chatSessionRoutingProviderService`
  missing) is **still present** in this build; it does not block the Crusor
  panel (composer, engine chip and turn all worked) and is not a Crusor failure.

## 10. Electron shutdown

`terminate()` → **exit code 1** (not a clean 0). Reported as-is; the app was
stopped by the harness after the turn failed.

## 11. Tests

- `src/tests/test_p0_6_5_live_acceptance.py` — **27 passing** (env, readiness,
  manifest matching/tamper, guard pid/attempt/dispatch checks, financial
  classification, process ownership incl. venv shim, UI input, console
  evidence, verdict math, bounded git, manifest path).
- Full suite touched by this milestone: 27 + 31 (P0.6.4) + 11 (clamp) + 11
  (P0.5.1) = 80 passing.

## 12. Defects found and fixed during this milestone

| Defect | Fix |
| --- | --- |
| `git` in project discovery could block forever on Windows (timeout path re-enters `communicate` while a grandchild holds the pipe) — the desktop turn sat at "Thinking" with 0 dispatches | `RepositoryDiscoveryEngine._run_git`: stdin=DEVNULL, prompts/daemons disabled, hard `taskkill /T` on timeout (`src/intelligence/discovery.py`) |
| Harness looked for manifests under `evidence/turns/` (nonexistent) and never matched a running turn | scan `evidence/**/turn-*.json` |
| Enter key inserted a newline instead of submitting | `rawKeyDown` + `keyUp`, send-button fallback, gate on composer clearing |
| Panel auto-hides ~3 s after restore → readiness sampled a dying view | `ensure_panel_open()` stability loop + re-open on missing chip |
| venv shim hid the real bridge PID | ownership by ancestry; guard pid accepted from the app-owned bridge set |

## 13. Unverified criteria and remaining defects

- Workspace mutation through the broker: **none** (turn failed before valid output).
- Tests executed against a modified workspace: **none** (no artifact).
- Final response in the UI: the **failure** state was rendered (`turn failed`), not a result.
- Financial reservation/settlement: **not implemented on the orchestrator path**.
- Output ceiling 2048 is too small for the implementation node this task produces.
- The orchestrator plans 7 nodes; the acceptance cap is 5 — either the planner
  must honour a dispatch budget, or the acceptance task must be scoped to ≤5
  nodes, or the cap (a product decision) must change.

## 14. Evidence files

- `live4/evidence.json`, `live4/evidence.jsonl` — gates, stages, correlation, financial/verification readouts
- `live4/acceptance_dispatch.json` — guard ledger (run id, pid 18920, 5 claims, 1 attempt)
- `live4/home/evidence/session-…/turn-….json(+.sha256)` — the app's own turn manifest
- `live4/home/runtime_events.db` — journal (`turn.started`, `turn.failed`)
- `live4/screenshots/` — engine ready, prompt typed, turn finished, final response
- `<workspace>/.crusorai/tenants/default_tenant/tasks/turn_…/orchestration_journal.jsonl` — orchestrator stages
- `preflight_final/` — provider-free preflight that passed every gate before submission

## 15. What a passing run would require

1. Wire `OrchestrationFinOpsGovernor` (reserve → usage → settle) into
   `EngineeringExecutionOrchestrator.run_task`, so the financial criteria have
   receipts (the store and governor already work).
2. Raise the implementation node's output ceiling (2048 → 4096) **or** make the
   planner emit a plan that fits the budget; the task's module alone exceeds
   2048 tokens.
3. Align the dispatch budget with the plan (7 nodes) or bound the planner.
4. Only then re-run — one submission, one chain, with real settlement.
