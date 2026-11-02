# Opt-in continuous execution

Continuous mode keeps a productive turn working past the ordinary iteration
ceiling. It is **off by default**. It is not a promise that every task can
finish: providers, safety/permission decisions, user cancellation, genuine
repeated failures, context constraints, or explicit limits can still stop a
turn. Existing verification and completion gates still determine the verdict.

## Enable and set limits

Set `AGENT_CONTINUOUS_EXECUTION=1` in the environment of the bridge/agent
process, or pass `--continuous` to `scripts/run_bridge_turn.py` or
`scripts/run_long_session.py`. Example (use your existing workspace and prompt
file paths):

```sh
AGENT_COST_BUDGET=0.50 python scripts/run_bridge_turn.py \
  --continuous --workspace ./my-workspace --prompt-file ./task.txt
```

**Cost warning:** continuous mode disables the implicit iteration, token and
cost caps, and the drivers disable their implicit call and wall-time caps.
Without explicit limits it can keep spending until stopped. The single-turn
driver also disables its default no-delivery call cap. Explicit CLI and
environment limits still apply: `AGENT_ITERATION_BUDGET`,
`AGENT_TOKEN_BUDGET`, `AGENT_COST_BUDGET`, and the drivers' call, token,
no-delivery and time flags, where supported. A positive iteration limit retains
its reserved tool-free final call; explicit limits above 60 are not clamped in
continuous mode. A configured budget can still end a task incomplete.

Cost is an **estimate**, checked after a request, so one request can cross the
cap. With an explicit cost cap, continuous mode stops if cost is unknown rather
than treating it as zero; it does not make an additional paid grace call after
a cap trips. Existing pending tool calls still follow the graph's normal
routing, safety and cancellation rules. Per-call telemetry in streaming
continuous turns reports the existing session-cumulative estimate (or unknown)
and tokens; the runner prints and records the last received estimate. It is not
an invoice or a guaranteed real-time provider balance. The long-session
harness's `--max-cost-usd` configures a **per-turn** graph estimate, not a
whole-session spending ceiling. Set an external account limit if a strict
financial ceiling is needed.

The long-session driver remains an intentionally bounded benchmark unless its
continuous option or environment flag is used. Its explicitly supplied call,
time and iteration options remain active in that mode. Other custom drivers
can impose their own limits; the graph cannot override those.

## How continuation works

Both `invoke_agent` and `stream_agent` use bounded LangGraph segments in
continuous mode. At a framework recursion boundary only, the graph reads the
SQLite checkpoint, checks that a pending step exists and the checkpoint has
advanced, then resumes with `None` rather than replaying the original prompt or
turn resets. `durability="sync"` persists each completed graph superstep
before starting the next. Iteration counters, pending actions, tool receipts,
verification state and configuration remain in the same turn; the existing
context compaction, permission checks, cancellation gates and recovery guards
remain active. A missing/non-advancing checkpoint or other exception is not
silently retried. Streaming events are forwarded once as received.

This protects the *recursion-boundary* handoff; it does not provide exactly-once
external effects across process crashes, power loss, or a tool that performs an
external action and then fails before its checkpoint is written. It does not
automatically restart a crashed process or re-authorize a denied action.

## Evidence and limitations

`src/tests/test_continuous_execution.py` includes a provider-free, real SQLite
LangGraph with 75 productive model/tool cycles across multiple forced recursion
boundaries, ordered unique side-effect receipts, retained intent/permissions,
and a final verification receipt. It also checks the real AI node still binds
tools at iteration 75, checkpoint non-progress, cancellation at a boundary,
explicit budgets, unknown cost, telemetry, and an echo bridge round trip. The
existing safety, cancellation, budget, status and long-session regressions are
run separately. The targeted run passed 132 tests on LangGraph 1.2.19.
The new continuous tests also passed on LangGraph 1.2.9, the project's stated
minimum (in a separate dependency combination). The separate existing
`test_reasoning_effort_threading.py` run had 14 passes and two failures: its
custom/cheap-provider expectations conflict with the unchanged current
reasoning configuration. This is not a paid model or production end-to-end
benchmark.

A local seven-sample microbenchmark of that artificial 75-cycle graph on
SQLite had median 348.22 ms in one large segment and 344.83 ms with a very small
five-step recursion limit; individual samples ranged 274.2–401.1 ms and
318.9–369.7 ms respectively. The ranges overlap substantially: this does
**not** establish a latency improvement or predict provider latency, token
usage, cost, throughput, or task completion. No paid benchmark was run for
this change. Existing blueprints and past benchmark evidence remain in
`docs/agent_core_blueprint.html`, `docs/ref_blueprints.html` and
`docs/ECOMMERCE_MULTI_MODEL_BENCHMARK_2026-11-01.md`.

## Design references

- OpenCode's [compaction](https://github.com/anomalyco/opencode/blob/3f3ee9e5f02a7425406c29bf5807784d85a156f8/packages/core/src/session/compaction.ts)
  and [max-steps](https://github.com/anomalyco/opencode/blob/3f3ee9e5f02a7425406c29bf5807784d85a156f8/packages/core/src/session/runner/max-steps.ts):
  context management and an explicit configured step boundary. OpenCode's
  configured max steps do disable tools; it is not evidence of universal
  unbounded execution.
- Aider's [base coder](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/coders/base_coder.py):
  bounded reflection and interruption handling, not endless retries.
- Void's [agent prompts](https://github.com/voideditor/void/blob/b3166e7ef2aefbdfeb139445fdf248a561b85d4d/src/vs/workbench/contrib/void/common/prompt/prompts.ts):
  encouragement to take needed steps and wait for tool results.
- PulseAI's existing SQLite checkpoints, context compaction, finish/verification
  gates, safety policies and cancellation controls provide the actual local
  implementation. The reference projects do not guarantee this integration.
