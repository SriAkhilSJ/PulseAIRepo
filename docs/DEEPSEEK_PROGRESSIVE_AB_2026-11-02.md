# DeepSeek continuous-agent A/B — 2026-11-02

## Verdict

The live test **confirms the parent request schema reduction reached the
provider boundary** and shows lower input tokens in the first 37 completed
requests. Neither run finished successfully, and the experiment does not prove
better task completion or end-to-end latency. The discovery-on run was cut off
by the gateway wallet, not the configured graph budget. No more paid runs were
attempted.

## Setup and limits

- Main model: `deepseek/deepseek-v4.1-flash`, custom Velona gateway; auxiliary
  configured as `qwen/qwen3.7-flash`. The recorded LLM request/ledger rows show
  DeepSeek only; they do not prove an auxiliary call occurred.
- Same pinned `benchmark_ecommerce_prompt.txt` (SHA-256
  `8e98b4886c4241f4f66e6f6a575c192bf917d07cf2adf2272e0dfa63046c315c`), empty
  workspaces, continuous mode, 2.5M graph token cap, estimated $0.60 graph cost
  cap per turn and 1,100-second runner timeout. No configured iteration cap.
- The first workflow was intended to run the arms sequentially on one runner.
  The baseline returned nonzero because it was incomplete, and GitHub's shell
  `-e` stopped the workflow before the second arm. The corrected workflow ran
  **only** the missing arm; the arms therefore used separate Ubuntu runners a
  few minutes apart. The only code change between them was the benchmark
  workflow. Host/load, provider stochasticity and shared gateway cache are
  confounders. The failed workflow status is a harness outcome; the later
  successful workflow status is **not** a successful agent task.
- A graph cap is an estimate checked after a request; the final in-flight call
  can overshoot. Auxiliary or failed in-flight usage might not be included. It
  is not a hard provider-side or combined two-run spending limit.

## Full run scorecard

| Metric | Discovery off (baseline) | Discovery on |
|---|---:|---:|
| Provider requests started | 44 | 38 |
| Completed provider responses | 44 | 37; request 38 failed mid-stream |
| Provider-reported input tokens in completed responses | 1,909,333 | 1,259,209 |
| Provider-reported output tokens in completed responses | 27,792 | 26,126 |
| Estimated graph cost at last telemetry | $0.6061503 | $0.4091139 |
| Elapsed run time | 155.777 s | 200.888 s |
| Request latency p50 | 2.172 s | 2.442 s |
| Request latency p95 | 9.066 s | 18.082 s |
| Last outcome | `budget_exhausted`; incomplete | `turn_failed`; wallet exhausted mid-stream |

The estimated sum is **$1.0152642** for reported graph telemetry, not an
invoice or guaranteed total: the failed streaming request had unknown usage.
Provider response frames did not report billed cost. The discovery-on wall
clock included first/second request durations of approximately 18.1/71.0 s.
These distinct tasks and partial trajectories do not establish a latency
regression or improvement caused by discovery.

## Matched early-trajectory comparison

The first **37 completed responses** in each arm are compared here. They are
not the same conversation: tool choices, outputs, generated code and cache
conditions differ.

| Metric, first 37 completed responses | Off | On | Observed difference |
|---|---:|---:|---:|
| Input tokens | 1,537,828 | 1,259,209 | −278,619 (−18.1%) |
| Mean input/request | 41,563 | 34,033 | −7,530 |
| Output tokens | 20,196 | 26,126 | +5,930 |
| Graph-estimated cumulative cost | $0.4855836 | $0.4091139 | −$0.0764697 |

Both first requests were in forced delivery with 1 schema/985 characters. In
subsequent requests the off arm sent **67 schemas/60,809 characters** (43
requests), and the on arm sent **29 schemas/25,021 characters** (37 requests,
including the failed in-flight request). This is a **58.9% per-request schema
character** reduction, not a 58.9% overall-token or cost reduction. Neither
arm called `discover_tools`; extra discovery round trips and activated-schema
cost were therefore **not tested**. Request payloads also differed: over the
first 37 requests mean serialized message characters were approximately
125,279 off vs 127,075 on, and mean tool-call/name/ID metadata was 14,323 vs
12,798. Provider input totals include all request content and schemas; the
observed input decrease cannot be uniquely attributed to schemas.

The debug logs reported cache values for 41/44 off and 35/37 successful on
responses: weighted cached-prompt ratios were approximately **45.0%** and
**57.0%** respectively, over those partial sets only. Do not compare those
percentages as full-run cache accounting or assume equal cache state.

## What actually happened

**Off:** The agent created a Python server, three frontend files and a generated
API test script. It hit the $0.60 estimated graph cap at $0.6061503 and finalized
incomplete/unverified; navigation/rendered proof was missing. Its own test
printed **21 passed, 2 failed** but exited 0, demonstrating that a shell success
code here does not establish tests passed. The same script reproduced 21/2 in a
fresh temporary copy locally. The two failing checks involved an expected
unauthorized status (script expected 403 while server returns 401) and an
admin-update status (server returns 201 although the script expects 200).
Those are test/API-contract discrepancies, not evidence that every business
flow failed.

**On:** The agent created `app.py`, a frontend and its own `verify.py`. Its test
printed **17 passed, 7 failed**, exit 1, then the model began examining the
code; the next request failed with gateway `insufficient_quota` and a
mid-stream truncation. Its test failures were reproduced in a clean temporary
copy. The test uses a cookie and `quantity`, while this implementation uses
`X-Cart-Token`/`cart_token` and `qty`. A separate local probe using the
implementation's actual protocol returned products 200, added and retrieved a
cart of 2 items, and checked out with HTTP 201. This narrows the diagnosis to a
test/implementation mismatch; it does **not** prove browser/UI behavior,
security, all task requirements, or that the seven generated assertions are
correct. No provider or generated code was altered for that probe.

## Evidence and next steps

- Baseline workflow: <https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/41414061599>
- Discovery-on workflow: <https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/41414546540>
- Redacted artifacts: `docs/benchmarks/deepseek-progressive-ab-41414061599/off/`
  and `docs/benchmarks/deepseek-progressive-ab-41414546540/on/` (frames,
  outcome, logs, telemetry, independent checks, text workspace files).
- A further live run requires wallet funding and an agreed explicit budget.
  If authorized, use a reliable sequential A/B harness and independently
  specified tests, include a task that actually requires an activated deferred
  tool, and measure provider billing/cache as available. The present data does
  not show a real-provider checkpoint-resume boundary or a completed task.
