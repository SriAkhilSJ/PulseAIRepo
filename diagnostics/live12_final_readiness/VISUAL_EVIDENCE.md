# Visual Evidence Plan

## 1. What Live11 could not prove

Live11 preserved only five screenshots: an empty panel, engine-ready, the typed
prompt, the finished turn and the final response. None showed a tool-call card
while a tool was running. The turn's event trace exists, but "the frame was
emitted" is not the same as "the card was rendered". Motion cannot be proven by
a single still image.

Therefore visual tool calling and any "breathing" animation remain **unproven**.

## 2. What LIVE12 will capture

The acceptance harness now samples the real Agent pane during the turn.

- Immediately after the submission gesture: `turn-submitted`.
- Every 20 s while the turn is not terminal: `turn-running` (bounded to 30
  samples).
- Once the terminal frame is observed: `turn-terminal`.

Each sample stores, in `evidence.json` under `visual`:

| Field | Meaning |
|---|---|
| `panel.tool_rows` | number of `.crusorai-tool-row` cards in the DOM |
| `panel.running_rows` | cards currently marked `.is-running` |
| `panel.activity_rows` | the single tail activity row while a turn runs |
| `panel.streaming_messages` | assistant messages marked `.is-streaming` |
| `panel.plan_live` | live plan indicator elements |
| `screenshot` | `screenshots/turn-NN.png`, a full-pane capture |

Sampling is best-effort: a CDP or disk failure is recorded as
`panel_error`/`screenshot_error` and never aborts the paid turn.

## 3. How the result will be judged

- **Tool calling visibly rendered** requires a mid-turn sample with
  `tool_rows > 0` (or a `running_rows > 0`) and the matching screenshot, plus
  event-trace agreement. A final screenshot alone is insufficient.
- **Breathing/animation** is judged honestly: the DOM classes and the CSS
  animation rules can be shown to have been applied, but static images cannot
  prove perceived motion. It will be reported as "animation class observed" or
  "not observed", never as subjective motion proof.
- If no tool card appears in any sample while tool events exist, that is a
  **visual rendering failure**, reported as such even if the task passes.

## 4. Current status

Not collected. LIVE12 has not run. Visual success is not claimed.

The sampler is covered by `src/tests/test_live12_readiness.py`
(`TestVisualSampling`): it records panel counts, is bounded, and tolerates CDP
failure.
