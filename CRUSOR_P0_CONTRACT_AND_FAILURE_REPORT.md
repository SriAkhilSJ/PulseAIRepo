# Crusor P0 — Contract Extraction and Honest Failure States

**Date:** 2026-11-11
**Branch:** `feat/prompt-cache-stabilization` · **Starting HEAD:** `fb5bd528b40933346c4004a1490154683dc0d40e`
**Working tree at start:** 217 entries, 0 deletions (all pre-existing work preserved; no commit, no reset/stash/revert).
**Scope:** the two P0 defects from `CRUSOR_COMPLETE_FRONTEND_ARCHITECTURE_AUDIT.md`. No streaming (P1) work, no redesign, no new card schema, no provider calls.

Verdict: **PASS for the P0 definition of done.** Natural-language requests reach planning; a failed turn is always presented as failed; restored turns never invent success. Both are demonstrated in the real Electron app with a deterministic, provider-free fixture.

---

## 1. Root causes

### 1.1 B-LIVE-001 — the contract extractor did not read prose

`parse_prompt_contract` extracted a callable only when its name followed the literal token `def` or `function`:

```python
re.finditer(r"\b(?:def|function)\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", text)
re.finditer(r"\b(?:public\s+)?function\s+([A-Za-z_]\w*)\b", text)
```

The ordinary English order — *"implement a divide(a, b) function"* — matches neither. `fields["symbols"]` stayed empty, and the gate at `src/orchestration/contract.py:522` then rejected the request:

```
contract ambiguity: no public symbol is specified for the requested function
```

That is the failure that ended the real-provider Test A in 8.6 s with **zero provider calls, no plan, no tools, no edits**.

### 1.2 B-LIVE-002 — a failed turn could paint as a success

The bridge sends `turn_done` with `completed: false` (`src/bridge/__main__.py:1724-1729`, derived from `AgentTurnResult.completed`). The renderer ignored that flag:

```ts
this.turnOutcome = frame.cancelled ? 'cancelled' : 'completed';
if (canonical?.terminal_status) { /* receipt could override */ }
```

A failure has no receipt (`src/graphs/chat_graph.py:5448-5454` returns no `engineering_delivery`), so `turn_done{completed:false}` became **completed**. The failure text had already arrived as an assistant chunk, so the UI showed a confident answer whose content was an error — no failed row, no error styling.

The same untruth existed on restore: `hydrateTranscript` hardcoded `turnOutcome: 'completed'` for every turn and `state: 'passed'` for every tool (`crusorAIRendererService.ts:1438,1487`), regardless of what actually happened.

---

## 2. Contract extraction changes

**File:** `src/orchestration/contract.py`

The extractor now scans **clauses** (sentence/semicolon/newline boundaries) with five narrow patterns, in this order:

| # | Pattern | Example it serves |
|---|---|---|
| 1 | `def|function|method NAME(args)` | `function parse_duration(value)`, `def divide(a, b)` |
| 2 | `NAME(args) … function|method` | **Implement a divide(a, b) function** |
| 3 | `function|method called|named NAME` | **Add a function called divide**, `Add a Python function named clamp` |
| 4 | `public|python|helper? function|method NAME` | **Implement the public method `divide`** |
| 5 | bare `NAME(args)` **only in a creation clause** | **Create divide(a, b) in the existing package** |

Guards that keep it from becoming "extract everything":

- **Creation cue required for bare calls** (`implement|add|create|write|define|introduce|export|expose|build|provide|include|support|make`). Without it, `parse_duration(value)` in prose is not a new request.
- **Preservation/negation window.** A match is dropped when a cue (`preserve|keep|retain|maintain|leave|without|do not|don't|never|avoid|must not|should not|unchanged|intact`) governs it within the preceding 60 characters of the same clause. `"Keep the existing divide implementation intact"` and `"Do not add a function called remove"` extract nothing; `"…and keep add() unchanged"` suppresses only `add`.
- **Parameter-shape validation.** A bare call is accepted only when every parameter looks like an identifier/default (`a`, `b: float`, `*args`). This rejects `pytest -q`, `python -m pytest`, `range(0, 10)` and similar.
- **Stopword set** for prose names (`that`, `returns`, `public`, `function`, builtins, common CLI words). Explicit declarations bypass it — writing `def main(x)` is unambiguous.
- **Ambiguity rules untouched.** "More than one symbol plus *public function*" still reports a conflict; "the word function with no symbol" still reports `no public symbol`. `validate_contract_plan` and every dispatch/budget/approval guard are unchanged.

Extracted signatures feed the same `ContractComponent` fields as before (`symbols`, `signatures`), so source and test generators see the corrected API.

---

## 3. Failure-state changes

### 3.1 One pure decision module

**New:** `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAITurnOutcome.ts` (DOM-free, import-free — executable by a test).

| Signal | Outcome |
|---|---|
| `cancelled: true` | `cancelled` (a user stop wins over every label) |
| receipt `COMPLETED / CANCELLED / DENIED / FAILED / INCOMPLETE / INTERRUPTED / WATCHDOG` | mapped exactly |
| evidence status (no receipt) | `watchdog|interrupted → incomplete`, `failed → failed`, etc. |
| `completed: true` | `completed` |
| `completed: false` | `failed` |
| nothing | **`unknown`** |

`restoredTurnOutcome(outcomes, turnId)` returns the durable outcome or `unknown`; it never upgrades a missing record. `turnOutcomeReceipt()` is the single source of the user-visible labels (`Run failed`, `Run cancelled`, `Run denied`, `Run incomplete`, `Outcome not recorded`) and returns nothing for `completed`/`running`/`idle`.

### 3.2 Service wiring

**File:** `browser/crusorAIRendererService.ts`

- `turn_done` now derives `turnOutcome` from cancellation → canonical receipt → evidence status → `completed` → unknown. `turn_failed` stays `failed`.
- A failed/incomplete turn stores the terminal message in `this.error` (the existing error row) and **does not append it as assistant prose**.
- `dropDuplicatedFailureText()` removes a byte-identical chunk that streamed before the terminal frame, so the failure is painted once — as a failure — instead of as a confident paragraph plus an error box. Partial work that differs from the failure message is preserved.
- The completion toast is now honest: a failed turn notifies with `isError=true` instead of "Response Ready".
- No new card, receipt, or protocol type was introduced.

### 3.3 Renderer

**File:** `browser/crusorAIRenderer.ts`

- The two duplicated receipt blocks were replaced by one `turnReceiptRow(outcome, interrupt)` using `turnOutcomeReceipt()`; landed/dropped counts are preserved.
- `incomplete` and `unknown` render with their own labels and muted tones (`media/crusorAI.css`: `.is-incomplete`, `.is-unknown`); `completed` still renders nothing.
- Tool state gained `recorded` (label "Recorded", history glyph) for restored calls: the checkpoint proves the call happened, not that it succeeded.

---

## 4. Historical restoration

**Bridge** (`src/bridge/__main__.py`):

- `_turn_outcomes(events)` maps the journal's durable terminal rows to `turnId → completed|failed|cancelled|incomplete`. The journal already writes exactly one terminal row per turn (`TurnEvidenceRecorder.finalize`, `src/runtime/evidence_capture.py:1279-1325`); no new event type was added.
- `session_messages` now carries the optional `turn_outcomes` map (additive field; declared in `common/crusorAIProtocol.ts`).

**Renderer**:

- `hydrateTranscript(messages, turnOutcomes)` attaches `restoredTurnOutcome(...)` to each turn: durable outcome when present, `unknown` otherwise.
- Hydrated tools are `recorded`, never `passed`.
- Legacy journals without terminal rows (or without the field) produce `unknown` — the turn shows "Outcome not recorded" rather than a success claim. Backward compatible: absent field, absent entry, and unrecognised values all degrade to `unknown`.

The existing per-turn card ownership, plan-card placement, and internal-only card policy are untouched.

---

## 5. Tests and results

All commands run from the repo root with `.venv\Scripts\python.exe` (Python 3.14.4) or Node 24.18.0. No paid calls.

### 5.1 Contract extraction — new `src/tests/test_contract_natural_language.py`

**20 passed.** Covers the mission's matrix:

| Requirement | Test |
|---|---|
| Name before argument list | `test_name_before_argument_list_is_extracted` |
| Name after the word function | `test_natural_language_forms_extract_the_named_callable[Add a function called divide.]` |
| Explicit symbol names | `[Implement the public method \`divide\`.]`, `[Implement a public function divide(value).]` |
| Multiple requested symbols | `test_multiple_requested_symbols_keep_their_signatures` |
| Existing symbols preserved | `test_preservation_and_negation_clauses_are_not_requests` |
| Negative instructions | same, `Do not add a function called remove.` |
| Ambiguous requests | `test_no_symbol_for_a_public_api_still_rejects`, `test_conflicting_public_symbols_still_reject` |
| Unrelated identifiers | `test_unrelated_identifiers_are_not_symbols` (units, README, pytest, builtins) |
| Natural-language multi-file | `test_natural_multi_file_request_keeps_roles_and_symbols` |
| The live failing prompt | `test_the_live_divide_prompt_passes_contract_validation` |
| LIVE7 regression | `test_historical_live7_prompt_is_unchanged` |

### 5.2 Outcome semantics — new `scripts/test_crusorai_turn_outcome.mjs`

Executes the real module (not a source match): **`crusorai turn-outcome contract ok`**. Covers completed / failed / cancelled / receipt authority / evidence authority / watchdog / missing-evidence / restoration / unknown-not-success / 5 receipt labels.

### 5.3 Outcome wiring — new `src/tests/test_turn_outcome_semantics.py`

**8 passed.** Bridge mapping (including "first terminal wins", "no turn id", "no terminal row"), plus the renderer wiring (no `frame.cancelled ? … : 'completed'`, no `'completed' as const`, `recorded` tools, `turn_outcomes` declared).

### 5.4 Regression suites

| Suite | Result |
|---|---|
| `test_p0_6_8_contract_first.py` | **44 passed** |
| `test_contract_assignment_reliability.py` + `test_scope_fidelity.py` + `test_phase_11_6_autonomous_execution.py` | **65 passed** |
| `test_desktop_renderer_architecture.py`, `test_agent_cards.py`, `test_turn_card_rendering.py`, `test_turn_card_association.py`, `test_bridge_protocol_v2.py`, `test_desktop_session_pipeline.py`, `test_turn_outcome_semantics.py`, `test_contract_natural_language.py`, `test_p0_6_8_contract_first.py`, `test_contract_assignment_reliability.py` | **267 passed, 1 skipped, 1 xfailed, 1 failed** |
| `typecheck-client` | **exit 0** |
| panel emitter | **44 files** |
| `node scripts/test_crusorai_cards.mjs` | **ok** |

The single failure is pre-existing and unrelated: `test_agent_cards.py::test_all_required_card_types_are_declared` compares the Python allowlist (which declares `thinking`, `read`, `search` in the working tree) with the nine-type TypeScript schema. It failed identically before this task; recorded as B-LIVE-005 in the tracker rather than fixed here.

Three existing tests were updated because they encoded the old contract, not because behaviour was weakened:

- `test_desktop_renderer_architecture.py` asserted `"Run cancelled" in renderer` and the literal old rule `frame.cancelled ? 'cancelled' : 'completed'`. Both moved to the outcome module.
- `test_desktop_session_pipeline.py` / `test_turn_card_rendering.py` asserted the old `hydrateTranscript(messages)` signature and `turnOutcome: 'completed' as const`.

---

## 6. Electron acceptance evidence

**New:** `desktop/vscode/scripts/accept-crusorai-p0.mjs` — real `desktop/vscode/.build/electron/CrusorAI.exe`, real bridge, real canonical runtime, real orchestrator contract gate, `CRUSORAI_ORCHESTRATOR_MOCK=1` (the **model adapter** is the mock; nothing else is). No provider call; the run asserts `rows=0`-equivalent conditions by construction.

Disposable workspace: `src/mini_math/ops.py`, `tests/test_ops.py`, `README.md`.

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Successful turn reaches planning | PASS | plan card, verdict `COMPLETED`, report in the transcript |
| 2 | Successful turn produces assistant output | PASS | Engineering Execution Report text |
| 3 | Successful turn has no failure receipt | PASS | `[]` |
| 4 | Successful turn is not labelled unknown | PASS | `[]` |
| 5 | **Natural-language request reaches planning** | PASS | plan strip `task_ops ✓`, `task_verification ✓` |
| 6 | **Not rejected as ambiguous** | PASS | no `no public symbol` anywhere |
| 7 | Natural-language turn is not labelled unknown | PASS | one `is-failed` receipt (mock implementation failure, see below) |
| 8 | **Genuine ambiguity still fails at the gate** | PASS | `plan rejected before dispatch: contract ambiguity: no public symbol…` |
| 9 | **Failed turn renders a failed receipt** | PASS | new `is-failed` row ("Run failed") |
| 10 | **Failure shown in the error row** | PASS | error row carries the backend message |
| 11 | Failure not painted as assistant prose | PASS | no turn section contains the failure text |
| 12 | Failed turn not labelled unknown | PASS | no `is-unknown` |
| 13 | Three turns restored | PASS | 3 |
| 14 | Successful turn restores without a failure row | PASS | first turn `[]` |
| 15 | **Failed turn restores as failed** | PASS | last turn `is-failed` |
| 16 | Failed turn does not restore as unknown | PASS | no `is-unknown` / `is-incomplete` |

**Verdict PASS, 16/16.** Screenshots in `bench-results/phase-3.3-canonical-runtime/logs/electron-p0/`:
`01-agent-ready.png`, `02-successful-turn.png`, `03-natural-language-turn.png`, `04-ambiguous-turn.png`, `05-after-reload.png`; machine-readable `acceptance.json`.

**Important honesty note.** Turn 2 (the divide request) *passed the contract gate and planned successfully* (both plan steps completed), then **failed during mock implementation** (`FAILED`, 1 landed mutation, a cross-file contract violation and a missing test dependency). That failure is the mock adapter's, not the gate's — and it produced exactly the honest UI this milestone requires: `Run failed · 1 landed` rather than a completion. It also doubles as a real-UI demonstration of requirement 5 (failed turn without a successful receipt).

### 6.1 Existing acceptance did not regress

`accept-crusorai-progress.mjs` (three turns, plan outcomes, hidden internal cards, reload, repeated hydration, full application restart): **PASS 40/40**, `rows=0`. The new failed receipt coexists with the existing plan/activity/approval rendering; card ownership and final-answer ordering are unchanged.

---

## 7. Remaining limitations

1. **Live failure text is shown once, in the error row; restored failure text is shown as transcript content plus the `Run failed` receipt.** The checkpoint persists the failure as an AI message, and the bridge does not mark that message as an error, so after reload it appears as the turn's text with the failed receipt directly after it. It is never presented as success, but the two presentations differ. Closing this needs a per-message error flag in the checkpoint projection (out of P0 scope).
2. **`unknown` is visible on genuinely legacy sessions.** Journals written before terminal lifecycle rows existed have no outcome map, so those turns show "Outcome not recorded". This is the required conservative behaviour, not a defect, but it is visually new for old sessions.
3. **Nothing in this milestone was exercised with a real provider.** All Electron evidence is `ORCHESTRATOR_MOCK=1`. Real-provider qualification remains `FAIL` in `CRUSOR_REAL_PROVIDER_E2E_QUALIFICATION.md` until a new budgeted run.
4. **B-LIVE-003 (streaming) is untouched.** Engineering turns still emit one summary chunk; no P1 work was started, per the mission.
5. **Pre-existing test failure** `test_agent_cards.py::test_all_required_card_types_are_declared` (Python/TS card-type drift) remains; it is unrelated to P0 and was not "fixed to green".
6. **The watchdog/incomplete path is unit-tested but not exercised end-to-end.** The Electron fixture covers failed and successful turns; `incomplete` is covered by the pure decision test and the bridge mapping test.
7. **First-run Copilot modal.** A fresh Electron profile can open Copilot's sign-in dialog over the workbench; the P0 harness dismisses it explicitly. This is a harness concern, not a product change.

---

## 8. Definition of done — mapping

| Requirement | Status | Evidence |
|---|---|---|
| "Implement a divide(a, b) function" passes contract checks | Met | Python gate test + Electron plan strip |
| A failed turn always appears failed | Met | Electron checks 8-12, live and after reload |
| A restored conversation never portrays failure/unknown as success | Met | `restoredTurnOutcome`, `turn_outcomes`, Electron 13-16, node test |
| Demonstrated in the actual frontend | Met | `accept-crusorai-p0.mjs` PASS 16/16 |
| No P1 streaming work | Met | no streaming code touched |

**Deliverable:** this report. Tracker updated: `docs/BUGS_AND_LIMITATIONS.md` (B-LIVE-001 fixed, B-LIVE-004 fixed, B-LIVE-002/003 still open, B-LIVE-005 recorded).
