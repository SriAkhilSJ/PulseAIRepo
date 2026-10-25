# Agent Core evidence audit — 2026-10-24

## Scope and evidence rule

This audit is limited to Agent Core: interest resolution, context continuity,
planning and execution routing, recovery evidence, completion honesty, and
telemetry. Every recoverable provider-call row, trace row, generated performance
report, and benchmark receipt in the repository was read. No sample was used as
a substitute for the complete committed corpus.

A number is treated as measured only when its source and unit are attributable.
Mixed historical fixtures are not promoted to production sessions, missing
rows are not scored as zero, and generated reports are not treated as ground
truth when they disagree with their source traces.

## Evidence inventory and classification

| Evidence class | Complete inventory | Valid use |
|---|---:|---|
| Provider ledger | 22 JSONL rows: 20 calls for `session-c97a2d...`, 1 `selftest-terminal` call, and 1 terminal run verdict | The 20-call session is the only attributable end-to-end provider sequence in the committed ledger |
| Step traces | 68 JSONL files, 1,085 parseable rows, 0 parse errors | Aggregate telemetry corpus; not one production run |
| Session-shaped traces | 33 `session-*` files, 884 rows | Historical/session-shaped evidence, but not independently proven production traffic |
| Explicit fixture/demo/custom traces | 35 files, 201 rows | Regression and synthetic evidence only |
| Generated reports | 67 `PERFORMANCE_REPORT_*.md` files | Report-generator evidence; never an authoritative task verdict by itself |
| Benchmark receipt | `telemetry-evidence/agent_core_hardening_benchmark_receipt.json` | Persistence/scanner benchmark only |
| Referenced desktop trace | `session-bf69b91a5eed4aa88158fa680e74c4e3.jsonl` | Unavailable; no metric is inferred from it |

There are **no byte-identical duplicate trace rows**. However, eight files reset
or repeat `step_index` inside the same append-only file: `grace-law`, `main`,
`session-13e790...`, `session-18a744...`, `session-58e0a9...`,
`session-b0d54...`, `session-f16ed...`, and `test_session_unit`. Those are
appended/reset runs, so proximity-based retry calculations across their reset
boundaries are invalid.

## Complete measured findings

### Attributable provider run

The 20 operational calls in `calls-2026-10.jsonl` recorded:

| Metric | Measured result |
|---|---:|
| Input tokens | 616,072 |
| Output tokens | 21,348 |
| Total tokens | 637,420 |
| Provider wall time | 463.485 s |
| Mean / median call time | 23.174 s / 19.792 s |
| p95 / maximum call time | 45.407 s / 45.798 s |
| Provider-call errors | 0 / 20 |
| Terminal run verdict | `budget_exhausted` |

Input grew from **26,795** on call 1 to a peak of **37,273** on call 18:
**+10,478 tokens / +39.10%**. It then reset to 25,268 (**-32.21%**) and
13,705 (**-45.76%**). The resets show compaction/summary pressure; they do not
turn the final budget-exhausted verdict into completion.

The request-bucket estimates attribute **259,203 tokens / 42.07%** of cumulative
input to tool schemas and **71.58%** to system prompt plus tool schemas. This is
the largest still-measured cost issue.

### Mixed historical trace corpus

The 1,085 trace rows contain 586 AI/model rows, 646 AI-emitted tool proposals,
and 687 tool-node execution records. The old tracker labeled all 646 proposals
`success`, while 104 execution records were labeled failed. The raw labeled
execution-failure rate is therefore **104 / 687 = 15.14%**; it is not a valid
genuine-failure rate because multiple `failed` rows contain ordinary
`plan_update` JSON, file contents, or `File written` receipts.

The mixed traces sum to 9,762,707 input tokens, 232,771 output tokens,
10,949.56 model seconds, and $10.4421 in recorded cost estimates. These totals
describe the complete committed mixed corpus; they are not a per-task score and
must not be compared directly with the one attributable provider run.

A causal retry rate cannot be recovered honestly. Parallel batches and eight
counter-reset files make adjacent-call heuristics invalid. The provider ledger
has no provider-call errors, while the traces contain tool failures, but the two
sources do not provide a safe one-to-one call pairing.

### Verification, mutation, completion, and report contradictions

* Only **2 / 1,085** trace rows carry `verification_status=passed`; both are in
  fixture-style files (`test_session_unit` and `workspace_demo_run`). Operational
  verification coverage is therefore **unavailable**, not 0% and not 100%.
* Thirty generated reports contain a zero-mutation finding. This is not a valid
  delivered-artifact rate because the old evaluator ignored successful
  temporary writes that were later intentionally cleaned up and counted failed
  or merely proposed writes inconsistently.
* Twenty reports contain both **“Optimal Performance”** and a zero-mutation
  finding.
* All 67 generated reports award a perfect latency subscore; 65 of those have
  zero-duration evidence. Missing duration was being rewarded as perfect.
* Fifty-three reports display a runtime score with the wrong `/ 25` denominator
  even though the runtime composite is on a 100-point scale.
* Nine reports are stale relative to their append-only trace. The largest gap is
  `session-f16ed...`: 35 reported rows versus 146 trace rows, a lag of 111.
* Historical traces do not preserve the final assistant answer consistently.
  User-facing completion honesty therefore cannot be calculated from that
  corpus. The 20 Optimal+zero-mutation contradictions are measurable report
  defects, not a substitute completion-honesty percentage.

### Interest resolution replay

Every recoverable historical ask was replayed: **444 occurrences / 25 unique
asks**.

| Routing result | Before | After this hardening |
|---|---:|---:|
| Act | 297 | 331 |
| Social | 111 | 111 |
| Answer | 2 | 2 |
| Undetermined | 34 | 0 |

All 34 previously undetermined occurrences were balanced outer-quoted
directives. The fix unwraps one presentation quote layer for routing only and
preserves the exact source text in the versioned interest contract. Negated
mutation (`do not install anything`) now remains a constraint without becoming
positive mutation authorization; a later positive instruction (`then fix the
parser`) still authorizes changes.

## Defect-to-code map and implemented strengthening

| Agent Core stage | Evidence-supported defect | Strengthening |
|---|---|---|
| Interest resolution | 34/444 quoted directives routed as undetermined; negated mutation authorized changes; general `no ...` and `nothing else` constraints were dropped | `src/context/user_interest.py::_unwrap_routing_quotes`, `_positive_mutation_requested`, and broader constraint extraction |
| Context continuity | Reports could retain the initial `hello` instead of the current objective/correction | `StepTracker.start_step` now consumes the current versioned `UserInterest.focus_text`; the existing context/compaction interest contract remains the source of truth |
| Planning/routing | A verification tool name or the noun `app` was treated as creation intent | `src/runtime/quality_evaluator.py::_requests_workspace_mutation` requires conservative positive mutation authorization |
| Execution evidence | AI proposals and actual executions were both labeled success; execution args and exit codes were absent | `chat_graph.ai_node` records `proposed`; `SafeToolNode` pairs results to original calls, records sanitized args, and uses the final explicit exit receipt |
| Recovery evidence | Failure rates and artifacts included proposals/failed calls, so retry/failure analysis was polluted | Performance and quality evaluators now use tool-node executions only; failed/proposed calls cannot prove artifacts |
| Completion | Mid-step reports missed final interest, verification, verdict, and final answer | `chat_graph.finalize_node` calls `StepTracker.finalize_report` from authoritative graph state |
| Durable verification | Final verification existed only in regenerated Markdown | `StepTracker.finalize_report` appends a `finalize` trace row with verification status and `FINAL_VERDICT` evidence |
| Persistence safety | Diagnostic args could contain file bodies/secrets; restarted trackers lost prior rows and successful artifact evidence | `record_tool_call` and legacy hydration use the hardened persistence sanitizer/redactor; `_hydrate_existing_trace` restores all rows and safe mutation paths |
| Latency | Near-zero wrapper overhead overwrote provider/tool time; zero duration earned perfect latency | `finish_step` preserves explicit provider/tool duration only; missing duration is N/A |
| Runtime scoring | N/A latency/cache still contributed hidden perfect scores | `compute_performance_score` excludes unavailable dimensions and reports evidence coverage (`n/4 dimensions scored`) |
| Report truth | `/25` denominator, proposal/execution conflation, “Optimal” on unavailable evidence, stale partial sessions | Markdown and CLI now use `/100`, distinguish `↗ proposed` from executed outcomes, render unavailable evidence as N/A, and hydrate full append-only traces |
| Cleanup outcomes | A successfully created then intentionally removed temporary artifact became “zero mutation” | Successful sanitized execution receipts remain durable deliverable evidence even when the file no longer exists |

## Residual measured issue: tool-schema cost

Current HEAD still binds **64 tools**, serializing approximately **55,150 bytes /
13,787 heuristic tokens** of schemas for a normal action. That agrees with the
historical ledger's roughly 12,960 schema tokens per call and 42.07% cumulative
share.

This hardening intentionally does **not** reintroduce task-word-based tool
amputation. The repository has a pinned field regression showing that such a
policy removed browser and planning tools during a later “Run the build” step.
A competitive follow-up can reduce this cost safely by implementing
agent-chosen deferred capability discovery or provider-supported lazy tools,
while retaining an explicit capability-expansion path and stable cache prefix.
That architecture change needs its own evidence and regressions; silently
hiding tools by keywords would trade token cost for execution failures.

Cache effectiveness for the attributable provider run is unavailable because
the gateway did not report cache-read tokens. It must remain N/A until the
provider emits that field or a separately attributable cache receipt exists.

## Validation

* Historical resolver replay: **444/444 routed; 0 undetermined; all 34 quoted directives recovered as actions**.
* Legacy trace compatibility replay: **1,085/1,085 rows loaded**; all 646 AI tool rows normalized to `proposed`; all 687 execution rows retained. The largest stale session hydrated all **146** rows and regenerated a 146-row report.
* Focused Agent Core/evaluator/tracker gate: **74 passed**.
* Affected-surface gate covering interest, classifier skip/salvage, budgets,
  execution phases, toolsets, persistence, parallel tools, progress, completion,
  verification, and subagent parity: **344 passed**.
* Python compilation passed for all four changed application modules.
* `git diff --check` passed.

Full desktop/device runtime proof is not available in this sandbox. Per the
established handoff, the desktop agent should test the application build,
capture screenshots/SQLite/log evidence, and report failures exactly without
modifying application code. This audit does not infer that unavailable result.
