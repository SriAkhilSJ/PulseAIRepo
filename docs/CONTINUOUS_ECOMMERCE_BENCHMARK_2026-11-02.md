# Continuous execution: live e-commerce benchmark

## Verdict

**The real task did not complete.** Continuous mode passed the old default
45-iteration boundary, but this run stopped at its explicitly configured token
budget after 55 model requests. The output was an incomplete backend, and an
independent import failed. The run does **not** demonstrate a real-model
checkpoint continuation or work past 60 calls.

- GitHub run: https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/41396088687
- Tested commit: `7723fe6160ea4d1d9ee50fb97818e91b2eae1db0`
- Model: `z-ai/glm-5.3-flash`, custom Velona gateway; GitHub Actions Ubuntu runner.
- Prompt: `benchmark_ecommerce_prompt.txt`, SHA-256
  `8e98b4886c4241f4f66e6f6a575c192bf917d07cf2adf2272e0dfa63046c315c`,
  the same file as the previous multi-model benchmark.
- Mode: `--continuous`; no explicit iteration/call/no-delivery ceiling;
  `--max-input-tokens 2500000`, `AGENT_COST_BUDGET=0.60`, timeout 1,100 s.
- Pricing was checked before the paid turn. The $0.60 limit is an estimated
  graph cost budget, not an invoice or hard provider-side spending limit.
- Raw, redacted frames, outcome, logs, generated source and diagnostic trace:
  [`benchmarks/continuous-evidence-41396088687/`](benchmarks/continuous-evidence-41396088687/).
  Evidence collection was a separate GitHub job and made no model calls.

## Before vs. current: same model and prompt, not a controlled A/B

The previous GLM result is from
[`bench_glm_ecommerce_unlimited_SUMMARY.json`](benchmarks/bench_glm_ecommerce_unlimited_SUMMARY.json)
and [`t5-5cc64bf83e.jsonl`](../showcase/agent_ecommerce_glm/diagnostics/traces/t5-5cc64bf83e.jsonl).
It used a different host and budget configuration; model variability and
configuration changes prevent attributing differences to continuous mode.

| Metric | Previous GLM | Continuous-mode GLM | Observation |
|---|---:|---:|---|
| Verified task completion | No | No | No completion improvement demonstrated |
| Run outcome | `budget_exhausted` | `budget_exhausted` | Current trigger is explicitly identified as tokens |
| Model requests | 52 | 55 | Current finished at iteration 55, beyond old default 45, not beyond 60 |
| Runner elapsed | 523.35 s | 490.61 s | 6.3% lower in these single runs; not causal proof |
| Request p50 / p95 | 2.93 / 19.68 s | 3.18 / 43.60 s | Tail latency worsened in this run |
| Input tokens | 1,980,730 | 2,449,090 | +23.6% total |
| Output tokens | 55,904 | 64,398 | +15.2% total |
| Input tokens/request | 38,091 | 44,529 | +16.9%; task histories differ |
| Estimated spend | $0.3251 | $0.3996 | +22.9%; estimates, not invoices |
| Tool outcome receipts | 29 succeeded, 29 failed | 50 succeeded, 8 failed | Receipt classification, not proof the task worked |
| Cache, reported rows only | 1,342,208 / 1,756,813 (76.4%; 45 rows) | 1,418,624 / 2,323,830 (61.0%; 51 rows) | Partial denominators; not directly attributable |

The baseline runner was configured for 100 calls and 2.5M input tokens, but
historical graph clamps and conflicting stop fields mean its exact binding
stop should not be inferred from the CLI alone. The current run has direct
stop evidence: its terminal frame says `iterations 55/uncapped, tokens
2,513,488/2,500,000, ... tripped: tokens`. Runner `budget_stop=false` because
its own breaker counts **input** tokens, while the graph counts **input plus
output** tokens. The current CLI label `--max-input-tokens` therefore does not
precisely describe the graph limit; this is a provenance/contract issue, not
an iteration stop. The graph can cross the cap by one in-flight response.

## Per-cycle overhead: direct new payload evidence

This is the relevant blueprint question, not merely the generated-site result.
The redacted `llm.request` frames show actual recorded request metadata:

- Requests 1–2 each carried **1 tool**, with 985 schema characters.
- Requests 3–55 each carried **67 tools**, with **60,809 schema characters
  per request**. Across all 55 requests that is 3,224,847 recorded schema
  characters. A crude characters/4 approximation is roughly **806,212
  schema tokens total**, including approximately 15,202 per full-schema
  request. This is an estimate, not a provider tokenizer measurement; schema
  serialization and tokenizer behavior matter. These tokens are already part
  of the input total and must not be added to it again.
- Recorded `message_chars` grew from 88,464 on request 1 to 142,528 on
  request 55. This is character payload size, **not** a provider token count.
- The measured input/request rose from 38,091 in the previous GLM run to
  44,529 here, but the old raw schemas and equivalent per-cycle breakdown are
  not available in the saved baseline. No fixed-overhead reduction is proven.

**Correction to the earlier resolver analysis:** the code-level resolver
comparison (e.g. UI 46→43) did not prove that the parent agent actually sent
those smaller sets. The real parent binding path in `src/graphs/chat_graph.py`
applies `resolve_runtime_tool_names` only for strict-scoped children and
otherwise starts from the registry. This live parent turn actually sent 67
schemas on 53 requests. The blueprint's tool-gating gains should not be
presented as a verified reduction in this parent model payload.

## What happened

1. First response hit the output length limit with no tool call; the next
   proposed `write_file` was rejected for invalid Python. A second write landed,
   followed by edits assembling `server.py`.
2. A terminal import check found `NameError: name 'api_logout' is not defined`.
   The agent then made many inspection calls instead of completing the repair
   and frontend. Among 45 terminal-start frames, 36 commands contain both
   `server.py` and `readlines()`; several inspect different or overlapping
   ranges, so this is not proof each individual read was useless, but the
   sequence consumed substantial calls without closing the delivery.
3. The runner received 58 tool-end receipts: 50 classified success and 8
   failure, including syntax/argument errors and safety-policy denials. The
   mismatch between 55 start frames and 58 end receipts is a telemetry-count
   difference, not evidence of 58 independently successful actions.
4. The turn stopped after the final response pushed **total** known tokens to
   2,513,488. It reported `completed=false`, `run_outcome=budget_exhausted`,
   and `verification_status=failed`. The status contract reports
   `failure_reason=budget_exhausted`; the separate top-level `failure_reason`
   field is null, an observable status consistency defect.
5. No `[continuous] resumed checkpoint segment` line appears in the captured
   bridge stderr. This run exceeded 45 calls but did not demonstrate an actual
   graph-recursion checkpoint boundary. The provider-free 75-cycle SQLite
   test remains the evidence for boundary/resume mechanics.

## Independent checks of the saved deliverable

The GitHub runner's `independent.txt` records `server.py` as the only non-
metadata workspace file; `python -m compileall` passed, and pytest was not run
because no Python test files were present. Compilation alone does not resolve
names or prove a server starts.

A separate local import of the captured file with `runpy.run_path` failed with
`NameError: name 'api_logout' is not defined`. Static AST inspection found five
undefined names referenced by the `ROUTES` table: `api_logout`,
`api_cart_clear`, `api_orders_list`, `api_admin_stats`, and
`api_admin_products`. The referenced `frontend/` directory is absent from the
captured workspace. The source also contains seeded demo/admin passwords; it
must not be treated as production-ready. No live storefront, cart, checkout,
or browser verification passed.

## Priority follow-ups, not implemented by this benchmark

1. Apply and test capability-based parent tool binding on the actual provider
   request path, with permissions and needed browser/verification tools
   preserved. Measure schemas using the provider tokenizer and payload frames.
2. Detect repeated, varied inspection of the same file without a corresponding
   repair or delivery; guide a change of strategy while keeping legitimate
   inspection and permissions intact. Validate against the 36 observed reads.
3. Resolve input-only versus total-token cap semantics and top-level versus
   contract failure-reason consistency. Preserve explicit cost/token limits.
4. Run an independent import/start check in addition to syntax compilation,
   and test the required frontend and user flows. A green tool exit is not a
   completed task.
5. For the continuous boundary claim, run a controlled model-backed test that
   actually exceeds 60 productive calls and crosses the recursion boundary,
   with a higher **explicit** budget and clear approval for the extra spend.
   Do not assume that removing budgets alone repairs the model's trajectory.
