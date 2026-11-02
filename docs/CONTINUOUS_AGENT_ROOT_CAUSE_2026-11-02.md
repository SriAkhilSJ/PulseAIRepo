# Root-cause analysis: continuous execution and agent-cycle overhead

## Scope and evidence

This analysis follows the captured live GLM run
[`41396088687`](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/41396088687),
its [redacted frames, outcome and bridge log](benchmarks/continuous-evidence-41396088687/),
the previous [same-prompt GLM summary](benchmarks/bench_glm_ecommerce_unlimited_SUMMARY.json)
and [diagnostic trace](../showcase/agent_ecommerce_glm/diagnostics/traces/t5-5cc64bf83e.jsonl),
and the historical [`agent_core_blueprint.html`](agent_core_blueprint.html) and
[`ref_blueprints.html`](ref_blueprints.html). The runs used different hosts and
settings. They are evidence of two trajectories, not a randomized A/B.

**Bottom line:** removing the iteration wall exposed an existing loop, but did
not address the blueprint's larger underlying problem: the parent repeatedly
pays for a large context and tool surface while failing to turn observations
into repair and verified delivery. We do not know that continuous mode itself
caused the worse trajectory. We do know the new trajectory was incomplete and
expensive.

## Timeline: where work and tokens went

| Model request(s) | Observed behavior | Provider input / output | Model request time |
|---|---|---:|---:|
| 1–2 | One tool exposed. First response ended on length with no call; second proposed a syntactically invalid write that was rejected. | 35,948 / 16,384 | 92.53 s |
| 3–12 | 67 tools exposed. The agent wrote and edited a backend; request 12's import check failed on undefined `api_logout`. | 377,299 / 9,036 | 68.87 s |
| 13–45 | 33 requests and 35 terminal-start frames, with no write/edit start in this interval. They include many different or overlapping file reads, some malformed calls and safety denials. | **1,507,912 / 23,953** | 215.52 s |
| 46–55 | Request 46 ended on length; one edit followed, then more inspection. Graph stopped at token cap. | 527,931 / 15,025 | 102.44 s |

The 1,507,912 input tokens in requests 13–45 are **61.6% of this run's input**.
They are repeated provider input, not necessarily 1.5M unique tokens; some
were cache hits. This interval is not proof that every read was useless. It is
strong evidence that observations did not lead to timely repair or delivery.
Request durations are summed provider request/response intervals, not another
wall-clock measurement.

At the end, the only delivered source file was `server.py`; it compiled but
failed to import. Independent AST inspection found five referenced but
undefined route handlers. No frontend was captured. The run honestly reported
`completed=false`, verification failed, and `budget_exhausted`.

## The blueprint's per-cycle bill, at the real provider boundary

### 1. The base request is large even before the full tool menu

The first request contained two recorded messages, 88,464 message-content
characters and one 985-character tool schema. Provider-reported input was
17,923 tokens. That 17,923 includes the task, system/context message and tool
schema; it is **not** a direct measurement of the persona alone. The historical
blueprint's 430-token autonomous persona and 7,939-token fixed total were
configuration-specific estimates, not comparable provider bills. A controlled
breakdown is still needed.

### 2. The actual parent received the entire broad registry

The first two requests contained one schema; the next 53 each recorded **67
schemas / 60,809 schema characters**. `src/graphs/chat_graph.py::_resolve_bound_tools`
starts the parent from the registry and calls
`resolve_runtime_tool_names` only for strict-scoped children. The earlier
resolver-only 46→43 comparison was real at the resolver level, but **did not
prove that the parent provider payload became smaller**. This corrects the
previous interpretation; the actual live parent request is the decisive
measurement.

Between requests 2 and 3, recorded schemas jumped from 985 to 60,809 characters
and provider input rose from 18,025 to 35,207 tokens (+17,182). Recorded
message *content* characters decreased by 172. This is strong evidence worth
investigating, but it is **not an isolated schema-only experiment**: message
contents, tool-call arguments/metadata, response state and serialization also
changed. `build_request_snapshot` counts `message_chars` from message content
only, not the full serialized message including tool calls. Never equate that
delta to an exact schema-token bill.

Across 55 requests the recorded schema JSON was 3,224,847 characters.
Characters/4 gives approximately 806,212 schema tokens; this is a rough,
configuration-dependent estimate, not the provider's token count or additional
bill. It is already included in the reported prompt input. A provider-appropriate
serialized-payload tokenizer or same-history controlled provider measurement
is needed before claiming a schema-token saving.

### 3. Transcript growth compounds the fixed bill

From request 3 to 55, provider input rose from 35,207 to 54,105 tokens; recorded
message-content characters rose from 88,789 to 142,528. The bridge log estimated
message-only input of ~22.1k tokens initially and ~35.9k near the end; those
estimates use a fallback tokenizer and are not the same thing as provider
usage. Long-term memory was off. The runner logged a discovered 1,048,576-token
context window and a 996,148-token provider cap; no compaction marker appeared
in the bridge log. This does not prove every context-pruning mechanism was
inactive, but it means no logged structural compaction can be credited for
this run. A large per-request window is not the same as a low cumulative bill.

## Why the repair loop did not recover

### Import failure was real but did not become durable check debt

Request 12 ran a `python3 -c` import probe and failed with `NameError` on
`api_logout`. `src/graphs/gates.py::_is_debt_eligible_command` deliberately
recognizes stable checks such as pytest, unittest, test files, build and lint,
not arbitrary `python -c` snippets. Replaying the captured command against that
predicate returns false. The final graph log reported
`unresolved_check_debts=0` despite the import failure and missing delivery.

This rule exists to avoid permanently blocking a correct task on a throwaway
probe; simply converting *all* exploratory failures into permanent debt would
reintroduce that known bug. The gap is that an actionable startup/import
failure can be lost as a **current repair signal** even if it should not become
an eternal exact-command completion obligation. We have shown the command is
ineligible and the final debt count is zero, not that this was the only cause
of the model's subsequent decisions.

### Existing cycle guard is exact, not semantic

`src/graphs/progress_helpers.py::tool_cycle_sample` fingerprints tool name,
canonical arguments, status and full outcome. `detect_tool_cycle` looks for
identical trailing cycles. The 36 `server.py`/`readlines()` commands varied
ranges, arguments or results, so many would produce different fingerprints;
no `[ToolCycleGuard]` line appeared in this run. This is a blind spot for
*overlapping/varied* inspection of the same file without progress, not proof
that all repeated reading is bad. A replacement must be a strategy-change
nudge with revision, path and error awareness, not an arbitrary hard stop that
blocks legitimate debugging.

### Output envelope is another confound

The live job set `CRUSORAI_DELIVERY_MAX_TOKENS=8192`; the first response reported
`finish_reason=length`, 8,192 output tokens, 33,128 reasoning characters and no
tool call. The second reported 8,192 output tokens and a `write_file` that the
syntax guard rejected. `requested_output_cap` combines the configured reply
amount with any enabled thinking allowance, and provider accounting can vary;
the recorded request frame does not independently include the final
`max_tokens` wire value. Do not assert the cap alone caused the failed write.
It is a clear experimental variable. The historical first two diagnostic AI
rows reported 24,192 and 18,423 output tokens, versus 8,192 and 8,192 here;
that old run also spent ~163.8 s on its first AI row versus ~44.6 s here.
Different configurations prevent causal attribution.

## What worked and what did not

- **Worked:** no implicit 45-call final slot; 55 real model requests were made;
  cost telemetry and explicit budget stop were visible; safety denied several
  questionable commands; final status did not claim success; the local
  provider-free SQLite test crossed multiple recursion boundaries with 75
  productive cycles.
- **Not demonstrated live:** >60 productive calls, an actual recursion-boundary
  resume, passing app verification, or a reduction in token overhead/cost.
  No checkpoint-resume line appears in the captured live stderr.
- **Observability caveat:** the outcome counted 58 tool-end receipts (50 success,
  8 failure), but two error events are duplicated by tool ID/name. The captured
  frames have 56 unique `(tool_id, name)` end identities: 50 `ok` and 6 `error`.
  A successful shell exit is not task success. There were 55 start frames, so
  start/end event parity remains an instrumentation issue.
- **Budget caveat:** the runner's `--max-input-tokens` breaker measures input,
  but the graph cap measured input plus output, tripping at 2,513,488 total
  tokens despite only 2,449,090 input. The current turn frame identifies the
  token leg; top-level `failure_reason` was null while its status contract said
  `budget_exhausted`.

## Prioritized fixes and proof required

1. **Parent schema waist:** apply a capability-aware tool profile to parent
   provider calls, while preserving explicit user intent, user-selected tools,
   safety policy, browser/test capabilities when needed, and dynamic tool
   availability. Compare actual serialized payloads before/after on the same
   saved request state; include strict child, ask, read-only, UI, research,
   MCP, image, and execution-phase regression tests. An arbitrary first-N
   tool cap is insufficient and can silently remove needed capabilities.
2. **Actionable error → bounded recovery guidance:** maintain a current,
   revision-aware startup/import failure as repair context; it should prompt a
   small fix and relevant recheck without converting all ad-hoc probes into
   permanent debts. Test both the captured NameError path and the historical
   transient-probe false-debt case.
3. **Varied inspection progress guard:** detect excessive overlapping reads of
   the same revision without a repair or new evidence, ask the model to change
   strategy, and reset when evidence or workspace revision changes. Do not
   halt productive work solely due to a fixed number.
4. **Output and context profiling:** capture actual `max_tokens`, provider
   response finish reason, complete serialized-message/token counts and
   per-layer attribution; run a small controlled output-envelope experiment.
   Separate single-request window pressure from cumulative-token spending and
   avoid damaging prompt caching by aggressively rewriting the prefix.
5. **Budget/status contract and verification:** align token-cap names and
   accounting, reconcile the two failure-reason fields, deduplicate tool
   receipts, and independently test import/start, frontend and user flows.
6. **Measure before another expensive task:** first use recorded-request
   replay and provider-free regression tests; then a bounded same-host,
   same-model, same-prompt A/B with explicit spend, comparable settings and
   independent tests. Separately test >60 productive model calls and a real
   graph checkpoint boundary. A single live run cannot establish improvement.
