# Implementation Report

Status: **implemented; offline-tested; not live-tested**. No provider call was
made during implementation or qualification (₹0.00).

Baseline: `17811f98352f1606f24fba1945e781988a912413`

---

## 1. Files changed

| File | Change |
| --- | --- |
| `src/orchestration/model_adapter.py` | provider-aware ceiling; bounded recovery loop; recovery instruction; cancellation and acceptance-guard checks; `recovery` ledger operation type; `generation_recoveries` records |
| `src/orchestration/orchestrator.py` | `GENERATION_RECOVERIES` journal event; lifecycle metadata; delivery population |
| `src/orchestration/models.py` | `DeliveryContract.generation_recoveries` field and serialization |
| `src/tests/test_generation_boundary.py` | new 15-test offline suite (not present at baseline) |
| `diagnostics/generation_boundary/*` | this evidence set |

Not modified: planner, agent-core graphs, retrieval, memory, subagents, FinOps
internals, provider gateway, `src/llm/output_budget.py`,
`src/llm/capabilities.py`, all historical `diagnostics/p0_6_9/live9` and
`live10` evidence.

---

## 2. Why each change was necessary

### 2.1 Provider-aware ceiling (root-cause half 1)

Before:

```python
max_output_tokens=getattr(node, "max_tokens", None) or 2048
```

The node ceiling was sent to the provider unexamined. The repository already had
`requested_output_cap()` for this decision but the implementation path bypassed
it.

After (`model_adapter.py:1058-1080`):

```python
requested_ceiling = int(getattr(node, "max_tokens", None) or 2048)
effective_ceiling = requested_output_cap(
    mod, provider=prov, requested=requested_ceiling,
)
```

This can only lower the request to a verified/stated provider cap. When no cap is
known (`max_output_for(...) is None`, the Live10 case), the requested 8192
stands. No new global constant was introduced. The effective ceiling is logged.

### 2.2 Bounded recovery (root-cause half 2)

`_call_model_for_implementation()` now loops at most
`1 + _max_generation_recoveries()` dispatches. It catches **only**
`IncompleteModelOutputError`. Every other integrity error still propagates
immediately with no retry.

Before redispatching it checks:

1. the recovery count against `CRUSORAI_MAX_GENERATION_RECOVERIES` (default 1,
   clamp 0–2);
2. `cancellation_checker()` — raises `TurnCancelledError` without spending;
3. `active_guard().remaining > 0` — no second claim after the acceptance guard is
   exhausted.

The recovery uses a new `purpose` (`node_<id>_recovery<N>`) so
`_dispatch_code_prompt()` creates a new reservation, invocation id, usage
receipt, cost and settlement. Nothing is hidden inside the first call.

### 2.3 Recovery instruction (quality, not a bypass)

`_recovery_instruction()` asks for a complete but minimal file (≤120 lines, only
contract symbols, no tests/CLI/examples/extra APIs, no repeated definitions).
The response still has to pass the unchanged finish-reason, extraction, AST,
contract and cross-file checks. This is a generation-quality hint, not a relaxed
acceptance rule.

### 2.4 Ledger operation type

`_dispatch_code_prompt()` classifies:

```python
"repair"      if purpose starts with "repair_"
"recovery"    if purpose contains "_recovery"
"implementation" otherwise
```

This makes continuation/recovery spend visible in the same invocation ledger as
normal implementation and repair dispatches.

### 2.5 Delivery and journal observability

On a successful implementation the orchestrator records:

```json
{"event_type": "GENERATION_RECOVERIES",
 "details": {"count": 1, "recoveries": [ ... ]}}
```

and puts the same records on `DeliveryContract.generation_recoveries`. The
lifecycle stage metadata also carries the count. A failed turn still has the
ledger entries; see `GENERATION_RECOVERY_DESIGN.md` §6 for that limitation.

---

## 3. Unchanged contracts (deliberately)

- No workspace mutation before finish reason + extraction + syntax validation.
- Incomplete and invalid output still raise and still never reach `write_file`.
- `IncompleteModelOutputError` remains a subclass of
  `ModelOutputIntegrityError`.
- Repair dispatches (`repair_*`) are untouched and still have their own retry
  policy.
- FinOps reservation/settlement/uncertainty code is untouched.
- The acceptance guard, dispatch budget, cost cap, token reservation and
  cancellation paths are reused, not duplicated.
- The planner and graph state machine remain authoritative.

---

## 4. Regression suite added

`src/tests/test_generation_boundary.py` — 15 tests, deterministic fakes only,
no network:

| Group | Tests |
| --- | --- |
| Finish-reason boundary | incomplete reasons fail closed; `stop`/`tool_calls`/missing reason pass; malformed metadata does not crash; unclosed fence is not extracted |
| Output ceiling | provider-aware effective cap reaches `invoke`; unknown model does not invent a cap; complete first response does not recover |
| Historical replay | Live10 truncation recovers and completes; always-truncated fails without writing; invalid Python never mutates; malformed fence never mutates; missing usage is uncertain |
| Recovery budget | acceptance guard blocks at zero remaining; cancellation stops before recovery; recovery can be disabled |

The replay test additionally asserts:

- exact historical prompt SHA-256 `a887a669…05f8`;
- exactly three physical invocations (source, recovery, tests);
- one recovery ledger row with `operation_type="recovery"`;
- three distinct reservation ids, all settled, totals reconciling;
- `GENERATION_RECOVERIES` journal event;
- 10/10 in-turn tests;
- the acceptance harness's own **9/9** independent smoke;
- only `src/duration.py` and `tests/test_duration.py` are mutated.

---

## 5. Classification

| Item | Classification |
| --- | --- |
| Provider-aware ceiling | implemented, offline-tested |
| Bounded regeneration | implemented, offline-tested, simulated |
| Separate recovery accounting | implemented, offline-tested, simulated |
| Duplicate-content protection | implemented by construction; offline-tested |
| Live model effectiveness | **not proven** |
| Endpoint maximum | **not proven** |
| P0.6.9 accepted | **unchanged: not accepted** |
