# Final Agent Core Closure Report (2026-11-11)

Status: **PASS for engineering implementation, Windows path identity, fresh
bridge-process recovery and combined Electron acceptance. PARTIAL for a genuine
failed-verification repair dispatch. Architecture frozen.**

Starting HEAD: `604605b2a02b3b1b6960f7959f4c122aeeed8bd4`
Branch: `feat/prompt-cache-stabilization` (origin 0/0)
No paid provider calls. No commit or push. Snapshot preserved.

## 1. Exact files changed in this closure

Production:
- `src/graphs/chat_graph.py` — `CRUSORAI_FORCE_REAL_MODEL=1` selects the real
  adapter under the scripted provider; canonical turn contextvar.
- `src/bridge/scripted_turn.py` — engineering provider-boundary fixture with
  usage receipts; no bridge bypass.
- `src/workspace/path_safety.py` — `canonical_path()` via OS realpath/final-path
  resolution; containment and relative-path calculation use it.
- `src/tools/file_tools.py` — broker-relative paths use
  `PathSafetyValidator.get_relative_normalized` instead of `relative_to()`.
- `src/llm/scripted_model.py` — per-session/turn cursor, token callbacks, usage
  metadata (from prior qualification).

Tests:
- `src/tests/test_invocation_reconciliation.py` — real engineering dispatch test
  and canonical cost/unknown-cost tests.
- `src/tests/test_windows_path_alias.py` — 6 native alias/junction tests.
- `src/tests/test_shadow_checkpoints.py` — approval-bound write/edit fixtures
  updated to preserve assertions under the broker policy.

Desktop acceptance:
- `desktop/vscode/scripts/accept-crusorai-checkpoint.mjs` — adds bridge PID
  kill/restart proof.
- `desktop/vscode/scripts/accept-crusorai-engineering.mjs` — combined
  engineering Electron acceptance.

Docs:
- `docs/ARCHITECTURE.md` section 14 status → FROZEN / QUALIFIED.
- `docs/CURRENT_STATE.md`, existing qualification report, this report.

## 2. Engineering / repair invocation results

| Path | Status | Evidence |
|---|---|---|
| Engineering implementation through real orchestrator | **PASS** | `test_engineering_dispatch_uses_canonical_id_through_real_orchestrator`; one `inv-…` in gateway log, ledger and receipt; `COMPLETED`, `VERIFIED`, one `acceptance.md` |
| Repair / failed-verification loop | **PARTIAL** | Retry/ledger separation covered provider-free; no genuine scripted failed-verification repair dispatch was produced |

Implementation fixture: LangGraph → `engineering_task_node` →
`EngineeringExecutionOrchestrator` → `ModelExecutionAdapter` → shared gateway →
`ScriptedChatModel` → FinOps ledger → DeliveryContract → TurnReceipt.

The test does not call adapter helpers directly and does not fabricate a gateway
result. `CRUSORAI_FORCE_REAL_MODEL=1` only forces the real adapter under
`CRUSORAI_TEST_MODE`; the provider is still the deterministic scripted model.

Repair limitation: syntax-invalid and missing-symbol responses failed
pre-verification (generation/contract validation), so the orchestrator never
entered its verification-driven repair loop. No test was weakened to fake it.

## 3. Full invocation-ID data flow

```text
graph ai_node / engineering_task_node
  → orchestrator / adapter
    → gateway.invoke_model
      → mints one inv-<16hex>
      → provider (scripted boundary)
      → InvocationResult.context.invocation_id
      → FinOps ledger record (same id, session, turn, usage)
  → DeliveryContract / verification
  → TurnReceipt.model_invocations.ids (same id)
  → bridge turn_done.receipt
  → renderer delivery/cost card data.invocation_ids (same id)
```

Engineering test evidence: ledger id == receipt id == UI card id. Chat and live
engineering were already proven in the prior qualification; this closure adds
the real provider-free engineering dispatch.

## 4. Windows short-path root cause

`file_tools` converted `safe_path` to a broker-relative path with
`safe_path.relative_to(workspace)`. That is a string/PurePath operation, not a
filesystem identity check. On Windows the same directory appeared as both
`C:\Users\ADMINI~1\...` and `C:\Users\Administrator\...`, so a legitimate target
inside the workspace failed containment and a broker path could be computed
inconsistently.

This was not harmless noise: it could make containment/authorization decisions
on a different spelling of the same physical target.

## 5. Windows normalization decision

Added `PathSafetyValidator.canonical_path()`:
- Uses `os.path.realpath()` (Windows final-path/handle resolution for existing
  components) to expand 8.3 aliases and resolve junctions/symlinks.
- For a non-existent leaf, the existing parent is canonicalized and the leaf is
  retained, so pre-write validation remains safe.
- Containment compares canonical paths, case-insensitively on Windows.
- Relative broker paths use the same canonical root/target.
- No lowercasing of the whole path and no stripping of `~` aliases.
- Approval tokens now bind the canonical relative path, content digest and
  precondition; an alias cannot create a second authorization target.

Junction/symlink escapes are resolved to their outside target and rejected by
the containment check.

## 6. Alias and containment test results

`src/tests/test_windows_path_alias.py`: **6 passed**
1. Short-name and long-name resolve to one target.
2. Case-insensitive existing file resolves to the real casing / one relative path.
3. Approved write via long alias; token replay via short alias rejected.
4. Outside-workspace alias and `../` escape rejected.
5. Junction escape rejected.
6. Non-existent target under aliased parent contained.

Related suites: `test_shadow_checkpoints.py` **19 passed**;
`test_security_containment.py`, `test_desktop_workspace_boundary.py`,
`test_phase_9_4_1_windows_boundary.py` all green in the 287-passed run.

## 7. Fresh bridge-process restart evidence

Electron checkpoint acceptance killed the live Python bridge and waited for an
automatic fresh OS process:
- Old bridge PID: **18576**; exited.
- New bridge PID: **10884**; started.
- Transcript restored from durable checkpoints.
- User message restored once.
- Checkpoint rows: **8 before / 8 after**; no re-execution.
- Cards (activity/delivery/verification/cost) restored.
- Evidence: `logs/electron-checkpoint/acceptance.json` `bridgeRestart`,
  `05-bridge-restart.png`.

## 8. Combined Electron engineering acceptance

Fresh Electron app, disposable workspace/user-data/home, real bridge, real
LangGraph/orchestrator, provider-boundary scripted model, no paid provider.

Prompt: “Create exactly one file named acceptance.md containing a short
description of Crusor. Do not create any other user deliverables.”

**PASS** checks:
- Actual Agent pane and UI submission.
- Graph classification and engineering delegation.
- Plan card, approval/diff card + real approval click.
- WorkspaceMutationBroker applied the mutation.
- Tool/file-change card, independent verification, verification card.
- Delivery card and TurnReceipt.
- Exactly one deliverable: `acceptance.md`; no `.crusorai`/`diagnostics`.
- Reload restored the conversation and prompt once.
- Fresh bridge restart restored the conversation and did not re-execute.
- Ledger id == receipt id (`inv-5b8f1fc7c6914417` in the acceptance run).

Screenshots:
`logs/electron-engineering/{01-agent-ready,02-engineering-start,03-approval-diff,04-engineering-complete,05-post-reload,06-bridge-restart}.png`

## 9. Workspace hashes and final contents

Combined acceptance workspace contained exactly:
```text
acceptance.md  171 bytes
sha256 255b1ce641d257f9b9aeffc383e9045ca95776900641eb02365553b11c8b3bf5
```
Content:
“Crusor is an AI-powered coding IDE that plans changes, applies them through an
approval-gated workspace broker, runs verification, and reports a truthful
delivery receipt.”

Evidence manifest: `logs/electron-engineering/EVIDENCE_MANIFEST.json`
(**COMPLETE**, 12 artifacts, 0 bad hashes, sha256
`060628e17fbffbd3d4c3c710654bf4027865a49f945ec650231ea5e5abb16329`).

## 10. FinOps / TurnReceipt replay evidence

- Combined engineering ledger and receipt ids equal.
- Checkpoint carries `turn_receipt`; replay did not append a second invocation.
- Ledger dedupe and unknown-cost preservation covered by 13 invocation tests.
- No paid calls in this closure; cost amounts are fixture synthetic.

## 11. Regression results

| Suite | Result |
|---|---|
| UTF-8, isolation, invocation, Windows alias, cards, scope, Increments 1–3, renderer, protocol | **205 passed, 1 skipped, 1 xfailed** |
| Desktop startup/session/workspace, security containment, shadow checkpoints, Windows boundary | **287 passed, 4 skipped** |
| Electron checkpoint (reload + bridge restart) | **PASS** |
| Combined Electron engineering | **PASS** |
| Evidence manifests | **COMPLETE, 0 bad hashes** |

No new regression failures. Historical autonomous-runtime failures remain
pre-existing and untouched. No test was deleted or weakened.

## 12. Architecture freeze status

- LangGraph remains the single interactive lifecycle; orchestrator remains the
  delegated engineering engine.
- No new runtime, gateway, broker, approval queue, checkpoint system or ledger.
- Increments 1–3: **closed**.
- `docs/ARCHITECTURE.md` section 14: **FROZEN / QUALIFIED**.
- No further architecture migration phase authorized.

## 13. Remaining product-readiness limitations

1. **Repair loop PARTIAL** — no genuine scripted failed-verification repair
   dispatch was produced; provider-free retry/ledger semantics are covered.
2. Fresh bridge restart was proven after a completed chat turn; the combined
   engineering run also restarted the bridge, but a restart *during* an active
   tool/approval wait is not separately tested.
3. Fixture cost is synthetic; live chat cost remains provider-unknown by design.
4. Production readiness still reports expected warnings for missing CI/CD,
   backup policy and `/health` in disposable workspaces.
5. The ten-task coding benchmark has not been executed.

## 14. Exact Git state

```text
HEAD: 604605b2a02b3b1b6960f7959f4c122aeeed8bd4
Branch: feat/prompt-cache-stabilization
Origin: 0 ahead / 0 behind
Working tree: 281 entries (104 modified, 177 untracked)
No commit or push
```

Working tree and snapshot counts are recorded in the final response and in
`REPO_HYGIENE.md`; the snapshot remains
`C:\Users\Administrator\AppData\Local\Temp\opencode\crusor-snapshot-20261110`
(1,671 entries, 0 bad).
