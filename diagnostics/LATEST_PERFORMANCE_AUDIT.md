# Agent Performance & Diagnostics Audit — Evidence-Adjudicated

**Session ID:** `session-e181f632730e4daba43adedb09101923`

**Generated at:** `2026-10-24 03:09:55 UTC`

**Model:** `z-ai/glm-5.3-flash`

**Task summary:** Verify bounded context behavior; create, inspect, and then
remove a synthetic credential probe; exercise terminal handling; and inspect
durable verification/replay evidence. The literal synthetic token is omitted
from this committed report.

## Evidence-validity notice

The generated evaluator originally reported a unified score of **56.9/100**.
That number is not valid for this task:

1. it treated the explicitly required cleanup of `scratch/security_probe.py` as
   a “zero mutation failure,” although successful write events prove the
   mutation and the teardown evidence separately proves intentional removal;
2. it assigned a perfect latency subscore while every recorded step duration
   was `0.00s`, which means latency telemetry was unavailable rather than zero;
3. it displayed runtime health as `82.2 / 25`; the generated composite is on a
   100-point scale.

The raw calculation is retained below for provenance, but it must not be used
as a release verdict or an agent-quality score. This hardening slice does not
change evaluator policy.

## Raw generated scores and adjudication

| Dimension | Raw generated value | Evidence adjudication |
|---|---:|---|
| Unified benchmark | 56.9 / 100 | **Invalid** because the quality input contains a cleanup false-negative |
| Output quality and fulfillment | 40.0 / 100 | **Invalid**; temporary creation plus required deletion is proven in the journal |
| Runtime execution and economics | 82.2 / 100 | **Provisional**; token/cache/tool data are usable, latency component is not |

No replacement numerical quality score is invented here. The task contracts
are evaluated directly from UI, SQLite, benchmark, and automated-test evidence
in `telemetry-evidence/CRUSOR_AGENT_LIVE_TEST_EVIDENCE.md`.

## Evidence-based task outcome

| Requirement | Evidence | Outcome |
|---|---|:---:|
| Bounded context signaling | Desktop UI displayed `context scan bounded`; scanner tests and benchmark establish bounded deterministic selection | **Passed** |
| Temporary probe lifecycle | Successful `write_file` events plus later cleanup; omission rows at sequences `14246` and `14297` | **Passed** |
| Durable body omission | Journal contains typed `tool_body` omission metadata instead of source content | **Passed** |
| Synthetic-token redaction | Exact probe value absent from all 70 session journal rows | **Passed** |
| Terminal success/non-zero handling | Exit codes `0`, `1`, and `3` observed with recovery behavior | **Passed** |
| Zero-exit masked-success edge case | Automated `test_terminal_masked_success.py` contracts | **Passed (automated)** |
| Typed verification evidence | Schema-v1 journal events and verification ledger row `51` | **Passed** |

## Runtime and economics measurements

| Metric | Observed value | Interpretation |
|---|---:|---|
| Recorded graph steps | 24 | 14 AI nodes and 10 tool nodes in the exported step table |
| Wall time / per-step latency | Unavailable (`0.00s` recorded) | No latency conclusion is valid for this session |
| Cumulative input tokens | 347,694 | Sum of per-call prompt usage, not unique context tokens |
| Output tokens | 21,307 | Sum of per-call output usage |
| Cache-read tokens | 217,600 | Provider-reported cache contribution |
| Prompt-cache ratio | 62.6% | `217,600 / 347,694`; below the audit target of 70% |
| Estimated provider cost | $0.0628 USD | Rate-card estimate; above the audit target of $0.05/task |
| Failed tool results | 4 | Host-capability discovery, one edit, and two terminal attempts |

The separate live evidence reports 22 reasoning/tool steps from the desktop
turn counter. That UI count and this export's graph-node count use different
units, so neither is substituted for the other.

### Provisional runtime sub-scores from the generator

| Component | Raw value | Validity |
|---|---:|---|
| Latency efficiency | 25.0 / 25 | **Invalid:** duration telemetry missing |
| Prompt cache stability | 17.5 / 25 | Supported by provider cache-token counts |
| Tool correctness and safety | 18.9 / 25 | Supported by tool-result statuses |
| Batching and concurrency | 20.7 / 25 | Generator-derived; no independent end-to-end timing proof |

## Actionable findings

1. **Fix evaluator semantics separately:** temporary artifacts explicitly marked
   for cleanup must not trigger the zero-mutation penalty.
2. **Repair timing telemetry:** unknown duration must render as `N/A`, never
   `0.0s` or a perfect latency score.
3. **Reduce repeated input context:** 347,694 cumulative input tokens and a
   62.6% cache ratio indicate room for better static-prefix caching and context
   reuse. This is separate from persistence redaction.
4. **Improve first-attempt tool correctness:** diagnose the host-capability,
   edit, and terminal failures rather than retrying equivalent shapes.
5. **Keep cost claims rate-card-qualified:** the $0.0628 value is an estimate,
   not a provider invoice.

## Recorded execution log

Durations are shown as `N/A` because the source records contained `0.00s` for
every step.

| Step | Node | Duration | Tokens (input/output) | Tools and recorded status |
|---:|---|---:|---:|---|
| 1 | AI | N/A | 21,697 / 4,401 | `think`, `todo_list`, `list_files`, `discover_host_capabilities` proposed |
| 2 | Tools | N/A | — | `think` pass; `todo_list` pass; `list_files` pass; `discover_host_capabilities` fail |
| 3 | AI | N/A | 9,874 / 721 | two `write_file` calls and one `edit_file` proposed |
| 4 | Tools | N/A | — | both `write_file` calls pass; `edit_file` fails |
| 5 | AI | N/A | 23,609 / 6,855 | read, terminal, listing, search, and capability tools proposed |
| 6 | Tools | N/A | — | two terminal attempts fail; remaining listed tools pass |
| 7 | AI | N/A | 24,529 / 2,116 | `read_file`, `terminal`, `search_files` proposed |
| 8 | Tools | N/A | — | all three pass |
| 9 | AI | N/A | 25,051 / 230 | `think`, `terminal` proposed |
| 10 | Tools | N/A | — | both pass |
| 11 | AI | N/A | 25,522 / 513 | `terminal` proposed |
| 12 | Tools | N/A | — | `terminal` passes |
| 13 | AI | N/A | 25,646 / 459 | four verification calls proposed |
| 14 | Tools | N/A | — | four verification calls pass |
| 15 | AI | N/A | 26,113 / 168 | `todo_list` proposed |
| 16 | Tools | N/A | — | `todo_list` passes |
| 17 | AI | N/A | 26,353 / 865 | no tool call |
| 18 | AI | N/A | 27,172 / 3,302 | `think`, `write_file` proposed |
| 19 | Tools | N/A | — | both pass |
| 20 | AI | N/A | 27,459 / 132 | `verify`, `terminal`, `typecheck_workspace` proposed |
| 21 | Tools | N/A | — | all three pass |
| 22 | AI | N/A | 27,679 / 613 | no tool call |
| 23 | AI | N/A | 28,418 / 813 | no tool call |
| 24 | AI | N/A | 28,572 / 119 | no tool call |
