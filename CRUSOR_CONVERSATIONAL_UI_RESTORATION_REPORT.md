# Crusor Conversational UI Restoration — Report

**Date:** 2026-11-11
**Branch:** `feat/prompt-cache-stabilization` · **Starting HEAD:** `fb5bd528b40933346c4004a1490154683dc0d40e` (unchanged)
**Verdict:** **PASS** for the restored interaction model. The transcript is card-free, assistant text streams progressively, Markdown renders, cancellation is honest, and replay restores the conversation. The Agent Core is untouched.

---

## 1. What changed after PR #31

PR #31 is merge commit `631ec58a` (`parents 7e827991… + e0b0016b…`). On this branch there are **no frontend commits after that merge** (`git log 631ec58a..HEAD -- desktop/.../crusorai` is empty). The card-heavy presentation came *inside* PR #31, in:

```
f3528098  feat(desktop): integrate streaming agent cards and desktop routing
          +130  common/crusorAICards.ts   (new)
          +126  browser/crusorAIRenderer.ts
          +64   browser/crusorAIRendererService.ts
          +135  media/crusorAI.css
```

The pre-merge renderer (`git show 631ec58a^1:…/crusorAIRenderer.ts`, 5,023 lines) had `planStrip`, `toolSection`, `assistantTurn` and the tail activity row — and **no** `agentCard` / `is-activity`. That is the baseline this work restores.

### Before vs. the card-heavy state

| Concern | Pre-PR #31 | Card-heavy (post-#31) | Restored now |
|---|---|---|---|
| Assistant text | `parts` text segments, streamed | same + card pins | same, streamed, no card pins |
| Reasoning | inline disclosure | same | same |
| Tool calls | inline `toolSection` rows | rows **plus** typed tool cards | inline rows only |
| Plan | lightweight strip | strip **plus** plan card | strip only |
| Progress | tail activity row | row **plus** activity card | row only |
| File change | tool row + diff | row **plus** file-change card | tool row + diff |
| Tests / verification / delivery / cost | not cards | cards (later hidden) | journaled only |
| Approvals | dock | dock **plus** approval card | dock only |
| Timeline | one list of parts | parts + a second card stack | one list of parts |

## 2. What was already in the working tree

When this pass began, the tree already contained a partial version of this restore (user-owned work): `crusorAICards.ts` marked seven types internal (`activity, plan, file_change, test_results, verification, delivery, cost`) and the renderer/service contained the card-pinning guard. I did **not** overwrite that; I verified it and completed it.

Two concrete gaps were found:

1. **The typed `tool` and `approval` cards were still policy-visible.** Tool cards are suppressed only when a matching inline row exists; orphan/duplicate tool cards still rendered as a bottom stack, and every approval produced both a dock and a card. That is the "second presentation timeline" the task forbids.
2. **The shipped panel was stale.** `test_engine_hash_matches_the_shipped_panel_on_this_repo` failed: `out/` did not match the sources, so the app could still be painting the old UI.

## 3. Changes made in this pass

| File | Change |
|---|---|
| `desktop/.../common/crusorAICards.ts` | `CRUSOR_INTERNAL_CARD_TYPES` now contains **all nine** types; `isUserFacingCard` is false for every typed card. Comment documents the destination of each surface (strip, tool row, dock, receipt, ledger). |
| `scripts/test_crusorai_cards.mjs` | Contract updated: the store keeps all nine; `userFacingCards` returns `[]`; unknown/unsupported cards remain visible as the safe indicator. |
| `src/tests/test_turn_card_rendering.py` | Policy source assertion updated to the nine-type list. |
| `desktop/vscode/scripts/accept-crusorai-p0.mjs` | Planning check reads the plan strip (cards no longer exist). |
| `desktop/vscode/scripts/accept-crusorai-streaming-engine.mjs` | Plan-step sampling reads `.crusorai-plan-strip li`. |
| `desktop/vscode/scripts/accept-crusorai-conversation.mjs` | **New** acceptance for the restored model (streaming, Markdown, no cards, cancel, reload). |
| `desktop/vscode/out/…` | Re-emitted (44 files); hash guard now passes. |

No renderer redesign, no new component, no protocol change, no backend change in this pass.

## 4. What was deliberately preserved

- **Backend event generation and journaling**: every typed card still flows through `agent_cards.py` → `agent_card` frames → journal; `turn_done` receipts, verification and FinOps records are untouched.
- **LangGraph** remains the turn owner; `EngineeringExecutionOrchestrator` remains the delegated engine; the shared gateway, context engine, mutation broker, approval gateway, security boundaries, TurnReceipt, checkpointing, replay, cancellation and failure outcomes are unchanged.
- **Approval dock, plan strip, tool rows, thinking blocks, error rows, turn receipts** — all existing lightweight components.
- **rAF coalescing** in the render service and the renderer's three paint paths.
- **The 160-character holdback** for tools-bound calls. It predates PR #31 (`git show 631ec58a^1:src/graphs/chat_graph.py` contains `_HELD_TEXT_CAP = 160`), and it exists so a generation that turns out to be a tool call is not painted as prose and then discarded. The protocol *can* distinguish tool-call markup (`strip_tool_blocks`) and can retract already-painted text (`message.agent.retract`), but retraction is visible as a flash; removing the hold is a product decision for a later pass, not required to restore this model. Measured effect: the first prose segment appears at ~145–160 chars (≈1.9 s in the acceptance), then every subsequent chunk paints.

## 5. Streaming audit

| Hop | File | Behaviour |
|---|---|---|
| Provider → LangChain | `src/llm/factory.py` | `streaming=True`, `stream_usage=True` |
| Model → events (chat) | `src/graphs/chat_graph.py` `_AgentTokenPump` | 160-char hold, then `message.agent.chunk` per delta; `token_retract` on discard |
| Model → activity (engineering) | `src/orchestration/generation_progress.py` (P1A) | characters/elapsed heartbeat, **no** model text |
| Events → wire | `src/bridge/__main__.py` `_project_event` | `token`, `reasoning`, `tool_call_*`, `turn_done` |
| Wire → state | `crusorAIRendererService.ts` | `token` appends to the last text part; `render()` coalesces to one rAF |
| State → DOM | `crusorAIRenderer.ts` | live text slot patched in place; structural changes repaint |

Nothing in this pass changed the pipeline; the verification below measures it end to end.

## 6. Tests and results

### Deterministic (provider-free)

| Run | Result |
|---|---|
| `node scripts/test_crusorai_cards.mjs` | **ok** — nine internal types, empty user-facing set, unknown stays visible |
| `pytest test_turn_card_rendering.py test_desktop_renderer_architecture.py test_agent_cards.py test_turn_card_association.py test_desktop_session_pipeline.py test_bridge_protocol_v2.py` | **181 passed, 1 skipped, 1 xfailed, 1 failed** |
| `npm run typecheck-client` | **exit 0** |
| panel emitter | **44 files**; engine-hash guard passes |
| `accept-crusorai-p0.mjs` | see §7 |

The one failure is pre-existing and unrelated: `test_agent_cards.py::test_all_required_card_types_are_declared` compares the Python card allowlist (which carries `thinking`, `read`, `search` in this working tree) with the nine-type wire schema.

### Electron acceptance — restored conversation (new)

`accept-crusorai-conversation.mjs`: real `CrusorAI.exe`, real bridge, real canonical runtime, real gateway and a local loopback SSE provider (no paid calls; no scripted orchestrator). **PASS 13/13**:

| Check | Evidence |
|---|---|
| text streams before the turn ends | 36 distinct growing lengths: `0,145,154,163,…,531,546` while running |
| monotonic growth, no missing/duplicated chunks | the same sequence is strictly increasing |
| one chronological timeline | `["text"]` |
| Markdown | 3 headings, 3 list items, 1 code block, inline code parsed |
| **no typed agent card painted** | `0` during every sample and at the end |
| no failure receipt on success | `[]` |
| cancellation | `crusorai-turn-receipt is-cancelled | Run cancelled` |
| not painted successful | no `is-failed` / `is-unknown` |
| reload restores the conversation | 2 turns, no cards, Markdown intact, text `[546,32,32]` |

Screenshots: `bench-results/phase-3.3-canonical-runtime/logs/electron-conversation/{01-agent-ready,02-conversation,03-cancelled,04-restored}.png`; machine-readable `acceptance.json`.

### Electron acceptance — failure semantics (re-run against the card-free UI)

`accept-crusorai-p0.mjs` (mock model adapter only): **PASS 16/16**. A successful turn plans (plan strip `task_notes ✓ / task_verification ✓`), the natural-language request still reaches planning, genuine ambiguity still fails at the gate, the failure renders as `Run failed` **without** any card, and after reload the failed turn restores as failed while the successful turn has no failure row.

## 7. Electron acceptance status

- **Conversation model:** PASS 13/13 with a provider-free loopback transport.
- **Failure semantics (P0):** PASS 16/16 (plan strip + receipts only, no cards; failure restores as failed).
- **Card-heavy progress acceptance (`accept-crusorai-progress.mjs`): superseded.** Its 40 checks assert per-turn *card* ownership, plan cards and hidden internal cards — the exact surfaces this task removes from the transcript. It is left in the tree as historical evidence but is not a valid gate for the restored model; the new conversation acceptance covers the user-visible equivalents (single timeline, cancellation, reload). Rewriting it to assert card ownership would contradict this task; a replacement engineering acceptance should assert the plan strip, receipts and replay instead.

## 8. Remaining problems

1. **Engineering turns still have no assistant prose during generation.** Their model output is a file body or structured plan; only the final delivery report is chat text. The activity card that used to show a heartbeat is now internal, so engineering liveness is limited to the plan strip and the tail "Thinking" row. If engineering should feel conversational, the next step is to route the P1A heartbeat into the tail activity row (a small, additive render-model field), not to bring cards back.
2. **The 160-char holdback remains.** Progressive, but the first ~2 s of a tools-bound answer are silent by design.
3. **Tool-row restoration is fixture-limited.** The SSE chat fixture has no tools, and the bridge scripted runner does not write checkpoints; inline tool rows were verified live (`toolCount:1`, order `[tool,text]` in the scripted run) but not across a restart. A deterministic tool-bearing checkpoint fixture is still needed for that specific assertion.
4. **`accept-crusorai-progress.mjs` is stale** (see §7) and will fail if run unmodified.
5. **Pre-existing failure** `test_all_required_card_types_are_declared` remains (Python/TS card-type drift), untouched.
6. **The Copilot first-run sign-in modal** still appears on a fresh profile; the harness dismisses it. Separate product issue.
7. **No real-provider run** in this pass; all Electron evidence is provider-free (loopback SSE or the bridge's scripted provider seam).

## 9. Git working-tree status

```text
HEAD:        fb5bd528b40933346c4004a1490154683dc0d40e (no commit, no reset/clean/checkout)
Branch:      feat/prompt-cache-stabilization
                241 dirty entries at the start of this pass; zero deletions
Untracked/new: CRUSOR_CONVERSATIONAL_UI_RESTORATION_REPORT.md,
               desktop/vscode/scripts/accept-crusorai-conversation.mjs
Modified:      crusorAICards.ts (+ comment/policy), test_crusorai_cards.mjs,
               test_turn_card_rendering.py, accept-crusorai-p0.mjs,
               accept-crusorai-streaming-engine.mjs, regenerated out/ (44 files)
Preserved:     every pre-existing uncommitted change, including the user's
               partial seven-type policy, P0/P1A work, docs and evidence
```

No file was taken from a historical commit. The pre-PR31 renderer was read with `git show` for comparison only.

---

## Final acceptance condition

| Requirement | Evidence |
|---|---|
| Assistant text streams naturally | 36 incremental paints while running (§6) |
| Tool calls appear inline | scripted run: inline tool rows, `[tool, text]` order |
| Results chronological in one timeline | one `parts` list; no card stack |
| Assistant continues after tools | existing chat path; not re-tested here (fixture limitation) |
| Final responses are ordinary Markdown | headings/list/code/inline verified |
| No card stack | 0 `.crusorai-agent-card` at every sample and after reload |
| Agent Core intact | no backend file changed in this pass; journal/receipts/FinOps untouched |
