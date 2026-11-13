# CRUSOR — CONVERSATIONAL UI RESTORE (PR #31 CARD REMOVAL)

**Date:** 2026-11-11 · **Branch:** `feat/prompt-cache-stabilization` · **HEAD:** `fb5bd528`
**Scope:** frontend presentation + streaming policy only. Backend untouched.
**Provider calls:** 0 · **Ledger rows:** 0 · **Nothing committed or pushed.**

> ### Result
> The seven phase-era card surfaces are retired from the user-facing timeline by changing **one
> policy constant** plus **one defensive guard**. The workbench compiles clean and the decision is
> verified against the compiled artifact. **Electron acceptance is BLOCKED** at engine readiness
> (unchanged from the previous investigation) — so no claim is made that the pane was visually
> confirmed.

---

## 1. What changed after PR #31

Merge `631ec58a` ("Merge pull request #31 from SriAkhilSJ/feat/prompt-cache-stabilization",
2026-11-10 22:22:56 -0800), parents `7e827991… e0b0016b…`.

Frontend (first-parent diff):

| File | Δ |
|---|---:|
| `browser/crusorAIRenderer.ts` | +126 / − |
| `browser/crusorAIRendererService.ts` | +139 / − |
| `browser/media/crusorAI.css` | +157 |
| `common/crusorAICards.ts` | **+130 (new card system)** |
| `common/crusorAIProtocol.ts` / `.generated.ts` | +11 |
| `common/crusorAISessionProjection.ts` | 4 |

Backend in the same merge: `src/bridge/agent_cards.py` **new, 425 lines**; `src/bridge/__main__.py`
+849; `src/graphs/chat_graph.py` +634; `tool_policy.py` +120; `scripted_turn.py` +378.

So the card-heavy presentation is the **client half** of a card pipeline whose server half lives in
`agent_cards.py` + the bridge/orchestrator frame emitters. The conversation timeline gained a second
presentation surface: typed cards pinned as `kind:'card'` parts next to text and tool rows.

## 2. How the original conversation worked vs now

| Behaviour | Pre-PR #31 | Post-PR #31 |
|---|---|---|
| Assistant text | `token` frames appended to the last text part, painted by one rAF | unchanged |
| Streaming cadence | rAF coalescing (~60 paints/s ceiling) | unchanged |
| Tool call | inline tool row from `tool_call_start/args/end` | unchanged **plus** optional typed `tool` card |
| Tool result | inline tool row output | unchanged |
| Reasoning | collapsed thinking block | unchanged |
| Turn outcome | final markdown + receipt on `turn_done` | **also** Delivery / Verification / Cost / Activity / Plan / File-change / Test-results cards |
| Progress | pane status line | **also** Activity card, Plan card |

**The text-streaming path was never replaced** — it is the same `appendTextPart` → `render()` →
`mount.update()` chain. The regression is additive: extra card surfaces layered on top, which is why
the fix can be a presentation policy change rather than a rewrite.

## 3. What was restored

One source of truth for the transcript is restored:

- assistant markdown streamed into the conversation (unchanged pipeline),
- inline tool rows in arrival order (unchanged),
- approval dock / clarify / errors (unchanged),
- no periodic cards competing with the timeline.

### The change

`desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAICards.ts`

```ts
export const CRUSOR_INTERNAL_CARD_TYPES = [
	'activity', 'plan', 'file_change', 'test_results',
	'verification', 'delivery', 'cost',
] as const;
```

`isUserFacingCard()` is already the single gate used by **every** render path:

| Path | File : line |
|---|---|
| live pin at frame arrival | `crusorAIRendererService.ts:2325` |
| history/restored pins | `crusorAIRendererService.ts:2070` (`withCardPins`) |
| card-run painter | `crusorAIRenderer.ts:2783`, `:2916` |

Keeping `approval` and `tool` user-facing preserves the approval card and tool lifecycle.

### Verified against the compiled artifact

```
activity -> suppressed      approval -> VISIBLE
plan -> suppressed          tool     -> VISIBLE
file_change -> suppressed   test_results -> suppressed
verification -> suppressed  delivery -> suppressed
cost -> suppressed
```

Run with Node against `desktop/vscode/out/.../crusorAICards.js` — i.e. the shipped JS, not the source.

### Defensive guard (required by the change)

`crusorAIRenderer.ts` `flushCards()` appended `agentCardStack(cardRun)` directly. That function
returns `undefined` when every card in a run is internal — a state this restore makes common.
Compilation caught it (`TS2345` at `:2763`); it is now:

```ts
const stack = agentCardStack(cardRun);
if (stack) { response.append(stack); }
```

Without the guard, a turn whose only cards were suppressed would throw during paint.

## 4. Backend preserved (non-negotiable items)

Untouched and still authoritative: LangGraph turn lifecycle, `EngineeringExecutionOrchestrator`,
shared gateway + context engine, `WorkspaceMutationBroker`, `ApprovalQueue`/`RiskApprovalGate`,
TurnReceipt, FinOps ledger, checkpointing, agent event journaling, session replay, cancellation
semantics.

`agent_cards.py`, the bridge emitters and `chat_graph.py` are **not modified**: cards are still
generated, persisted, journaled and replayed. Only the presentation policy changed, so replay of an
old session shows the same text/tool/approval timeline without card stacks.

## 5. Files modified

| File | Change |
|---|---|
| `…/common/crusorAICards.ts` | retire 7 card types from presentation; comment documents the mapping |
| `…/browser/crusorAIRenderer.ts` | guard `flushCards()` against an empty/undefined card run |
| `desktop/vscode/out/…` | recompiled by `npm run compile-client` (8.88 min, exit 0) |

> The renderer file was **already dirty** (user work) before this task. My edit is limited to the
> `flushCards()` guard; the rest of that file's diff is pre-existing and preserved.

## 6. Streaming and the 160-character holdback

Holdback site: `src/graphs/chat_graph.py:4165-4171`, `_HELD_TEXT_CAP = 160`, active only for
**tools-bound** attempts (`hold_text=True`).

Why it exists (from its own comment + field note 2026-10-15): a tools-bound attempt may be discarded
(re-prompt, tool call, failover). Without the hold, the user sees a paragraph appear and vanish. Under
160 chars the text is held until the attempt's fate is known; above it the text is "certainly the
answer" and streams live.

**Assessment:** this is not the cause of the card-heavy UI, and it only delays *short pre-tool
narration*, never a normal chat answer (no tools bound → `hold_text=False` → streams immediately).
Removing it blindly would reintroduce the vanish-on-discard artifact. It was therefore **not
changed**. A protocol that marks an attempt provisional (id + replace/retract) would remove the delay
without the artifact — that is a backend design change and out of scope here.

rAF coalescing retained; no renderer optimisation added.

## 7. Tests executed (actual results)

| Command | Result |
|---|---|
| `npm run compile-client` (desktop/vscode) | **exit 0** — `tsc finished`, 731 resources, `out/` ready (8.88 min) |
| Node policy check vs compiled JS | 9/9 types as intended (7 suppressed, 2 visible) |
| `pytest test_scripted_model_pacing.py test_scripted_model_seam.py -q` | **13 passed** |
| `pytest test_agent_cards.py test_desktop_renderer_architecture.py test_turn_card_association.py -q` | **140 passed, 1 skipped, 1 xfailed, 2 failed** |

The two failures, both explained and **not** caused by this change's logic:

1. `test_agent_cards.py::test_all_required_card_types_are_declared` — the working-tree backend emits
   `thinking`, `read`, `search` card types that the test's expected set lacks. Pre-existing
   user-owned backend work (Python untouched by me).
2. `test_desktop_renderer_architecture.py::test_engine_hash_matches_the_shipped_panel_on_this_repo` —
   shipped `SOURCES_HASH` is `9f7cc07f…`; recompute over the edited sources is `7e6f5d65…`. The hash
   artifact is refreshed when the panel activates (it is not written by `gulp compile`), which cannot
   happen while Electron is blocked (§8). It will resolve on the first successful panel launch.

### Test A–F status

| Test | Status |
|---|---|
| A progressive streaming | **NOT RUN** in Electron; streaming chain unchanged, pacing seam tested at unit level |
| B tool lifecycle | **NOT RUN** (Electron) |
| C multiple tools | **NOT RUN** (Electron) |
| D failure handling | **NOT RUN** (Electron) |
| E history/replay | **NOT RUN** (Electron); backend persistence untouched |
| F card regression | **PARTIAL** — verified at policy/compiled-artifact level (`9/9`), not visually |

## 8. Electron acceptance — BLOCKED

Every launch aborts before engine readiness, identically to the previous investigation:

1. pane mounts (`textarea.crusorai-composer-input` present),
2. bridge logs `[env]`, `[bridge][acceptance]`, `[bridge][memory]`, then `engine build: unknown`,
3. **no `hello`, no `session_info`, no `[turn]`**, and no `start failed` / `handshake timed out` line,
4. by the 150 s bound the pane is gone (`probe_run5_190940/abort.png`).

Ruled out earlier: protocol mismatch (both `2`), broken handshake (bridge answers `hello` when driven
directly), missing `CRUSORAI_PYTHON_PATH`/`CRUSORAI_ENGINE_ROOT` (set), foreign port 8931 (12
bench-owned preview servers cleared). Exact blocked stage: **engine service → utility-process worker
stdout relay never yields a `hello` frame**, with the pane disposed before the 45 s handshake timeout
can report.

No acceptance result is claimed. No paid call was made.

## 9. Remaining problems

1. Engine readiness blocker (above) — gates A–F and the `SOURCES_HASH` refresh.
2. Pre-existing backend card-type test mismatch (`thinking`/`read`/`search`) in user-owned work.
3. Light theme (`B-DESK-002`) still unverified.
4. With activity/plan cards gone, progress relies on the pane status line and inline tool rows — that
   is the intended minimal indicator, but it has not been seen running.
5. The 160-char holdback still delays short pre-tool narration (documented, not changed).

## 10. Git working-tree status

```
HEAD     fb5bd528b40933346c4004a1490154683dc0d40e
branch   feat/prompt-cache-stabilization
dirty    244 entries   staged 0   untracked 1620
```

`git status` confirms `crusorAIRenderer.ts` and `crusorAICards.ts` modified; the recompiled `out/`
tree is modified as expected. No reset, clean, stash, revert, checkout of historical files, commit or
push was run. All pre-existing user modifications remain in place.
