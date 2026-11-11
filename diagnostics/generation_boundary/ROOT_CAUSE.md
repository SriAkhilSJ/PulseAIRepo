# Generation Boundary — Root Cause

Status: **provider-free forensic reconstruction**. No provider was called for this
report. Live facts are quoted from the preserved P0.6.9 evidence; code facts are
from the repository at the repair baseline.

Baseline commit: `17811f98352f1606f24fba1945e781988a912413`
Branch: `feat/prompt-cache-stabilization`

---

## 1. The observed failure (Live10, preserved evidence)

Run: `p0_6_5_20261107T224903_ddf70775`
Turn: `turn-894b79c852ba44098aab315fc26fe872`

| Fact | Value | Source |
| --- | --- | --- |
| Source reservation | `res_6988ef02e5e6` | `diagnostics/p0_6_9/live10/provider_invocations.jsonl` |
| Source invocation | `inv_3b521d55750146d9ba6df553c2864e3c` | same |
| Provider / model | `custom` / `z-ai/glm-5.3-flash` | same |
| Input tokens (billed) | 512 | same |
| Output tokens (billed) | **8192** | same |
| Cost | ₹0.153887 | same |
| Tests reservation | `res_d75fe218ac8c` (691 in, 384 out) | same |
| Total settled | ₹0.164152 | `FINAL_REACCEPTANCE.md` |
| Terminal error | `Provider stopped before completing output for 'src/duration.py': finish_reason='length'.` | `live10/logs/electron.stderr.log:104` |
| Workspace after turn | `src/duration.py` absent; `tests/test_duration.py` present | `FINAL_REACCEPTANCE.md` |
| Claims / settlements | 2 physical claims, 2 settlements, 0 active, 0 uncertain | `FINAL_REACCEPTANCE.md` |

The fail-closed behaviour was correct: the incomplete source never reached
`write_file`. The missing capability was recovery after a legitimate provider
output exhaustion.

---

## 2. Complete ceiling path (traced, not inferred from configuration)

```text
ExecutionLimits.max_output_tokens_per_node = 8192        src/orchestration/models.py:308
        |
        v
orchestrator assigns the ceiling to every node            src/orchestration/orchestrator.py:605-609
    if not node.max_tokens: node.max_tokens = int(ceiling)
        |
        v
PLAN_GENERATED event records per_node_output_tokens       src/orchestration/orchestrator.py:611-618
        |
        v
_call_model_for_implementation reads node.max_tokens      src/orchestration/model_adapter.py:1005+
        |
        v
_dispatch_code_prompt(max_output_tokens=...)              src/orchestration/model_adapter.py:1159+
        |
        v
build_output_token_kwargs(provider, max_output_tokens)    src/orchestration/model_adapter.py:391-402
        |
        v
resolve_output_token_parameter("custom") -> "max_tokens"  src/orchestration/model_adapter.py:371-381
        |
        v
llm.invoke(prompt, max_tokens=8192)                       src/orchestration/model_adapter.py:1329+
```

The Live10 journal confirms the plan stage:

```json
{"event_type": "PLAN_GENERATED",
 "details": {"nodes_count": 3, "dispatch_budget": 5,
             "per_node_output_tokens": 8192, "work_units": 2, "demand": 2}}
```

So the number 8192 is **the harness's own per-node implementation ceiling**, not
a transport default and not a value discovered from the endpoint. The applied
provider parameter for `custom` is `max_tokens`.

### What was *not* used on this path

`src/llm/output_budget.py::requested_output_cap()` already existed and is the
provider-aware resolver used by the chat graph. The orchestrator implementation
path bypassed it and passed `getattr(node, "max_tokens", None) or 2048` straight
to the dispatch. That is the code defect behind an unexamined ceiling.

`src/context/model_budgets.max_output_for("z-ai/glm-5.3-flash", "custom")`
returns `None` on this machine, i.e. no dynamically verified output cap is
known. `requested_output_cap(..., requested=8192)` therefore returns 8192 (no
invented cap). The static `src/llm/capabilities.py` fallback for a `flash`
model states `max_output_tokens: 8192`, and
`normalize_llm_request_params()` would clamp to that profile, but that normalizer
is not invoked on this adapter path. Its value happens to agree with the
requested 8192, so it does not change the conclusion.

The 1,048,576-token context window in the static profile is **not** an output
capacity and was not used as one.

---

## 3. Finish-reason handling was already fail-closed

`response_finish_reason()` (`model_adapter.py:121`) reads
`response_metadata` / `additional_kwargs` and normalizes `length`,
`max_tokens`, `max_output_tokens`, `token_limit` and `incomplete` into the
canonical incomplete set. `assert_provider_output_complete()`
(`model_adapter.py:147`) raises `IncompleteModelOutputError` before extraction or
mutation. The Live10 terminal line proves this path fired.

Therefore the truncation was detected correctly. The defect was that detection
was terminal: there was no bounded, separately accounted recovery attempt, so the
entire turn aborted and the dependent test/verification stages never ran.

---

## 4. Why Live9 and Live10 differed

| | Live9 | Live10 |
| --- | --- | --- |
| Prompt contract | same `parse_duration` task | same |
| Prompt SHA | `a887a669…05f8` | `a887a669…05f8` |
| Requested output ceiling | 8192 | 8192 |
| Source input tokens | 518 | 512 |
| Source output tokens | **4386** | **8192** |
| Finish reason | normal completion | `length` |

The prompt, contract, ceiling and dispatch path were the same. The model simply
emitted more code in Live10 and reached the requested ceiling. This is **model
output-length variance**, not a change in prompt size, planner budget or
transport configuration. Live9 is preserved in `diagnostics/p0_6_9/live9/`.

No evidence supports a change in provider maximum between the runs; the endpoint
was not probed in either run beyond the request itself.

---

## 5. Non-causes (explicitly excluded)

- **Not a FinOps failure.** Two claims, two settlements, zero active and zero
  uncertain reservations. The second (tests) dispatch settled normally.
- **Not a prompt-size failure.** The prompt is 876 UTF-8 bytes / 876 characters;
  Live10 billed 512 input tokens.
- **Not a silent retry.** The Live10 ledger shows one source dispatch only.
- **Not an invalid-output acceptance.** The source file was never written.

---

## 6. Root-cause statement

> The implementation path requested exactly 8192 output tokens because
> `ExecutionLimits.max_output_tokens_per_node` was copied onto the task node and
> passed directly to the provider as `max_tokens`, without the existing
> provider-aware output-budget resolver. The model emitted a response that hit
> that ceiling (`finish_reason='length'`). The adapter correctly refused to write
> it, but the pipeline had no bounded, separately reserved and settled recovery
> path, so a recoverable truncation became a terminal turn failure.

The repair therefore has two parts:

1. route the requested ceiling through `requested_output_cap()` so a verified
   provider cap can only lower it (never invent one);
2. add one bounded regeneration attempt, dispatched and accounted as a new
   provider invocation, that still passes the full integrity pipeline.
