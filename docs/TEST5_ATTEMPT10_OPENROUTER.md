# Test 5 Attempt 10 — OpenRouter evidence review

**Date:** 2026-08-25  
**Evidence commit:** `e344bc00e6de2961a2695d4fc7cfa7401ad64c87`  
**Run:** `test5-10-desktop`  
**Model:** `stealth/ox-alpha` through OpenRouter  
**Workspace:** `C:\test5-ws-attempt10`

## Independent verdict

```text
RUNTIME_FAIL / PRODUCT_FAIL
```

The eight-token OpenRouter probe returned HTTP 200 in 2.70 seconds. The live
turn made one provider request and emitted one `llm.response`, but no content,
tool call, or file was produced. The runner then recorded
`OSError: [Errno 22] Invalid argument` and terminated incomplete.

Total endpoint attempts were one probe plus one live-turn request. The receipt's
`provider_call_count: 1` is the live-turn request count and does not include the
probe.

## Verified frame boundary

The committed frame sequence is:

1. `hello`;
2. `session_info`;
3. two `workspace.bound` frames;
4. `turn_started`;
5. one `reasoning` status frame;
6. one `llm.request` exposing only `write_file`;
7. one `llm.response` with:
   - `finish_reason: "lengthlength"`;
   - `incomplete: false`;
   - `content_chars: 0`;
   - `tool_call_count: 0`.

The runtime's exact-match finish-reason normalizer recognizes `length`, but not
the duplicated `lengthlength` string. LangChain streaming aggregation can merge
repeated string metadata by concatenation, so the evidence does not prove the
provider itself emitted that literal malformed value. The confirmed defect is
at Pulse's provider-adapter normalization boundary: an output-limit response
reached graph control flow as `incomplete: false`.

No tool call existed, so no incomplete mutation executed. No request 2 was
observed.

## OSError qualification

The committed evidence records only the exception type/message, not a Python
traceback. The OSError occurred after the malformed response frame, but the
receipt cannot prove that finish-reason handling directly raised it. A future
runner must retain a sanitized traceback for transport/console failures rather
than infer causality from timing.

## Product result

The workspace delivered zero files. Browser/static grading was therefore
impossible and the product verdict is FAIL, not ungraded.

## Evidence quality

Arena independently verified:

- exact evidence parent and evidence-only commit scope;
- implementation/probe-repair ancestry;
- all six manifest entries against committed byte lengths and SHA-256;
- the exact eight-frame sequence and response metadata;
- zero delivered files and no tool calls.

The commit does not contain the required 30-second monitor log, foreground
console transcript, preserved-evidence comparison, or complete product grading
matrix. Those omissions do not change the hard runtime/product failure, but no
claim of active 30-second inspection is supported.

## Disposition

Attempt 10 consumed its one probe and one live turn. No retry, provider traffic,
PR merge, branch deletion, or Agentic UI work is authorized. The next source
task is deterministic only: normalize repeated output-limit metadata, retain a
sanitized runner traceback, and prove both with tests before any future live-run
decision.
