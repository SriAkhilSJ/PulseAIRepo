# Bridge Transport Failure Resolution

## 1. Failing test

`src/tests/test_bridge_transport.py::test_turn_done_survives_a_undrained_event_queue`

The test publishes one event with the forwarder disabled, forces a flush strand,
and asserts:

1. `turn_done` is the last frame;
2. a `runtime_degraded` frame reports the strand;
3. `"undrained"` is in that frame's `reason`.

## 2. Observed failure

In this checkout, `TurnEvidenceRecorder` begins the turn with a **degraded**
receipt (missing build identity in a large dirty workspace). The bridge emits an
honest evidence-degradation `runtime_degraded` frame before the strand frame.
The test used:

```python
degraded = next(f for f in emitted if f["type"] == "runtime_degraded")
```

so it selected the evidence warning, not the strand. The failure is a
test-selection defect, not a production queue failure.

## 3. Baseline proof

A recorded baseline run with `src/bridge/__main__.py` from `6959c862` (the
parent of the Live11 repair) reproduces the same failure:

```text
FAILED test_turn_done_survives_a_undrained_event_queue
AssertionError: 'undrained' not in
  'Agent Core evidence capture is degraded; ...'
```

Evidence: `diagnostics/live12_acceptance/baseline_bridge_failure.log`.
The file was restored and SHA-verified. The failure is pre-existing.

## 4. Fix

The assertion now targets the frame under test:

```python
degraded = next(
    f for f in emitted
    if f["type"] == "runtime_degraded"
    and "undrained" in str(f.get("reason") or "")
)
assert "undrained" in degraded["reason"]
```

No assertion was weakened: the terminal-frame order, the presence of the strand
frame, and the `undrained` reason are all still required. No timeout was
increased, no test deleted/skipped/xfailed. Production behavior is unchanged.

## 5. Result

- Isolated: **1 passed** (17.78 s).
- Full suite: **359 collected, 359 passed** in 573.05 s (see
  `RELIABILITY_REGRESSION_RESULTS.md`).
