# Crusor Turn Card Restoration Report

**Task:** give every Agentic card exactly one owning conversation turn, persist that ownership, and restore it on reload/restart.

| Field | Value |
|---|---|
| Branch | `feat/prompt-cache-stabilization` |
| Starting HEAD | `fb5bd528b40933346c4004a1490154683dc0d40e` |
| Final HEAD | `fb5bd528b40933346c4004a1490154683dc0d40e` (no commit) |
| New card schemas / renderers | 0 |
| Paid provider calls | 0 (`rows=0` in the acceptance) |
| Electron acceptance | **PASS 32/32 checks**, including a full application restart |

---

## 1. Root cause

Cards were persisted with full identity, then thrown away at hydration.

- `crusorAIRendererService.ts` held **one global live map**:
  `private readonly cards = new Map<string, CrusorCardView>()` + `cardOrder`.
- Every `agent_card` frame went into that map and therefore painted in the **current** assistant lane.
- `session_messages` loaded **every** journaled card for the session into the same map; history rendering never passed cards into `assistantTurn()`.
- `hydrateTranscript()` had no turn identity at all: `HydratedTurn` carried only user/assistant text, parts, reasoning and tools.
- The bridge deduplicated journal cards by `card["card_id"]` alone and its history request returned **messages without any turn id**.
- `resetSessionState()` did not clear the card map, so a session switch could also leak cards.

Result: after a reload, cards from all turns reappeared in one shared bottom stack; nothing tied a card to the turn that produced it.

---

## 2. Existing identity and persistence architecture

Already present and reused:

- `CrusorCardView` (`common/crusorAICards.ts`) carries `schemaVersion`, `cardType`, `cardId`, `sessionId`, `turnId`, `data`.
- The bridge's `agent_card` journal rows carry `session_id`, `turn_id`, the card envelope, and a durable sequence.
- `session_messages` returns messages, pagination and cards; `_transcript_messages` projects checkpoint messages.
- `turn_started` frames carry the turn identity, and every card id is already turn-prefixed by producers (`<turn>:activity`, `<turn>:plan`, `<turn>:receipt:…`).

The missing link was **turn identity on historical messages** and **a per-turn card container in the renderer**.

---

## 3. Implementation changes

### 3.1 Shared card state — `common/crusorAICards.ts`

New `CrusorCardStore` (no DOM, no schema change):

- buckets keyed by **turn id**; each bucket keeps `Map<cardId, card>` plus stable first-arrival `order`;
- `update(card, fallbackTurnId)` — a card without a persisted turn id can be assigned only to an explicitly supplied current turn;
- `cardsFor(turnId)`, `turnIds()`, `all()`, `size()`;
- `snapshot()` / `restore()` for the surface stash;
- `clearTurn()` / `clear()`.

The same card id in two turns is two cards. Updating an existing `(turn, card)` replaces in place; duplicate replay is idempotent.

### 3.2 Renderer service — `browser/crusorAIRendererService.ts`

- State is now `private readonly cardStore = new CrusorCardStore()` plus `private currentTurnId: string | undefined`. The global `cards`/`cardOrder` map is gone.
- `turn_started` sets `currentTurnId` from the frame and clears that turn's bucket (and the legacy empty bucket).
- Live `agent_card` frames route by the card's own `turnId` (falling back to `currentTurnId`); a card for another turn updates that turn's bucket and, if that turn is in history, `syncHistoryCards(turnId)` refreshes only that entry.
- The live model paints `cardStore.cardsFor(currentTurnId)` only.
- `session_messages`:
  - settled/open hydration rebuilds the whole store from the journal;
  - a mid-run refresh **merges** so the live turn's bucket keeps painting;
  - cards are loaded **before** `hydrateTranscript` so turns can resolve them.
- `hydrateTranscript`:
  - `HydratedTurn` gains `turnId`; a message `turn_id` change is a hard boundary;
  - each history turn receives `cards: cardStore.cardsFor(turn.turnId)`;
  - a live turn currently painting is not duplicated into history;
  - legacy messages without turn ids use **only** the unambiguous single-turn/single-bucket fallback;
  - unclaimed buckets are kept in the store and named once via `console.warn` — never merged into the newest turn.
- `resetSessionState()` clears the store and `currentTurnId`; surface `captureSurface`/`restoreSurface` include `cardTurns` and `currentTurnId`.
- `archiveLiveTurn()` records the archived turn's `turnId`/`cards`.
- History entries with a `turnId` are the unit of card ownership.

### 3.3 Renderer — `browser/crusorAIRenderer.ts`

- `CrusorAIRenderModel` gains `currentTurnId`, and each history entry gains `turnId` + `cards`.
- History `assistantTurn(...)` now passes `cards: turn.cards` and `turnId: turn.turnId`; the live lane passes `cards: model.cards` and `turnId: model.currentTurnId`.
- `assistantTurn` sets `data-turn-id` on the assistant section (non-visual test/ownership marker).
- Presentation is unchanged: cards still render at the end of their turn via the existing `agentCardStack`/`agentCardView`.

### 3.4 Bridge — `src/bridge/__main__.py`

- `_journal_events(journal, session, page=2000)` pages the journal to completion (no single-window truncation).
- `_turn_request_rows(events)` extracts `(request.sha256, turn_id)` for every `turn.started` row.
- `_assign_transcript_turn_ids(projected, rows)`:
  - primary: hash the persisted human message and match the journal's `turn.started.request.sha256`; each prompt group is stamped with its real turn id;
  - steers inherit the open turn;
  - duplicate prompts consume turn ids in order;
  - legacy journals without request hashes fall back to ordinal association **only when user-message count equals turn count**;
  - no match ⇒ no stamp (never a newest-turn guess).
- `_transcript_messages(..., turn_rows=...)` assigns ids on the **full** list before paging, so a page boundary cannot split a turn from its prompt.
- `_latest_agent_cards(events, session)` dedupes by `(session_id, turn_id, card_id)`; replay updates in place, order is first-arrival.
- `session_messages` loads journal events once, stamps messages and returns per-turn cards together.
- Protocol: `CrusorSessionMessage.turn_id?: string`.

No LangGraph, orchestrator, card schema, CSS or renderer component was redesigned.

---

## 4. Updated state model

```text
card identity = (sessionId, turnId, cardId)

CrusorCardStore
  turnId -> { cardId -> card, order: cardId[] }

live assistant lane  -> cardsFor(currentTurnId)
history turn N       -> cardsFor(history[N].turnId)
```

Rules enforced:

1. Existing `(turn, cardId)` updates in place.
2. A new card appears only in its originating turn.
3. A different turn cannot overwrite another turn's card (even with the same card id).
4. Session reset/switch clears all buckets.
5. Replay cannot duplicate (update by identity + idempotent restore/hydration).
6. Per-turn insertion order is stable.

---

## 5. End-to-end flow

```text
producer emits agent_card (session, turn, card)
  → bridge journals it
  → bridge session_messages:
       journal events (paged)
       → turn.started request hashes
       → stamp each human/assistant/tool message with turn_id
       → latest card per (session, turn, card)
  → renderer:
       cardStore.update(card)
       hydrateTranscript(messages)
         → history turns carry turnId
         → cardsFor(turnId) attached per turn
  → renderer model.history[*].cards
  → assistantTurn(history turn) → agentCardStack at the end of THAT turn
  → reload/restart: same path, same identities
```

Live flow:

```text
turn_started (turn id) → currentTurnId
agent_card → cardStore.update(card, currentTurnId)
model.cards = cardsFor(currentTurnId)
```

---

## 6. Legacy compatibility

- Card envelope/schema unchanged (v1); old four-status plan cards and all existing card types remain valid.
- Journal rows already carried turn ids; the bridge now preserves them through `session_messages`.
- Older sessions whose `turn.started` rows lack `request.sha256` use the ordinal fallback **only when counts match exactly**.
- A session whose messages have no turn ids at all can still associate cards only when there is exactly one hydrated turn and exactly one card bucket.
- Anything ambiguous stays in the store, is **not** attached to the newest turn, and is named in a bounded `console.warn`. No history is deleted.
- Old clients that receive a new status still fall back to `pending`; not relevant to this change.

---

## 7. Deterministic tests and results

All Python runs used `.venv\Scripts\python.exe` (Python 3.14.4, Windows). No provider call.

### 7.1 Card store — `node scripts/test_crusorai_cards.mjs`

Extended with per-turn assertions (same runner as the existing card contract):

- turn 1 and turn 2 each hold `activity` + `plan`;
- the same card id in both turns stays two cards;
- an update replaces in place and keeps position;
- duplicate replay + snapshot round-trip are idempotent;
- a legacy card without `turn_id` is assigned only to the supplied turn;
- `clearTurn` / `clear` implement session switching.

Result: **`crusorai card contract ok`**.

### 7.2 New Python suites

`src/tests/test_turn_card_association.py` — **13 passed**

| Covers | Test |
|---|---|
| Turn 1 / Turn 2 message grouping | `test_message_turn_ids_follow_request_hashes` |
| Steer inherits its turn | `test_unmatched_user_message_inherits_the_open_turn` |
| Identical prompts → distinct turns | `test_identical_prompts_map_to_distinct_turns_in_order` |
| Legacy ordinal fallback only when counts match | `test_legacy_ordinal_fallback_only_when_counts_match` |
| No rows → no stamps | `test_no_turn_rows_leaves_messages_unstamped` |
| Journal turn rows | `test_turn_rows_read_only_turn_started_request_hashes` |
| Paged journal | `test_journal_pagination_reads_every_page` |
| Same card id in two turns | `test_cards_are_keyed_by_full_identity_not_card_id_alone` |
| Cards from another session never returned | `test_cards_from_another_session_are_not_returned` |
| Update in place / order | `test_card_replay_updates_in_place_and_preserves_order` |
| Duplicate replay | `test_duplicate_replay_never_duplicates_cards` |
| Handler returns per-turn cards + messages | `test_session_messages_stamps_cards_and_messages_with_turns` |
| Handler uses the identity helpers | `test_session_messages_source_uses_full_identity_helper` |

`src/tests/test_turn_card_rendering.py` — **7 passed** (source contracts): per-turn store, no global card map, session reset clears cards, hydration attaches only the turn's cards, settled/merge behaviour, history renderer passes `cards`/`turnId`, live updates route by owning turn.

Combined: **20 passed**.

### 7.3 Regression

```text
python -m pytest src/tests/test_engineering_progress_events.py \
  src/tests/test_plan_completion.py src/tests/test_plan_outcome_semantics.py \
  src/tests/test_canonical_runtime_engineering_delegation.py \
  src/tests/test_canonical_runtime_increment2.py \
  src/tests/test_bridge_orchestrator_protocol.py -q
79 passed

python -m pytest src/tests/test_desktop_renderer_architecture.py \
  src/tests/test_bridge_protocol_v2.py src/tests/test_agent_cards.py \
  src/tests/test_turn_card_rendering.py src/tests/test_turn_card_association.py -q
157 passed, 1 skipped, 1 xfailed, 1 pre-existing failure

python -m pytest src/tests/test_bridge.py src/tests/test_bridge_transport.py \
  src/tests/test_bridge_workspace_routing.py src/tests/test_bridge_protocol_v2.py -q
73 passed, 2 pre-existing failures
```

Pre-existing failure unchanged: `test_agent_cards.py::test_all_required_card_types_are_declared`
(working tree already adds `thinking`/`read`/`search` to Python `CARD_TYPES`), plus the two
`test_bridge.py` assertions already documented (echo frame window, autotitler signature).

Frontend:

```text
cd desktop/vscode && npm run typecheck-client
EXIT=0

node scripts/emit-crusorai-bundle.mjs
[emit] wrote 43 file(s)   (out JS/CSS + SOURCES_HASH current)
```

---

## 8. Electron acceptance evidence

`desktop/vscode/scripts/accept-crusorai-progress.mjs` was extended and run against the real app
(`desktop/vscode/.build/electron/CrusorAI.exe`) with `CRUSORAI_ORCHESTRATOR_MOCK=1`, approval
policy `ask`, and no provider: **PASS 32/32 checks, `rows=0`**.

Scenario executed:

1. Turn 1 — creates `notes.md`, approval → completed.
2. Turn 2 — nested target fails → failed + blocked.
3. Turn 3 — Stop during the approval wait → cancelled.
4. Reload the workbench → verify per-turn ownership.
5. Reload again → identical state (hydration idempotence).
6. Kill the application tree and relaunch the same profile → verify again.

Per-turn results (from `acceptance.json`):

```text
three restored turns carry distinct ids:
  turn-71ae10d8772c4a6fbf0651b490350355
  turn-338eb95057c740e2a0774ea7c8184f63
  turn-8d1408543456417c9073e61a4941be97

each turn owns exactly one plan card: [1, 1, 1]
every card id starts with its own turn id: PASS
turn 1 plan: [completed, completed]
turn 2 plan: [failed, blocked]
turn 3 plan: [cancelled, cancelled]
repeated hydration identical: PASS
three turns after application restart: PASS
restart keeps every card in its own turn: PASS
```

Screenshots (gitignored evidence):

- `bench-results/phase-3.3-canonical-runtime/logs/electron-progress/04-complete.png`
- `.../05-failed-blocked.png`
- `.../06-cancelled.png`
- `.../05-after-reload.png`
- `.../07-restarted.png`
- `acceptance.json` / `progress-result.json` — full check payloads.

The restored DOM groups cards inside `section.crusorai-assistant-message[data-turn-id]`; the
acceptance reads those sections and their card ids directly, not just journal rows.

---

## 9. Changed files

Backend:

- `src/bridge/__main__.py` — journal paging, turn stamping, full-identity card dedupe, handler integration.
- `src/tests/test_turn_card_association.py` *(new)*.
- `src/tests/test_turn_card_rendering.py` *(new)*.

Frontend:

- `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAICards.ts` — `CrusorCardStore`.
- `.../browser/crusorAIRendererService.ts` — per-turn store, hydration, session lifecycle, snapshots.
- `.../browser/crusorAIRenderer.ts` — history cards, `turnId`, `data-turn-id`.
- `.../common/crusorAIProtocol.ts` — `CrusorSessionMessage.turn_id`.
- `desktop/vscode/out/vs/workbench/contrib/crusorai/**` — regenerated panel (JS/CSS/SOURCES_HASH/BUILD_INFO/manifest).

Tests/script:

- `scripts/test_crusorai_cards.mjs` — store assertions.
- `desktop/vscode/scripts/accept-crusorai-progress.mjs` — per-turn reload, repeated hydration, full restart.
- `CRUSOR_TURN_CARD_RESTORATION_REPORT.md` *(this file)*.

---

## 10. Remaining limitations

1. **Legacy sessions with no request hashes and unequal counts.** If message groups and
   `turn.started` rows do not line up exactly, cards stay unassociated (kept in the store,
   warned once) rather than being guessed onto a turn.
2. **Legacy single-turn fallback is intentionally narrow.** It applies only when the hydrated
   window has exactly one turn and the store has exactly one bucket.
3. **Card placement is unchanged.** Cards still render at the end of their turn, not
   chronologically interleaved; that was explicitly out of scope.
4. **Journal paging reads the whole session journal** for each `session_messages`. Correct for
   long histories, but proportional to journal size.
5. **Pre-existing failures** remain: `test_agent_cards.py::test_all_required_card_types_are_declared`
   and the two `test_bridge.py` assertions documented previously. They were not touched.
6. **No paid-provider validation** of this path; the acceptance is provider-free.

---

## 11. Completion statement

Each Agentic card now has exactly one owner `(session, turn, card)`. Different turns keep
separate collections; identical card ids cannot collide; a session switch clears all buckets;
duplicate replay cannot duplicate; and the real Electron app restored three turns with their
original cards after a reload, a second hydration, and a full application restart.
