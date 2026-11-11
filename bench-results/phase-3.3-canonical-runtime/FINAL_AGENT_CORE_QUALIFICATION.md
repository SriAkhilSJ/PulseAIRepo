# Final Agent Core Qualification (2026-11-10)

Status: **PASS for A/B/C; PARTIAL for the single combined card flow.** A
(checkpoint-backed Electron replay) and B (complete, verifiable evidence
manifest) are closed. C (invocation-ID consistency) is closed live for chat and
engineering implementation, and provider-free for repair/retry semantics. The
remaining partial item is one single Electron run containing every card type.

Starting HEAD: `604605b2a02b3b1b6960f7959f4c122aeeed8bd4`
Branch: `feat/prompt-cache-stabilization` (origin 0/0)
No commits, pushes, resets, stashes or reverts.

## 1. Exact files changed in this qualification

Production:
- `src/llm/scripted_model.py` — provider-boundary cursor keyed by script + session/turn; callback token chunks; usage metadata.
- `src/bridge/scripted_turn.py` — `install_provider_fixture()` configures the provider seam and returns to the normal graph; no frame injection.
- `src/bridge/__main__.py` — removed the scripted bridge bypass; provider fixture falls through to LangGraph; companion cards journaled; `session_messages` returns persisted cards; `agent_card` replay projection; session/turn debug receipt.
- `src/bridge/agent_cards.py` — receipt-derived plan/file/test/verification/cost cards; cost card carries canonical invocation ids.
- `src/runtime/evidence_manifest.py` — versioned manifest builder and sidecar signing.
- `src/runtime/turn_receipt.py` — already deduped; unchanged in this phase.
- `src/graphs/chat_graph.py` — turn contextvar so graph gateway calls carry the canonical turn id.
- `src/finops/invocation_context.py`, `src/orchestration/model_adapter.py` — canonical id/dedupe adoption from previous phase.
- `src/runtime/app_paths.py` and isolation redirects — previous phase, preserved.

Desktop:
- `common/crusorAICards.ts`, `common/crusorAIProtocol.ts`, generated protocol, `browser/crusorAIRenderer.ts`, `browser/crusorAIRendererService.ts` — card hydration on replay, cost invocation row.
- `scripts/accept-crusorai-checkpoint.mjs` — real Electron checkpoint replay acceptance.
- `scripts/test_crusorai_cards.mjs`, `scripts/verify_evidence_manifest.py`.

Tests:
- `src/tests/test_invocation_reconciliation.py` — 12 tests.
- `src/tests/test_agent_cards.py` — 11 tests.
- UTF-8, isolation, scope fidelity tests preserved.

## 2. Checkpoint-backed Electron replay findings

The fixture no longer bypasses the graph. `CRUSORAI_BRIDGE_RUNNER=scripted`
now sets `CRUSORAI_TEST_MODE=1` + `CRUSORAI_TEST_LLM_SCRIPT`; the bridge then
executes the normal path:

```text
Electron prompt
  → bridge _run_turn
  → LangGraph stream_agent / ai_node
  → gateway invoke_model
  → get_llm → ScriptedChatModel (provider boundary)
  → graph finalize
  → SqliteSaver checkpoint
  → TurnReceipt / FinOps ledger
```

Observed in the final acceptance:
- Session: `session-d434c4126fa94caba072ff54fd204f22`
- Checkpoint rows: **8** before and after reload
- Persisted transcript: human prompt + assistant answer (exact emoji/Devanagari/Japanese)
- Card events journaled: activity, delivery, verification, cost (5 cards in `runtime_events`)
- Reload restored the transcript and cards from the checkpoint + journal
- Reload did **not** execute the turn again (checkpoint count 8 → 8)
- User message restored exactly once

Screenshots:
- `logs/electron-checkpoint/01-agent-ready.png`
- `logs/electron-checkpoint/02-pre-reload-streaming.png`
- `logs/electron-checkpoint/03-pre-reload-complete.png`
- `logs/electron-checkpoint/04-post-reload.png`

## 3. Pre/post reload comparison

| Item | Before reload | After reload |
|---|---|---|
| Assistant text | Present | Present, identical |
| User prompt | 1 | 1 |
| Cards | Activity, delivery, verification, cost | Same card ids restored |
| Checkpoint rows | 8 | 8 |
| Turn re-execution | — | None |
| Session id | `session-d434…` | Same |

Raw evidence: `logs/electron-checkpoint/pre-reload.json`,
`post-reload.json`, `turn_receipt.json`.

## 4. Evidence manifest completeness

Run directory: `bench-results/phase-3.3-canonical-runtime/logs/electron-checkpoint/`

`EVIDENCE_MANIFEST.json` (schema 1) contains: run id, test mode, provider mode,
application build id, git HEAD, session/turn ids, prompt id, artifact list,
workspace before/after hashes, commands, `not_applicable` notes, and
`evidence_status`.

Final status: **COMPLETE**; 10 artifacts; no missing required category.
Fixture distinction: `provider_call_authorized=false`; real-provider trace and
real-provider cost are recorded as `not_applicable` with reasons.

Manifest convention: the manifest excludes itself; its canonical bytes are
hashed into `EVIDENCE_MANIFEST.sha256`.

## 5. SHA-256 verification

Verifier: `scripts/verify_evidence_manifest.py`

```json
{
  "status": "COMPLETE",
  "artifacts": 10,
  "bad": [],
  "manifest_sha256": "972964bc190e873ce7c157b3a7049782b0ddeb73145e9392b9095455065d1fed"
}
```

All 10 artifact hashes matched; sidecar matched the manifest bytes.

Bundle of qualification docs, new tests and checkpoint evidence:
`bench-results/phase-3.3-canonical-runtime/EVIDENCE_SHA256_FINAL.txt`
(44 entries; the file's own SHA-256 is kept outside this report to avoid a
self-reference).

## 6. Invocation-ID data flow

```text
graph ai_node
  └─ _invoke_with_token_pump
       └─ gateway.invoke_model
            ├─ mints inv-<16hex> (one physical call)
            ├─ InvocationResult.context.invocation_id
            ├─ FinOps record_invocation(invocation_id, session, turn, usage)
            └─ provider response / usage
  └─ graph state.turn_receipt
       └─ model_invocations.ids = [same inv-…]
       └─ delivery / usage
  └─ bridge turn_done.receipt
       └─ renderer delivery/cost card
            └─ data.invocation_ids = [same inv-…]
```

Engineering path uses the same gateway id: `model_adapter` mints a placeholder,
then replaces it with `canonical_invocation_id(gateway_result, placeholder)`.
Repair is a separate physical dispatch with its own id and `repair_*` purpose.
`latest_invocations()` collapses replayed ledger lines; distinct retries remain
distinct.

## 7. Invocation consistency test results

`src/tests/test_invocation_reconciliation.py`: **12 passed**

1. Gateway id is the only id in the ledger.
2. Reused context gets a fresh physical id.
3. Adapter adopts the gateway id, not its placeholder.
4. Replayed ledger lines count once.
5. True retries remain separate and traceable.
6. TurnReceipt references the gateway invocation.
7. Graph chat writes the canonical session/turn id through the real graph and
   real gateway/ledger (subprocess-isolated, scripted provider).
8. Cost card carries the receipt invocation id.
9. Engineering implementation and repair dispatches keep distinct ledger ids
   and operation types.
10. Unknown cost remains unknown (not zero).
11. Receipt preserves unknown cost from the ledger instead of coercing it to 0.
12. Receipt falls back to ledger cost when delivery omits USD.

Graph chat integration: `graph-canonical-thread` / `graph-canonical-turn` produced
ledger records with exactly that session/turn; receipt ids equal ledger ids.

### Live provider verification (₹25 cap, no key printed)

One live chat and one live engineering task were run against Velona
`z-ai/glm-5.3-flash` in disposable HOME/workspace/app-data roots.

| Run | Gateway id | Ledger id | Receipt id | Result |
|---|---|---|---|---|
| Live chat | `inv-8d717e667d854dfe` | same | same | COMPLETED, 17,777 in / 16 out, cost **unknown** |
| Live engineering | `inv-ce47c37e93364048` | same | same | COMPLETED, VERIFIED, 3,042 in / 166 out, ₹0.017109 settled |

Live engineering workspace contained exactly `hello.md`; bytes were exactly
`Crusor — Build and Ship with Ease 🚀` (hex
`437275736f7220e28094204275696c6420616e6420536869702077697468204561736520f09f9a80`),
with one approval and one mutation.

Evidence: `logs/live-final/{chat.json,engineering.json,chat-gateway.log,engineering-gateway.log,live-results.json}`.

Spend: ₹0.017109 settled for engineering; chat cost was not provider-reported
and remains unknown (estimated ≈₹0.078 at the prior rate, not claimed as actual).
The ₹25 cap was not approached.

## 8. Electron acceptance

Final checkpoint acceptance: **PASS (8/8 checks)**.

Checks: streaming before completion; checkpoint rows exist; pre-reload text and
checkpoint text; restored text; user message once; no re-execution; COMPLETE
manifest.

Previous deterministic card-flow acceptance remains 15/16
(`logs/electron-streaming/`); its only failure was replay, now superseded by the
checkpoint-backed run. The old fixture has been removed from the execution path;
its screenshots are retained as historical card evidence.

## 9. Regression results

| Suite | Result |
|---|---|
| UTF-8 + isolation + invocation + cards + scope + Increments 1–3 + renderer + protocol v2 | **198 passed, 1 skipped, 1 xfailed** |
| Desktop startup/session/workspace boundary + security containment | **263 passed, 4 skipped** |
| Node card contract | **pass** |
| Electron checkpoint acceptance | **PASS 8/8** |
| Evidence manifest verifier | **COMPLETE, 0 bad hashes** |
| `test_shadow_checkpoints.py::test_write_file_snapshot_preserves_old_content` | **FAIL — environment limitation** |

Failure classification:
- Shadow checkpoint case fails because Windows short-path alias (`ADMINI~1`) and
  long path (`Administrator`) are mixed in `file_tools` `relative_to`, so the
  broker refuses the write. No path-normalization code was changed in this task;
  classified **environment limitation / inconclusive as a new regression**.
  It does not affect the Electron acceptance workspace.
- Pre-existing 3 `test_autonomous_runtime_contract.py` failures were not touched.

## 10. Remaining limitations

1. Repair is proven provider-free at the ledger/adapter boundary; no separate
   live repair call was made (budget was reserved for one engineering task).
2. A single combined Electron flow containing approval + file change + tests +
   verification is not re-run in this phase; the checkpoint flow covers chat,
   cards and replay, while the previous card fixture covers the richer visual
   sequence.
3. Fresh-process bridge termination/restart recovery was not separately exercised
   in Electron; renderer reload against the same durable checkpoint was.
4. Fixture usage is synthetic; live chat cost remains `unknown` because the
   provider did not report it. Engineering cost is settled at ₹0.017109.
5. The shadow-checkpoint Windows path-alias failure remains open.

## 11. Exact Git state

```text
HEAD: 604605b2a02b3b1b6960f7959f4c122aeeed8bd4
Branch: feat/prompt-cache-stabilization
Origin: 0 ahead / 0 behind
Working tree: 277 entries (102 modified, 175 untracked)
Snapshot: preserved, manifest 6e9af58d…, 1,671 entries / 0 bad
```

No commit or push was made.

## Final closure update (2026-11-11)

- Engineering implementation dispatch is now proven through the real graph →
  orchestrator → adapter → gateway → ledger → TurnReceipt with a
  provider-boundary fixture. Ledger and receipt ids match.
- Combined Electron engineering acceptance PASS: `acceptance.md` only, approval,
  mutation, plan/file-change/verification/delivery cards, VERIFIED, reload and
  fresh bridge-process restart with no re-execution.
- Fresh bridge restart PASS: old PID exited, new OS process started, transcript
  and cards restored, checkpoint count unchanged.
- Windows short-name/long-name identity fixed via
  `PathSafetyValidator.canonical_path`; 6 native alias/junction tests pass.
- Repair remains **PARTIAL**: a genuine scripted failed-verification repair
  dispatch was not produced; retry/ledger semantics are provider-free only.
- Closure report: `FINAL_CLOSURE_REPORT.md`.
- Architecture status: **FROZEN / QUALIFIED**.
