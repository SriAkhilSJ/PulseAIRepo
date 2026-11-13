# OpenCode Execution Architecture vs Crusor

**Status:** source-grounded comparison, read on 2026-11-11 from `github.com/anomalyco/opencode`, branch `dev`.
**Constraint honoured:** Crusor source was not changed as a result of this comparison.

---

## 0. Where the files actually are

The paths named in the mission (`packages/opencode/src/session/{message,processor,session}.ts`)
no longer exist on `dev`. The repository was restructured; `packages/opencode` is gone and the
session core lives in `packages/core`, with the wire schemas in `packages/schema`.

Resolved via the git tree API (`/git/trees/dev?recursive=1`, 12,463 entries):

| Mission path | Actual path on `dev` | Role |
|---|---|---|
| `session/message.ts` | `packages/schema/src/session-message.ts` (+ 2-line re-export at `packages/core/src/session/message.ts`) | assistant message + part schemas |
| `session/processor.ts` | *(no equivalent)* split into `packages/core/src/session/message-updater.ts` (event → message projection), `projector.ts` (persistence adapter), `runner/{llm,step,publish-llm-event}.ts` (generation loop) | streaming / part updates |
| `session/session.ts` | `packages/core/src/session/session.ts` (+ `store.ts`, `history.ts`) | session lifecycle, message store, restore |

Treating the mission's paths as authoritative would have produced a fabricated comparison. The
answers below cite the files that actually implement each behaviour.

---

## 1. How OpenCode represents an assistant message as ordered parts

An assistant message is one row with an **ordered array**, not a set of keyed children:

```ts
// packages/schema/src/session-message.ts:220-248
Assistant = {
  id, type: "assistant", agent, model,
  content: AssistantContent[],        // ORDER IS THE TIMELINE
  snapshot, finish, rawFinish, native, cost, tokens, error, retry,
  time: { created, firstToken, streamed, completed },
}
```

`AssistantContent` is a tagged union of exactly three kinds
(`session-message.ts:203-206`):

```ts
Union([AssistantText, AssistantReasoning, AssistantTool])   // discriminator: type
```

- `AssistantText { type:"text", text, native? }`
- `AssistantReasoning { type:"reasoning", text, native?, time?:{created,completed?} }`
- `AssistantTool { type:"tool", id, name, executed?, native?, state, time:{created,ran?,completed?} }`
  with `state` a second tagged union over `status`
  (`streaming | running | completed | error`, `session-message.ts:165-168`).

Consequences that matter for a renderer:

1. **Order is positional.** Rendering iterates `content` in array order. There is no
   `parent`/`after` pointer and no separate timeline table.
2. **Tool identity is explicit, other parts are not.** A tool part carries the provider
   `callID` in `id`; text and reasoning parts carry no id at all.
3. **The message, not the part, owns the accounting.** `cost` and `tokens` sit on the
   assistant message (per step), as do `finish`, `error` and `retry`.

---

## 2. How text, reasoning and tool calls are persisted

Two storage shapes, one logical model (`projector.ts:500-601`):

- **Inline (default):** the parts array is JSON inside `session_message.data.content`.
- **Part rows (`experimental.part_rows`):** one row per part in `session_part`
  (`message_id`, `ordinal`, part JSON). `withParts` joins them back ordered by
  `(message_id, ordinal)` (`history.ts:96-130`).

What is written when (`message-updater.ts:300-417`):

| Event | Persistence effect |
|---|---|
| `session.step.started` | creates the assistant row with `content: []`, `model`, `agent` |
| `session.text.started` | appends an **empty** `text` part |
| `session.text.ended` | sets the **full** text on that part (the replayable boundary) |
| `session.reasoning.started` / `.ended` | same pattern; `ended` also stamps `time.completed` |
| `session.tool.input.started` | appends a tool part in `state:"streaming"` with the `callID` |
| `session.tool.input.ended` | fills the raw streamed input string |
| `session.tool.called` | `state → running` with parsed `input`, stamps `time.ran` |
| `session.tool.success` | `state → completed` with `content[]`, stamps `time.completed` |
| `session.tool.failed` | `state → error` with `error` + partial content |
| `session.step.ended` / `.failed` | writes `finish`, `cost`, `tokens`, `native`, snapshot |

Deltas are **never** persisted. `session.text.delta`, `session.reasoning.delta`,
`session.tool.input.delta` and `session.tool.progress` are declared
`Event.ephemeral` (`session-event.ts:420-542`); the schema comment is explicit:
*"Stream fragments are live-only; Text.Ended is the replayable full-value boundary."*
This is why replay can never show half a sentence: the stream is transient UI state, the
part is a complete value.

Writes are incremental, not whole-message rewrites: `projector.ts:500-537` compares each
part to the stored row and only updates changed ordinals, deleting trailing stale rows.

---

## 3. How stable part IDs preserve ordering

There are three distinct identity layers, and conflating them is the classic mistake:

1. **Message id** — `msg_` + monotonic `ascending()`; for projected events,
   `SessionMessage.ID.fromEvent(event.id)` maps `evt_… → msg_…`
   (`session-message.ts:21-28`). Replaying the same event id yields the same message id:
   projection is idempotent.
2. **Tool part id** — the provider `callID`, unique within the message. Every tool event
   addresses the part by `{ type:"tool", callID }` (`message-updater.ts:324-395`).
3. **Ordinal** — the positional slot (`session_part.ordinal`). This, not a part id, is
   what orders text and reasoning.

Text/reasoning have **no stable id**; they are matched by *type* against the most recent
eligible part:

```ts
// projector.ts:585-596
draft.content.findLast(item =>
  item.type === match.type &&
  (match.callID === undefined || (item.type === "tool" && item.id === match.callID)) &&
  (!match.incompleteReasoning || (item.type === "reasoning" && !item.time?.completed)))
```

`incompleteReasoning` exists so a re-generated reasoning block does not overwrite a
completed one; a new `reasoning.started` appends a fresh part and `ended` finds the last
*incomplete* one. Ordering therefore survives because appends are the only structural
mutation — updates never reorder.

---

## 4. How streaming updates modify existing parts

Two channels, deliberately separated:

- **Live channel (ephemeral).** Deltas carry `assistantMessageID` **and `ordinal`**
  (`session-event.ts:420-427`), so the client appends the fragment to the part at that
  ordinal. No id lookup, no inference from text content.
- **Durable channel.** Coarse boundaries (`started`, `input.ended`, `called`, `success`,
  `failed`, `ended`) mutate the projected message, which is what a later replay reads.

There is also a legacy full-array replacement, `session.message.content.updated`
(`session-event.ts:147-158`, `message-updater.ts:93-94`), explicitly marked
*"Replay-only: older releases allowed replacing completed assistant content."* New writes
do not use it. It exists so old journals still decode.

Net effect: the renderer's fast path is *fragment → (message, ordinal)*; the durable path
is *event → projected part*. Neither path re-derives order from timestamps.

---

## 5. How session events reach the frontend

Three layers, no direct model→UI coupling:

1. **Events.** `Durable` and `All` unions in `session-event.ts:722-739`; every event has a
   type, an id and `created`.
2. **Projection.** `message-updater.update(adapter, event)` is a `Match` over durable
   events that mutates message state through the `Adapter` interface
   (`message-updater.ts:6-35, 86-494`). Ephemeral events are not projected at all — they
   are forwarded.
3. **Transport.** Clients read projected state (`SessionStore.messages/context/message`)
   and receive live events over the bus; the server handlers are
   `packages/server/src/handlers/{message,session}.ts`.

The important property: **the persisted message is a projection, not the source of truth.**
The source of truth is the event stream; the message table is a materialized view that can
be rebuilt. That is what makes crash/resume and replay safe (`store.ts:74-91` keeps an
execution claim precisely so an interrupted turn is identifiable).

---

## 6. How historical messages restore their original parts

Restoration is *decode of the same value*, not a re-interpretation:

```ts
// history.ts:96-130 (withParts)
select … from session_part
  where message_id in (…)
  order by message_id asc, ordinal asc
// then splice rows back into content[]
```

- Part rows are re-attached to their message in ordinal order; inline messages are used
  as-is.
- `SessionBlob.hydrate` restores media (`media:<sha256>` refs) before decode
  (`history.ts:153-168`).
- The decoded value is the same `AssistantContent` union the live projector writes, so
  live and restored renders run the same code.
- Paging is cursor-based on a monotonic `seq` (`store.ts:102-135`), not on timestamps.

Because the durable boundaries hold *full values*, a restored transcript is byte-identical
to the last durable state — including partial tool output on failure, which is carried in
`state:"error"`'s optional `content`.

---

## 7. Crusor today (for comparison)

Crusor is event-sourced too, but its journal feeds **two** projections instead of one.

| Concern | OpenCode | Crusor (current tree) |
|---|---|---|
| Source of truth | session event stream (`durable`/`ephemeral`) | `runtime_events` table in `runtime_events.db`, monotonic `seq`, hash-chained (`src/runtime/event_journal.py`) |
| Assistant timeline | `content[]` of tagged parts | `CrusorAITurnPart[]` union `text \| tool \| reasoning \| card` in `crusorAIRendererService.ts`, plus parallel `reasoningParts[]` |
| Part identity | tool `callID`; text/reasoning positional | `toolId` for tools; reasoning by index; cards by `cardId` |
| Second projection | none (cards are not a separate type) | `CrusorCardStore` keyed `(turnId, cardId)` — plan, activity, approval, file_change, test_results, tool, and internal-only verification/delivery/cost (`crusorAICards.ts`) |
| Streaming | ephemeral deltas keyed by `(messageID, ordinal)`; durable full-value boundaries | bridge frames; text appended into the last `text` part; tool updates by `toolId`; card updates replace by `(turnId, cardId)` |
| Ordering, live | array append order | arrival-order pins: `pushToolPart`, `pushCardPart`; a late receipt card is spliced before the final text |
| Ordering, restored | ordinal from `session_part` | **anchored**: checkpoint messages carry no per-event sequence, so `withCardPins` puts the plan early and the remaining cards before the final assistant answer, preserving stored order |
| Renderer contract | one part list | parts list + card list, with a single user-facing filter (`isUserFacingCard`) hiding verification/delivery/cost at paint time while keeping them in the model, journal, receipts and FinOps |

### 7.1 Where Crusor is equivalent

- Ordering is **positional**, not timestamp-sorted, on both sides.
- Tool identity is **explicit and stable** on both sides (`toolId` / `callID`).
- Live updates mutate existing entries in place; nothing is re-created per token.
- The durable record is independent of the render: hiding a card never deletes it
  (journal evidence from the timeline task: 3 delivery + 1 verification + 3 cost cards
  journaled while the DOM rendered 0).
- Per-turn isolation exists in both models, by different keys: OpenCode scopes parts to a
  `messageID`; Crusor scopes cards to `(turnId, cardId)` and renders only
  `cardsFor(turnId)`.

### 7.2 Where Crusor differs, and the cost of the difference

1. **Crusor has a second projection.** Cards are not part of OpenCode's message model at
   all. That buys typed UI (plan steps, approval state, test results) but creates a second
   ordering problem: `content[]` order and card order must be merged. The renderer solves
   it with pins, and the pins are the only place where ordering can drift.
2. **Crusor's live stream is not ordinal-addressed.** OpenCode's delta carries `ordinal`,
   so a fragment always lands on the right part even under interleaving. Crusor appends to
   `parts[parts.length-1]` when it is text (`appendTextPart`), which is correct only
   because the bridge emits token frames in order. It is an implicit invariant, not an
   encoded one.
3. **Crusor's restore is anchored, not ordinal-exact.** The journal does have a `seq`, but
   the renderer hydrates from checkpoint messages whose payload carries
   `userMessage / assistantText / parts / tools` and no per-card sequence. Historical
   placement is therefore plan-early + cards-before-final-answer. OpenCode does not have
   this problem because its persisted part array *is* the order.
4. **Accounting placement.** OpenCode attaches `cost`/`tokens`/`retry` to the assistant
   message, so accounting travels with the step it belongs to. Crusor projects a separate
   `cost` card and keeps it internal-only — correct for the UI requirement, but the ledger
   is the accounting truth, not the card.
5. **Identity derivation.** OpenCode derives ids deterministically from event ids
   (`fromEvent`). Crusor derives card ids from `(turnId, kind, discriminator)`
   (e.g. `turn-…:receipt:file:0`) and tool ids from the bridge. Neither is wrong; Crusor's
   ids are stable per turn but not globally meaningful outside it.

### 7.3 What this comparison suggests (not implemented, per the mission)

- Encode the ordinal in Crusor's text/tool frames the way OpenCode does, and the
  "anchored history" limitation disappears without a schema change to cards.
- If event-exact history is ever required, the cheapest correct step is to persist the
  journal `seq` (already present) into the checkpoint message parts at hydration time.

Neither is part of this qualification and neither was applied.

---

## 8. Bottom line

OpenCode's guarantee is structural: **one ordered array of tagged parts, mutated only by
append and addressed update, fed by an event stream whose deltas are ephemeral and whose
boundaries are full values.** Everything else — streaming, replay, crash resume, renderer
simplicity — follows from that.

Crusor matches the part model and adds a typed card projection with per-turn ownership and
an explicit user-facing filter. Its ordering guarantee is equally strong for live turns,
and intentionally weaker (anchored) for historical turns, because the hydration payload does
not carry the per-event sequence that the journal already has.
