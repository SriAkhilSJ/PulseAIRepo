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
