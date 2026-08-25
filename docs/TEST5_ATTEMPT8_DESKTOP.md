# Test 5 Attempt 8 — desktop evidence review

**Date:** 2026-08-25  
**Evidence commit:** `6586d7afab1558274353dd34256f1783503b83c1`  
**Run:** `test5-8-desktop`  
**Workspace:** `C:\test5-ws-attempt8`  
**Evidence:** `bench-results/test5-8-desktop/`

## Verified verdict

**RUNTIME_FAIL / PRODUCT_FAIL.** One provider request returned one successful
`write_file` call. `index.html` landed, but the graph never reached request 2.
The wrapper killed the process after 613.5 seconds without file, frame, or CPU
activity. No `turn_done`, `turn_failed`, or runner-owned `outcome.json` exists.

The product is statically a failure, not merely ungraded: the sole 4,995-byte
Windows artifact ends abruptly in the middle of a CSS rule, has no closing
`style`, `head`, or `html`, no body/canvas/script, no JavaScript or shader, no
local Three.js dependency, and none of the requested runtime behavior. Git's
Linux checkout stores the same text with LF endings at 4,892 bytes.

No retry is authorized.

## Request and loop boundary

The first provider request is exactly the repaired Windows shape:

- model: `sarvam-105b-conversations`;
- roles: system, system, system, human;
- message count/content: 4 / 3,083 characters;
- tool surface: exactly `write_file`;
- tool-schema content: 591 characters;
- SHA-256: `6f436c7d57ab12d36567fb337742b6ae962aefec3f071c8c53f9be734f329bcd`.

Frame order:

1. `turn_started`;
2. `llm.request`;
3. `tool_call_start(write_file)` after about 88.6 seconds;
4. `verification_updated(unverified)`;
5. `tool_call_end(write_file, ok)`;
6. no further graph event for more than ten minutes.

This confirms Sarvam responded to the narrowed contract and Pulse executed its
call. The first confirmed failure boundary is now Pulse's post-tool path, before
request 2—not provider instruction following.

## Post-tool boundary and deterministic repair

Autonomous context intentionally excludes semantic memory, but `progress_node`
still called `record_tool_memory` after every tool result. The first autonomous
tool therefore became the first use of the lazy `MemoryManager`, placing
sentence-transformer/model/database initialization in the unobserved post-tool
path before request 2. There is no event after `tool_call_end`, consistent with
that boundary.

The preserved evidence has no Python stack dump at the moment of the stall, so
it cannot prove the worker's exact instruction pointer; LangGraph's post-node
checkpoint transition is adjacent to the same boundary. The unused semantic
initialization is nevertheless a confirmed architectural fault and is removed
rather than treated as a speculative sole cause.

Repairs:

- autonomous progress no longer records semantic tool memory it will never
  consume;
- the guarded Test-5 wrapper disables optional long-term memory as defense in
  depth;
- streaming request loops now drain async generators with a five-second bound
  before closing, addressing the captured `Task was destroyed but it is
  pending` / un-awaited `Response.aiter_raw.aclose` warnings;
- watchdog termination now writes a durable fallback `outcome.json`;
- every watchdog line now includes LLM-request count, workspace file count, and
  bytes, making the 30-second record self-contained.

These are deterministic repairs only. They do not authorize another live run.

## Windows deterministic validation

Evidence commit `6b8a90b40ff2b5a8244198957669a6e561b787a1` was
independently fetched and verified:

- PowerShell parsed `run_test5_guarded.ps1` with zero errors;
- all five wrapper guard markers were present;
- 72 focused tests passed on Windows Python 3.14.4 in 23.98 seconds;
- changed Python modules compiled cleanly;
- `git diff --check` passed;
- the committed Attempt-8 evidence tree was identical before and after;
- all nine validation-manifest entries match their committed byte length and
  SHA-256 after checkout;
- provider calls were zero.

This validates the then-implemented deterministic contracts on the founder's
Windows runtime. A subsequent Arena repair now closes the identified source
parity gaps by using LangChain's synchronous invocation owner whenever native
streaming is enabled, retaining bounded provider finish metadata, rejecting
all tool calls from token-limited responses with paired error observations,
feeding those observations directly into request 2, and applying an explicit
output cap to both delivery phases. Deterministic fake-provider tests cover the
stream close and request-2 boundary. That follow-up has not run against a live
provider and does not authorize Attempt 9.

### Stream-parity Windows receipt

Desktop evidence commit `503c1972884d6ee190aafb3d9fce7227ef255e84`
records parser, protocol-generator, compilation, diff-check, and Attempt-8
before/after integrity PASS, plus 42 tests passed in 16.63 seconds with one
warning and zero provider calls. Arena independently verified all ten receipt
manifest entries, the exact evidence-parent relationship, implementation
ancestry, evidence-only commit scope, and unchanged committed Attempt-8 tree.

The authorized pytest list contained two additional targets that do not appear
in the committed Windows log: `test_bridge_protocol_v2.py` and
`test_d26_hashed_keys_match_builder_usage_ast`. The receipt therefore proves
all recorded checks passed, but not completion of the full required 50-test
Windows contract. Independent verdict:

```text
RECORDED_CHECKS_PASS / REQUIRED_VALIDATION_INCOMPLETE
```

The founder authorized one missing-check-only follow-up. Evidence commit
`496591a10e93b13d32065b3ac04d74f89d9fecde` records exactly the two omitted
targets: 8 collected, 8 passed in 2.83 seconds on Windows Python 3.14.4, with
zero provider calls. Arena independently verified its exact parent and
implementation ancestry, evidence-only scope, pytest target/count/output, and
all three receipt-manifest byte lengths and SHA-256 values.

Combined Windows focused result:

```text
50 collected / 50 passed / zero provider calls / DETERMINISTIC_PASS
```

This closes the deterministic Windows validation gap. It is not a live runtime
or product PASS and does not authorize Attempt 9 or PR merge.

## Evidence-quality findings

The committed console proves the watchdog itself sampled every 30 seconds from
+30s through +721s. However, `monitor-30s.jsonl` contains only six observations,
starts at +240s, and then groups output at roughly 90–150-second intervals.
Therefore the report's statement that all 30-second intervals were actively
inspected is **not independently supported**. This does not change the runtime
failure.

The Windows evidence manifest records pre-Git CRLF byte hashes. Git normalized
text files to LF on checkout because the evidence path lacked a binary/no-text
attribute. Seven of eight original hashes reproduce exactly by restoring CRLF;
the mixed-line-ending console transcript does not. Future evidence paths must be
marked `-text` before staging so cloned artifacts remain byte-verifiable.
