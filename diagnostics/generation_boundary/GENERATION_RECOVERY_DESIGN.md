# Generation Recovery Design

Status: **implemented**. Offline evidence is in
`OFFLINE_QUALIFICATION.md` and `LIVE10_REPLAY.md`.

---

## 1. Chosen mechanism: one bounded regeneration

When the provider explicitly reports incomplete output
(`finish_reason` in `length`, `max_tokens`, `max_output_tokens`, `token_limit`,
`incomplete`), Crusor discards the candidate and makes **one new, complete
generation request** for the same target with a minimal-output instruction.

The truncated text is never appended to, spliced, merged or reused. The new
response must independently pass the full existing pipeline:

```text
provider response
  -> finish-reason inspection
  -> exactly-one-complete-payload extraction
  -> language syntax validation (ast.parse for Python)
  -> contract validation / cross-file validation
  -> single workspace mutation
```

### Why not continuation / section merging

Assembling a Python artifact from arbitrary line ranges of a truncated response
and a continuation cannot be proven safe with the existing machinery:

| Risk | Why merging fails |
| --- | --- |
| Duplicate sections | The continuation can repeat the last partial function or import block. |
| Missing sections | There is no reliable way to know what the truncation dropped. |
| Repeated file headers | Continuations routinely re-emit `from __future__`, imports and the module docstring. |
| Overlapping line ranges | The provider does not return a resumable byte/line offset. |
| Incomplete final code block | The continuation can itself end mid-fence. |
| Conflicting definitions | A second `parse_duration` definition can silently shadow the first. |
| Lost imports/declarations | Merging can keep a header that references names from a discarded body. |

A deterministic reconstruction invariant cannot be established for those cases,
so the candidate was rejected rather than guessed. Regeneration has a checkable
invariant: **one response, one file, one public surface, AST-valid, contract-valid**.

### What regeneration prevents

- **Duplicate content:** only the successful response is extracted and written;
  the truncated bytes are never concatenated. The replay asserts the final module
  contains exactly one `def parse_duration`.
- **Missing sections:** the model is asked for the whole artifact, not a suffix.
- **Repeated headers / conflicting definitions:** only one response is used.
- **Truncated closing syntax:** an incomplete recovery is rejected before write.
- **Accidental acceptance:** reaching a token ceiling is never treated as
  success; only an explicit successful finish reason plus extraction and
  validation allows mutation.

---

## 2. Lifecycle

```text
GENERATION_STARTED
      |
      v
PROVIDER_RESPONSE_RECEIVED
      |
      v
FINISH_REASON_INSPECTION
      |
      +---------------------------+
      |                           |
      v                           v
  COMPLETE                    INCOMPLETE
      |                           |
      v                           v
SOURCE_EXTRACTION          GENERATION_RECOVERY decision
      |                           |
      v                           +--> attempts exhausted? ---- yes --> RAISE (fail closed)
SYNTAX_VALIDATION                 |
      |                           +--> cancelled? ------------ yes --> RAISE
      v                           |
CONTRACT/CROSS-FILE               +--> acceptance guard empty? - yes --> RAISE
      |                           |
      v                           v
WORKSPACE_WRITE            NEW reservation + NEW invocation id
                                    |
                                    v
                              new complete generation
                                    |
                                    v
                              finish/extract/validate
                                    |
                                    +--> still incomplete --> RAISE (fail closed)
                                    |
                                    v
                              WORKSPACE_WRITE (once)
```

The recovery branch is inside `ModelExecutionAdapter._call_model_for_implementation()`
and reuses `_dispatch_code_prompt()`, which owns reservation, invocation id,
usage receipt, cost, settlement and ledger writing. There is no second retry
framework.

---

## 3. Bounds and limits

| Limit | Behaviour |
| --- | --- |
| Attempts per target | Default **1** recovery; `CRUSORAI_MAX_GENERATION_RECOVERIES` clamped to 0–2. |
| Dispatch budget | Recovery is a physical dispatch; the existing acceptance guard and orchestrator dispatch budget still apply. |
| Cost budget | Recovery gets its own reservation; a budget breach blocks it through the existing governor. |
| Output tokens | Same effective provider-aware ceiling as the original request. |
| Time | Reuses the existing per-call timeout and client construction path. |
| Cancellation | Checked before the recovery dispatch; a cancelled turn raises `TurnCancelledError` and does not spend. |
| Acceptance guard | `active_guard().remaining > 0` is required before redispatch. |
| Invalid output | **No recovery** for syntax-invalid, malformed-fence or ambiguous output. Those are rejected immediately; recovery is only for explicit truncation. |

`CRUSORAI_MAX_GENERATION_RECOVERIES=0` disables recovery for operators who want
strict single-shot behaviour.

---

## 4. Recovery prompt

The recovery request is the original prompt plus a deterministic instruction:

```text
RECOVERY: Your previous response for this file was truncated at the provider's
output limit. Produce a COMPLETE but MINIMAL file now.
Hard limits: at most 120 lines; only the public symbol(s) in the contract;
no examples, no test code, no CLI, no README, no extra classes or constants,
no repeated definitions. Keep imports minimal. Return ONLY the file.
```

The instruction is generic. It contains no `duration.py`, `parse_duration`,
SprintBoard, model or provider special case. It reduces the chance of a second
truncation without weakening any validation.

---

## 5. Accounting and observability

Each recovery is a distinct physical invocation:

- its own `reservation_id`;
- its own `invocation_id`;
- its own provider claim;
- its own authentic usage receipt;
- its own cost and settlement;
- a ledger row with `operation_type="recovery"`
  (`purpose="node_<id>_recovery<N>"`);
- an adapter `generation_recoveries` record with node, target, attempt, reason
  and requested/effective ceilings;
- on a successful implementation, an orchestration journal event
  `GENERATION_RECOVERIES` and a `DeliveryContract.generation_recoveries` list.

The physical-claim invariant is unchanged:

```text
provider claims == invocation records == reservations/settlements
```

A recovery that receives no authentic usage receipt is treated as **uncertain**
after dispatch (the existing `MissingUsageReceiptError` path), never as free.

---

## 6. Failure behaviour

If the recovery is also truncated, or the budget/guard/cancellation blocks it:

- the task fails; no `COMPLETED` delivery is fabricated;
- no source file is written;
- the original and recovery reservations remain separately settled (or
  uncertain if the receipt is missing);
- the terminal error names the target and finish reason;
- the ledger preserves the recovery attempt for diagnostics.

A hard-failed turn does not emit the `GENERATION_RECOVERIES` journal event
because the orchestrator only records it on the successful implementation path.
The recovery is still visible in `provider_invocations` / the invocation ledger
(`operation_type="recovery"`) and in engine logs. This is a diagnostic-reporting
limitation, not an accounting gap.

---

## 7. Known limitations

- The recovery is **not live-proven**; only simulated offline. A model may
  truncate the second response too.
- A single regeneration is not decomposition. An artifact whose minimal form
  still exceeds the ceiling will fail honestly after one retry.
- The recovery does not increase the output ceiling. Raising a ceiling is not
  the fix and would require independent provider-capability evidence.
- Duplicate definitions *inside a single model response* are a model-quality
  issue; this design guarantees no duplicates from merging. The replay asserts
  one public definition in the accepted artifact.
- The exact endpoint maximum remains unknown (see
  `PROVIDER_OUTPUT_CAPABILITY.md`).
