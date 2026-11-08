# Acceptance Matrix

Scope: offline generation-boundary repair. No live acceptance was authorized or
performed. Verdict is limited to offline qualification.

---

| # | Criterion | Result | Evidence / classification |
| --- | --- | --- | --- |
| 1 | Live10 root cause identified from evidence | **PASS** | `ROOT_CAUSE.md`; `finish_reason='length'` at 8192 output tokens; request path traced |
| 2 | Actual provider output cap traced | **PASS (applied cap)** | Requested/applied `max_tokens=8192` traced end-to-end. Endpoint absolute maximum is **not proven** (see below) |
| 3 | Provider request parameter traced | **PASS** | `custom` → `max_tokens` (`resolve_output_token_parameter`) |
| 4 | Context/output budget distinction documented | **PASS** | `PROVIDER_OUTPUT_CAPABILITY.md` §1 (1,048,576 window ≠ 8192 request) |
| 5 | Truncation remains fail-closed | **PASS** | finish-reason tests; Live10 replay asserts no source file |
| 6 | Bounded recovery or decomposition implemented | **PASS** | one regeneration, default 1, clamp 0–2 |
| 7 | Duplicate content protection | **PASS** | no merging; replay asserts one `def parse_duration`, one response written |
| 8 | Incomplete source cannot mutate workspace | **PASS** | truncated/invalid/fence cases all assert file absent |
| 9 | Continuations separately financially accounted | **PASS** | new reservation/invocation/settlement; `operation_type="recovery"`; 3 ids |
| 10 | No unbounded recovery loops | **PASS** | attempts ≤ 1 + clamp(0–2); guard/budget checks |
| 11 | Cancellation preserved | **PASS** | cancellation before recovery test; no second claim |
| 12 | Existing P0.6.9 contracts preserved | **PASS** | 324/324 battery; Invariant 7; historical checksums 41/41 |
| 13 | Exact historical prompt offline replay | **PASS** | 876-byte prompt; SHA `a887a669…05f8` asserted |
| 14 | 10/10 historical workload tests | **PASS (simulated)** | in-turn `final_run` 10 passed, 0 failed |
| 15 | 9/9 independent smoke | **PASS (simulated)** | harness `_independent_smoke` 9/9 true |
| 16 | Broader offline regression gate | **PASS** | 324 passed in 524.59 s (309 historical + 15 new) |
| 17 | Secret scan | **PASS** | 0 real hits; 1 reviewed pre-existing false positive (`grant_approval` variable) |
| 18 | Invariant 7 | **PASS** | `maintained=True`; 0 changed/drift/undeclared |
| 19 | Evidence checksums | **PASS** | `p0_6_9/SHA256SUMS.txt`: 41/41 verified |
| 20 | Paid provider calls | **PASS** | 0 calls, ₹0.00 |

---

## Explicitly not proven (not hidden as PASS)

| Item | Status |
| --- | --- |
| Endpoint's true maximum output token capability | **not proven** — no live probe authorized |
| Live model completes the recovery attempt | **not proven** — simulation only |
| Live recovery cost/timing | **not proven** — fake receipts only |
| P0.6.9 live acceptance | **not accepted** — historical verdict unchanged |
| Chat/summarizer/compaction/planner-helper/One-Shot/inline coverage | **unchanged gaps** |

---

## Verdict

All mandatory provider-free criteria above pass:

```text
GENERATION_BOUNDARY_OFFLINE_QUALIFIED
```

This verdict means the generation boundary is implemented, offline-tested and
deterministically simulated against the exact Live10 evidence. It does **not**
mean P0.6.9 is accepted, and it is not evidence of live-model recovery
effectiveness.
