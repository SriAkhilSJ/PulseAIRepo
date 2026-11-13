# Crusor Agentic Timeline Report

**Task:** make the existing Agentic conversation timeline clean and chronological, hiding internal-only cards without removing verification or accounting.

| Field | Value |
|---|---|
| Branch | `feat/prompt-cache-stabilization` |
| Starting HEAD | `fb5bd528b40933346c4004a1490154683dc0d40e` |
| Final HEAD | `fb5bd528b40933346c4004a1490154683dc0d40e` (no commit) |
| New card schema / components | 0 |
| Paid provider calls | 0 (`rows=0`) |
| Electron acceptance | **PASS 40/40 checks**, three turns, reload, repeated hydration, full restart |

---

## 1. Files changed

Frontend (existing components only):

- `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAICards.ts`
  — `CRUSOR_INTERNAL_CARD_TYPES`, `isUserFacingCard`, `userFacingCards`;
  `CrusorCardStore.update` reports whether an identity is new.
- `.../browser/crusorAIRenderer.ts`
  — `CrusorAITurnPart` gains `{ kind: 'card'; cardId }`; `assistantTurn`
  renders pinned card runs in place; `agentCardStack` applies the user-facing
  policy.
- `.../browser/crusorAIRendererService.ts`
  — live card pins (`pushCardPart`), historical pins (`withCardPins`), late
  receipt cards placed before the final answer, internal/duplicate tool cards
  excluded from pins.
- `desktop/vscode/out/vs/workbench/contrib/crusorai/**` — regenerated panel
  (`node scripts/emit-crusorai-bundle.mjs`, 43 files, `SOURCES_HASH` current).

Tests / acceptance:

- `scripts/test_crusorai_cards.mjs` — policy + internal-retention assertions.
- `src/tests/test_turn_card_rendering.py` — policy/timeline source contracts (11).
- `src/tests/test_turn_card_association.py` — per-turn identity (13, unchanged).
- `desktop/vscode/scripts/accept-crusorai-progress.mjs` — hidden-card and
  chronology checks, reload/repeated-hydration/restart.
- `desktop/vscode/scripts/accept-crusorai-streaming.mjs`,
  `.../accept-crusorai-engineering.mjs` — updated to the new policy.
- `CRUSOR_AGENTIC_TIMELINE_REPORT.md` (this file).

No backend execution path, protocol, schema, orchestrator or LangGraph change.

---

## 2. Rendering policy implemented

One policy, applied to **every** user-facing card stack (live and restored
history):

```ts
CRUSOR_INTERNAL_CARD_TYPES = ['verification', 'delivery', 'cost']
isUserFacingCard(card) = !CRUSOR_INTERNAL_CARD_TYPES.includes(card.cardType)
```

| Card type | User-facing behaviour |
|---|---|
| Activity | Display |
| Plan | Display (plus the existing plan strip) |
| Tool | Display through the existing tool rows; a typed tool card is suppressed when its tool row exists, so the operation is not duplicated |
| File change | Display |
| Approval | Display (plus the existing approval dock for interaction) |
| Test results | Display |
| Verification | **Hidden** — execution and outcome remain in the model/journal/receipt |
| Delivery | **Hidden** — delivery remains the assistant report/receipt |
| Cost | **Hidden** — FinOps records remain internal |

Hidden cards are not deleted, not stripped from the model, and not removed from
the journal. `agentCardStack` filters at paint time, so historical cards of those
types are hidden during session restoration too. Unsupported/unknown card types
stay visible as the existing safe indicator.

---

## 3. Timeline ordering changes

### 3.1 Live turns — arrival-order pins

`CrusorAITurnPart` now carries card pins:

```ts
| { readonly kind: 'card'; readonly cardId: string }
```

When a **new** visible card arrives for the current turn, `pushCardPart` pins it
in the parts timeline at that point:

- the activity card pins where the first stage update arrives;
- the plan card pins at planning time;
- approval/file/test cards pin where their events arrive;
- updates to an existing card replace its data without adding a pin;
- hidden cards and typed tool cards (whose tool row already exists) are not
  pinned;
- a card that arrives **after** the final assistant text (receipt file/test
  cards) is inserted immediately before that answer, preserving arrival order
  among late cards.

`assistantTurn` flushes consecutive card pins through the existing
`agentCardStack`/`agentCardView`, so cards sit between tool runs, reasoning and
text instead of all being appended after the turn.

Observed live order for the completed acceptance turn:

```text
card:activity → card:plan → card:approval → card:file_change → text
```

### 3.2 Restored turns — stored order with two honest anchors

Checkpoint messages carry no per-tool/per-card sequence, so historical cards use
the store's first-arrival order with two anchors:

1. the **plan** card is placed early (after leading reasoning, before tools/text);
2. the remaining visible cards are placed **before the final assistant text**,
   preserving their stored order.

The final assistant answer is therefore always last, and cards are no longer a
shared bottom pile. Typed tool cards are not duplicated when the turn already has
the matching tool row.

Observed restored orders:

```text
turn 1: card:plan → card:activity → card:approval → card:file_change → text
turn 2: card:plan → card:activity → card:approval → card:approval → text
turn 3: card:plan → card:activity → card:approval → card:approval → card:approval → text
```

Per-turn ownership (`(sessionId, turnId, cardId)`) is unchanged; each turn's
timeline renders only `cardsFor(turnId)`.

---

## 4. Verification and FinOps preservation evidence

The UI policy is paint-only. Internal records still exist and carry real data.

Journal rows from the acceptance run (3 turns):

```text
activity 119, plan 26, approval 6, file_change 1,
delivery 3, verification 1, cost 3
```

while the rendered DOM reported:

```text
{"verification": 0, "delivery": 0, "cost": 0}   (live and after reload)
```

Sample journaled hidden-card data:

- verification: `{"status": "verified", "changed_files": ["notes.md"], ...}`
- delivery: `{"verdict": "COMPLETED", "files_modified": ["notes.md"], "approvals": 1, ...}`
  and the failed/cancelled variants with their real statuses.
- cost: `{"cost_inr": 0.0, "certainty": "actual", ...}` (mock mode is zero-cost;
  the FinOps fields and ledger path are unchanged).

Backend proof that verification/delivery/cost still execute and project:

- `test_phase_12_1_end_to_end_acceptance.py` — **5 passed** (full orchestrator,
  independent verification, delivery receipt).
- `test_invocation_reconciliation.py` — **13 passed** (gateway/ledger/receipt/
  cost identity).
- `test_agent_cards.py` — verification/delivery/cost projections still pass
  (only the pre-existing card-type-count assertion fails).
- No backend file was changed in this task.

---

## 5. Tests and results

All Python runs used `.venv\Scripts\python.exe` (Python 3.14.4, Windows); no paid call.

### 5.1 Node card contract — policy + retention

`node scripts/test_crusorai_cards.mjs` → **`crusorai card contract ok`**

- the store keeps all nine types, including verification/delivery/cost;
- `userFacingCards` returns only activity/plan/tool/file_change/approval/test_results;
- `isUserFacingCard` is false for the three internal types, true for the visible
  six, and true for unsupported cards (safe indicator).

### 5.2 Python suites

```text
python -m pytest src/tests/test_turn_card_rendering.py \
  src/tests/test_turn_card_association.py -q
24 passed
```

`test_turn_card_rendering.py` (11) now also pins:

- the internal-type list and `isUserFacingCard`/`userFacingCards`;
- `agentCardStack` filtering;
- `part.kind === 'card'` rendering and `flushCards`;
- `pushCardPart` / `withCardPins`;
- plan-early and before-final-text insertion;
- internal/tool card pin exclusions.

```text
python -m pytest src/tests/test_desktop_renderer_architecture.py \
  src/tests/test_bridge_protocol_v2.py src/tests/test_agent_cards.py \
  src/tests/test_turn_card_rendering.py src/tests/test_turn_card_association.py -q
161 passed, 1 skipped, 1 xfailed, 1 pre-existing failure
```

```text
python -m pytest src/tests/test_phase_12_1_end_to_end_acceptance.py \
  src/tests/test_invocation_reconciliation.py src/tests/test_agent_cards.py -q
28 passed, 1 pre-existing failure
```

The pre-existing failure is `test_agent_cards.py::test_all_required_card_types_are_declared`
(the working tree already adds `thinking`/`read`/`search` to Python `CARD_TYPES`).

Frontend:

```text
cd desktop/vscode && npm run typecheck-client
EXIT=0

node scripts/emit-crusorai-bundle.mjs
[emit] wrote 43 file(s)
```

---

## 6. Electron acceptance

`desktop/vscode/scripts/accept-crusorai-progress.mjs`, real
`desktop/vscode/.build/electron/CrusorAI.exe`, `CRUSORAI_ORCHESTRATOR_MOCK=1`,
approval policy `ask`, no provider: **PASS 40/40, `rows=0`**.

Scenario:

1. Turn 1 completed (approve the real mutation).
2. Turn 2 failed + blocked (nested target filesystem failure).
3. Turn 3 cancelled (Stop during the approval wait).
4. Workbench reload.
5. Repeated hydration / relaunch with the same profile.
6. Full application restart.

Checks specific to this task (all pass):

```text
no dedicated verification card      {"verification":0,"delivery":0,"cost":0}
no dedicated delivery card          same
no dedicated cost card              same
final assistant response follows the execution cards
  [card:activity, card:plan, card:file_change, card:approval, text]
historical verification/delivery/cost cards stay hidden
each restored turn keeps its final answer after its cards
  turn1 [plan, activity, approval, file_change, text]
  turn2 [plan, activity, approval, approval, text]
  turn3 [plan, activity, approval, approval, approval, text]
three restored turns carry distinct ids
each turn owns exactly one plan card [1,1,1]
turn 1 plan completed / turn 2 failed+blocked / turn 3 cancelled
repeated hydration identical
three turns restore after application restart
restart keeps every card in its own turn
```

Screenshots (gitignored evidence):

- `bench-results/phase-3.3-canonical-runtime/logs/electron-progress/04-complete.png`
- `.../05-failed-blocked.png`
- `.../06-cancelled.png`
- `.../05-after-reload.png`
- `.../07-restarted.png`
- `acceptance.json` / `progress-result.json` — full checks, turns, restart turns.

Note: `accept-crusorai-streaming.mjs` was updated for the new policy (it now
asserts test-result cards and hidden verification/delivery/cost), but its app
launch did not reach engine-ready in this environment (the existing pane/engine
startup flake). Test-result card rendering remains covered by
`test_agent_cards.py` projection tests and the renderer architecture tests; the
policy itself is covered by the 40/40 acceptance above.

---

## 7. Multi-turn replay regression

- Per-turn identity `(sessionId, turnId, cardId)` and `CrusorCardStore` remain
  unchanged.
- Three turns restored with distinct ids; every visible card id is prefixed by
  its own turn id.
- Reload and repeated hydration produced identical turn/card collections.
- Full restart restored all three turns with the same cards and plan statuses.
- Hidden cards remain in the journal for all three turns
  (3 delivery, 1 verification, 3 cost) but paint nothing.

---

## 8. Remaining limitations

1. **Historical chronology is anchored, not event-exact.** Checkpoint messages
   carry no per-event sequence, so restored turns place the plan early and the
   other cards before the final answer, preserving card order; they are not
   interleaved between individual historical tool calls.
2. **Typed tool cards without a matching tool row** fall back to the end of the
   turn (the existing tool row remains the primary representation).
3. **Plan strip and plan card both remain** (the strip above the transcript is
   persistent; the card is the turn record). Approval dock + approval card
   remain (interaction vs record). The task explicitly asked to keep both
   existing surfaces.
4. **Hidden cards stay in the model and store.** This is intentional for
   journals, receipts, auditing and debugging; only the paint is filtered.
5. **Reload helper can relaunch.** In this build the workbench window can close
   during a renderer reload; the acceptance relaunches with the same profile in
   that case. The first reload is real, and the explicit full-restart phase is
   separate.
6. **No paid-provider validation**; all evidence is deterministic/mock
   (`rows=0`). Pre-existing card/bridge test failures remain untouched.
