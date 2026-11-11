# Acceptance Harness Repair (offline)

## 1. Contradiction found by preflight

LIVE12 mandates `CRUSORAI_AUTOTITLE=off` with an auxiliary ceiling of ₹0.00,
but the acceptance harness still required titling to happen:

| Harness requirement | Location (before) | Effect with titling off |
|---|---|---|
| `len(aux_settled) >= 1` | `live_acceptance.py:647` | impossible — no title call exists |
| non-empty `session_title` | `live_acceptance.py:663` | impossible — title is never generated |
| 90 s auxiliary wait | `live_turn.py:512` | burns the full timeout, returns no records |

Result: a technically perfect LIVE12 run would have returned
`P0.6.9_ACCEPTANCE_FAILED`. The blocker was in the harness, not in the repaired
bridge.

## 2. Repair (stricter, not weaker)

`benchmarks/crusor_desktop_acceptance/live_turn.py`

- `autotitle_disabled()` — one shared definition of `0/off/false/no`
  (case/space insensitive), matching `BridgeServer._auxiliary_llm_allowed()`.
- `wait_for_auxiliary_accounting(..., expected=False)` returns immediately with
  `{"records": [], "waited": false, "skipped": "auxiliary_disabled"}`.

`benchmarks/crusor_desktop_acceptance/live_acceptance.py`

- `finish()` captures `state.autotitle = {disabled, value}` before shutdown and
  passes `expected=not autotitle_off` to the auxiliary wait.
- `_verdict()` for titling off:
  - `aux_ok = not aux_records` — **zero** `session_titling` records required;
    any title invocation is an unauthorized auxiliary dispatch and fails;
  - `title_ok = True` — the empty title is expected, not tolerated silence;
  - titling-enabled runs keep the original `len(aux_settled) >= 1` and
    non-empty-title gates;
  - gate inputs are recorded in `state.auxiliary_gate`.

Because titling-off demands zero title records, the repair cannot hide a title
call. It only stops the harness from demanding a call the run is forbidden to
make.

## 3. Verdict naming

The harness keeps its historical `P0.6.9_*` strings (existing tests and
historical evidence depend on them). `LIVE12_ACCEPTANCE_PROCEDURE.md` §6 maps:

```text
P0.6.9_ACCEPTANCE_PASSED  -> LIVE12_ACCEPTANCE_PASSED
P0.6.9_ACCEPTANCE_FAILED  -> LIVE12_ACCEPTANCE_FAILED
P0.6.9_ACCEPTANCE_BLOCKED -> LIVE12_ACCEPTANCE_FAILED
missing/unreconciled      -> LIVE12_INCONCLUSIVE
```

No historical verdict is rewritten.

## 4. Tests

`src/tests/test_live12_readiness.py`:

| Test | Proves |
|---|---|
| `test_harness_and_bridge_agree_on_off_values` | harness and bridge accept exactly the same off-values |
| `test_auxiliary_wait_is_skipped_when_titling_disabled` | no 90 s burn; returns in <2 s |
| `test_title_off_with_zero_title_calls_passes` | titling-off run with zero title calls passes |
| `test_title_off_with_a_title_call_fails` | any `session_titling` record fails |
| `test_title_enabled_still_requires_a_settled_title_call` | original gate preserved |

Existing `TestVerdictGates` (9 tests) and `TestAuxiliaryWaitHelper` still pass,
so the titling-enabled path is unchanged.

## 5. Scope

No bridge, FinOps, ledger, submission or desktop source was changed. Desktop
artifacts (`SOURCES_HASH` `465a6bb1…`, renderer, worker, `CrusorAI.exe`) remain
byte-identical and valid for source commit `7d4a4cc5`.
