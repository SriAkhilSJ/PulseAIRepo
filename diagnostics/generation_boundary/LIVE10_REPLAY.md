# Live10 Failure — Offline Replay

Status: **deterministic simulation**, not a live-model result. No provider was
called. The exact historical prompt bytes and the Live10 failure shape are
replayed against scripted responses.

---

## 1. Inputs

| Input | Value |
| --- | --- |
| Prompt source | `diagnostics/p0_6_7/live7/evidence.json` (`prompt` field, byte-for-byte) |
| Prompt length | 876 characters / 876 UTF-8 bytes |
| Prompt SHA-256 | `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8` |
| Target source | `src/duration.py` |
| Target tests | `tests/test_duration.py` |
| Requested ceiling | 8192 (`ExecutionLimits.max_output_tokens_per_node`) |
| Provider / model | `custom` / `z-ai/glm-5.3-flash` |
| Runtime | temporary git workspace, fake `invoke()` |

The replay asserts the SHA-256 before running, so a paraphrased or reconstructed
prompt cannot pass silently.

---

## 2. Replayed invocation sequence

### Invocation 1 — the Live10 failure shape

```text
purpose:        node_task_duration
reservation:    new (unique)
response:       '```python\nfrom __future__ import annotations\n\nimport re\n\n\ndef parse_duration('
finish_reason:  length
output tokens:  8192 (reported by the fake receipt)
outcome:        IncompleteModelOutputError, settled, no write
```

### Invocation 2 — bounded recovery

```text
purpose:        node_task_duration_recovery1
reservation:    new (unique)
prompt:         original prompt + deterministic RECOVERY instruction
response:       complete 32-line / 1101-character module
finish_reason:  stop
outcome:        extraction + ast.parse + contract validation pass
```

### Invocation 3 — tests artifact

```text
purpose:        node_task_tests_test_duration
reservation:    new (unique)
response:       complete 48-line / 991-character pytest file
finish_reason:  stop
outcome:        written once
```

The fake's per-target routing is generic (it reads `Target file path:` from the
prompt); it contains no production special case. `duration.py` appears only in
the test fixture, not in the implementation.

---

## 3. Functional result

| Check | Result |
| --- | --- |
| `src/duration.py` exists | yes |
| `tests/test_duration.py` exists | yes |
| `def parse_duration` count in module | **1** (no concatenation) |
| Module length | 32 lines (≤120 recovery limit) |
| In-turn pytest | **10 passed, 0 failed** |
| Cross-file contract validation | `ok` |
| Harness independent smoke | **9/9 checks true** |
| Files mutated | exactly `src/duration.py`, `tests/test_duration.py` |
| Task verdict | `COMPLETED` |
| `delivery.independently_verified` | true |
| `delivery.generation_recoveries` | 1 record for `src/duration.py` |

The 9/9 smoke is the acceptance harness's own
`LiveAcceptance._independent_smoke`, reused verbatim: four value checks and five
exception checks (`ValueError` × 4, `TypeError` × 1).

---

## 4. Financial shape of the replay

| Invariant | Observed |
| --- | --- |
| Physical provider calls | 3 |
| Ledger invocation records | 3 |
| Distinct reservation ids | 3 |
| Settled reservations | 3 |
| Active reservations | 0 |
| Uncertain reservations | 0 |
| Recovery operation type | `"recovery"` (exactly 1) |
| Recovery purpose | `node_task_duration_recovery1` |
| Ledger cost total vs governor spend | equal (asserted to 6 decimals) |

The fake receipts are authentic-shaped usage records; the cost values are
**simulated**, not real spend. No hidden call exists: the test asserts
`accounting.calls_count == len(llm.prompts)`.

---

## 5. Negative replays (all fail honestly)

| Scenario | Scripted response | Result |
| --- | --- | --- |
| Recovery also truncated | `finish_reason=length` again | `IncompleteModelOutputError`; source absent; exactly one recovery after the original |
| Recovery invalid Python | `def parse_duration(:` | syntax validation fails; source absent |
| Recovery malformed fence | opening fence, no close | extraction fails; source absent |
| Recovery missing usage | complete code, no usage metadata | reservation marked **uncertain**; source absent; not treated as free |
| Acceptance guard exhausted | 1 allowed dispatch | original dispatch only; no second claim |
| Cancellation before recovery | checker returns true | no second dispatch |
| Recovery disabled | `CRUSORAI_MAX_GENERATION_RECOVERIES=0` | original dispatch only; error propagates |

In every negative case:

- no `src/duration.py` is created;
- the original reservation is settled (or uncertain when its receipt is missing);
- the turn does not report `COMPLETED`.

---

## 6. Performance / size instrumentation

| Measurement | Live10 (observed) | Replay (simulated) |
| --- | --- | --- |
| Prompt characters / bytes | 876 / 876 | 876 / 876 |
| Input tokens billed | 512 | fake receipt |
| Available context window | 1,048,576 static | same value available |
| Requested output | 8192 | 8192 |
| Provider-declared max output | unknown (`None`) | unknown (`None`) |
| Actual output tokens | **8192** | 8192 / 900 / 300 (fake) |
| Reasoning tokens | none reported | none |
| Finish reason | `length` | `length` → `stop` |
| Recovery count | 0 (capability absent) | **1** |
| Source candidate size | incomplete | 32 lines / 1101 chars |
| Test candidate size | 48 lines (completed live) | 48 lines / 991 chars |
| Extraction attempts (source) | 1 (rejected before extraction) | 2 (truncated + recovered) |
| Syntax-validation attempts (source) | 0 (rejected earlier) | 1 (recovered candidate) |
| Reservations | 2 | 3 |
| Final integrity | fail-closed, no source | complete, validated, written once |

The replay does not claim that the fake 900-token recovery is a prediction of
live model behavior. It only demonstrates the boundary mechanics.

---

## 7. What this replay proves — and does not prove

**Proven offline**

- The exact Live10 prompt can traverse the repaired pipeline.
- A `finish_reason='length'` response is still rejected and never written.
- One separately reserved/settled regeneration can complete the artifact.
- The completed artifact passes extraction, AST, contract, 10/10 tests and the
  harness's 9/9 smoke.
- Negative recoveries fail closed with honest accounting.

**Not proven**

- That `z-ai/glm-5.3-flash` will produce a complete file on the recovery attempt
  in a live turn.
- The endpoint's true maximum output capability.
- Live timing, live cost of a recovery, or live session-titling behavior.
- P0.6.9 acceptance. The historical verdict remains
  `P0.6.9_ACCEPTANCE_FAILED`.
