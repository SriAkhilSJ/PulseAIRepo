# Provider Output Capability

Status: **code-traced and evidence-backed; endpoint maximum not independently
probed.** No live provider request was made for this report (₹0.00).

---

## 1. The six quantities, kept separate

| Quantity | Value on Live10 | How established |
| --- | --- | --- |
| Model context window | 1,048,576 (static profile for `flash`) | `src/llm/capabilities.py` static fallback |
| Provider maximum output tokens | **unknown / not verified** | `max_output_for("z-ai/glm-5.3-flash","custom")` returns `None` |
| Requested generation tokens | **8192** | `ExecutionLimits.max_output_tokens_per_node = 8192` |
| Reasoning-token budget | 0 / none observed | no reasoning metadata in the response; no `reasoning_effort` applied |
| Actual completion usage | 8192 output, 512 input | `live10/provider_invocations.jsonl` |
| Remaining invocation / financial budget | 5 dispatches, ₹5.00 cap | plan event + `ExecutionLimits` |

The context window is **not** used as an output ceiling. The static capability
table also carries `max_output_tokens: 8192` for `z-ai/glm-5.3-flash`
(`src/llm/capabilities.py:31-39`), but that static number is not an independently
verified provider statement, and the orchestrator path does not consult
`normalize_llm_request_params()` anyway. It is documented here as a fallback
value only.

---

## 2. Wire parameter

`resolve_output_token_parameter()` maps providers to the parameter their adapter
accepts (`src/orchestration/model_adapter.py:371-381`):

| Provider | Parameter |
| --- | --- |
| `custom` | `max_tokens` |
| `openai`, `cheap`, `nvidia`, `deepseek`, `groq`, `anthropic` | `max_tokens` |
| `gemini`, `google` | `max_output_tokens` |

For Live10 (`custom`) the request was:

```text
llm.invoke(prompt, max_tokens=8192)
```

This is traced through the exact call chain in `ROOT_CAUSE.md`. The wire body
itself was not captured in the preserved evidence; what is proven is:

1. the code path builds `{"max_tokens": 8192}`;
2. the provider billed exactly 8192 output tokens;
3. the provider reported `finish_reason='length'`.

Those three facts together are consistent with the request limit being reached.
They do not prove the endpoint's absolute maximum. A live capability probe is
explicitly out of scope and was not performed.

---

## 3. Unknown maximum policy (implemented)

`src/llm/output_budget.py::requested_output_cap()`:

```text
stated = max_output_for(model, provider)
allowed = min(requested, stated) if stated else requested
return max(_MIN_REPLY_TOKENS, allowed)
```

Consequences:

- a verified/stated provider cap **can only lower** the request;
- when no cap is known, the requested value stands;
- no magic 8K/16K/32K/64K constant is introduced;
- the existing 512-token minimum reply floor is retained.

For Live10 the resolver returns 8192 because no dynamic cap is known. That means
the repair does **not** silently raise the ceiling; it makes the ceiling an
explicit, provider-aware decision and adds a recovery path when the ceiling is
still reached.

---

## 4. Reasoning tokens

The Live10 usage record exposes only `input_tokens`, `output_tokens`,
`cached_tokens` and `total_tokens`. No reasoning-token field is present. The
adapter's reasoning budget is therefore 0 for this call, and the 8192 output
tokens are visible completion tokens, not hidden reasoning that could have
produced an empty-looking response.

If a provider later reports reasoning usage, `requested_output_cap()` already
accepts `thinking_tokens` and adds it to the requested amount; that behavior is
unchanged and is not exercised by this repair.

---

## 5. Budget interaction

- The request (8192) is below the model's context window, so no input-headroom
  conflict exists (512 billed input tokens).
- The request is within the task-level worst-case financial bound documented on
  `ExecutionLimits.max_output_tokens_per_node` (5 dispatches × 8192 tokens at the
  measured rate is far inside the ₹5 cap).
- The recovery dispatch reuses the same effective ceiling. It does not increase
  the per-call request, does not increase the dispatch budget, and cannot bypass
  the FinOps reservation.
- The acceptance guard (`src/llm/acceptance_guard.py`) is consulted before a
  recovery is dispatched; a guard with zero remaining claims blocks the retry.

---

## 6. Remaining uncertainty

| Question | Status |
| --- | --- |
| Could the endpoint emit more than 8192 output tokens? | **Not proven.** No live probe authorized. |
| Is 8192 the endpoint's hard maximum? | **Not proven.** It was the requested value and the stop point. |
| Are reasoning tokens billed inside `max_tokens` on this endpoint? | **Not exercised.** No reasoning usage was reported. |
| Would a larger ceiling have completed the file? | **Not proven**, and increasing the ceiling is not the chosen fix. |

These unknowns are not hidden: the recovery design is deliberately independent
of knowing the endpoint's true maximum.
