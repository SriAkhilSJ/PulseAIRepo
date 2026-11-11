# LIVE12 Preflight Acceptance Matrix

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Starting HEAD / branch / origin | PASS | `128fbc56…`, local == origin |
| 2 | Live11 repair commit present | PASS | `128fbc56` |
| 3 | Historical evidence integrity | PASS | P0.6.9 41/41; Live11 48/48; Live11 repair 19/19 |
| 4 | Unrelated workspace changes preserved | PASS | not staged/reset |
| 5 | Historical reservation classified truthfully | PASS | `res_d7990e4d3dc3` persisted `in_flight`; classified **uncertain**; not released |
| 6 | One stable submission id | PASS | renderer + protocol + tests |
| 7 | Duplicate IPC cannot create another turn | PASS | 25-test suite |
| 8 | Duplicate session create returns original | PASS | bridge test |
| 9 | Completed/pending replay refused | PASS | terminal finality + reload tests |
| 10 | Distinct submissions still possible | PASS | same-session repeat test |
| 11 | Cross-session replay rejected | PASS | bridge test |
| 12 | Durable submission state across restart | PASS | reload + `running -> failed` |
| 13 | Concurrent duplicate claims idempotent | PASS | 8-thread test |
| 14 | 60 s new-session rule audited | PASS with trade-off | `SUBMISSION_IDEMPOTENCY_AUDIT.md` |
| 15 | Reserved-never-dispatched -> released | PASS | lifecycle test |
| 16 | Dispatch interrupted -> uncertain + hold | PASS | lifecycle test |
| 17 | Missing usage -> uncertain | PASS | adapter/generation suite |
| 18 | Authentic usage -> settled once | PASS | commit-idempotence test |
| 19 | No double settlement | PASS | test |
| 20 | Forced termination durable | PASS | sweep test |
| 21 | Current-process call not reconciled as orphan | PASS | cutoff test |
| 22 | Auxiliary title accounting independent | PASS | governed gateway + P0.6.9 tests |
| 23 | Title cannot create session/turn | PASS | code audit |
| 24 | Title cannot block terminal | **FAIL / unresolved** | synchronous `wait=True` + `_engine_build` subprocess can block (9.5 min Live11); must disable autotitle or bound `_engine_build` |
| 25 | Hard pre-dispatch budget | PASS | `budget_preflight.json` |
| 26 | Budget requirement documented | PASS | ₹0.037732 observed; ₹1.20 recommended |
| 27 | Relevant offline suites | PASS | Live11 repair 25/25; generation 15/15; P0.6.9 FinOps 15/15 |
| 28 | Broad battery | PASS with pre-existing failure | 349 collected: 348 passed, 1 failed; baseline reproduces the same failure |
| 29 | Desktop runtime artifact | PASS | exe present; renderer JS updated; `node --check` 0 |
| 30 | Clean desktop rebuild | **FAIL / environment-blocked** | missing Electron/DebugProtocol/TrustedHTML typings; no changed-file errors |
| 31 | LIVE12 procedure prepared | PASS | one session, one submission, exact prompt, abort rules |
| 32 | Provider calls / spend / Electron runs in preflight | PASS | 0 / ₹0.00 / 0 |

---

## Verdict

```text
LIVE12_NOT_READY
```

The Live11 exactly-once and financial-lifecycle controls themselves pass. The
preflight is not unconditionally ready because:

1. the title path still runs synchronously before the terminal event and can
   block in `_engine_build`; a LIVE12 run must set `CRUSORAI_AUTOTITLE=off` or a
   separate bounded-build fix is required;
2. a clean desktop rebuild cannot be verified in this environment because the
   installed Electron/DebugProtocol/TrustedHTML type packages are incomplete;
3. one pre-existing broad-battery failure remains red (baseline-proven, not
   caused by the Live11 repair).

If the authorizer explicitly accepts the existing built artifact and the
autotitle-off control, the run can proceed with a **₹1.20** ceiling. Without that
acceptance, LIVE12 is not ready.
