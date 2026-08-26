# Attempt 11 Product-Delivery Boundary Repair

Date: 2026-08-26

Scope: provider-free source repair after the accepted completion-integrity
revalidation. The historical Attempt-11 workspace and evidence were read only.
No provider request, probe, desktop turn, cap increase, or product rerun occurred.

## Failure boundary

The earlier completion repair made an exhausted, unverified run honest, but it
did not preserve enough bounded capacity to make the product complete. Attempt
11 spent 27,606 tokens on three output-limit continuations, then repeatedly
re-sent landed file bodies. After response 9 the turn had consumed 95,735 of its
120,000-token ceiling. Requests 10 and 11 consumed 17,904 and 17,923 input
tokens respectively; the terminal check then crossed the cap and the next call
was the no-tools grace response. The product still lacked both local Three.js
modules and used `MAX_STEPS_LOOP` without injecting its definition.

## Current Hermes comparison

A fresh checkout of `NousResearch/hermes-agent` at
`b3a2065ff345f849b29178da67b5ed70172dc525` was inspected before this repair.
Useful current mechanics are:

- a thread-safe consume/refund iteration budget;
- explicit incomplete-response continuation;
- a pending final-response candidate while bounded verification nudges run;
- workspace-aware verification evidence and detected verification recipes; and
- budget exhaustion normalized as non-completion rather than success.

Hermes does **not** directly provide the bounded reserve Pulse needs here. Its
parent loop defaults to an effectively unlimited iteration count, and current
verify-on-stop behavior is opt-in/off by default. Pulse therefore adapts the
bounded verification-continuation idea but does not copy unlimited spending or
weaken its mandatory evidence gate.

## Repair

### 1. Existing-cap verification reserve

`src/graphs/budget.py` now marks the final bounded slice of both ceilings as a
verification reserve:

- 30,000 tokens by default (`AGENT_VERIFICATION_TOKEN_RESERVE`); and
- six iterations by default (`AGENT_VERIFICATION_ITERATION_RESERVE`).

Each reserve is bounded to at most half of its corresponding configured cap.
The total caps are unchanged. Once either threshold is reached after code has
landed, `chat_graph._resolve_bound_tools` enters `verification_reserve`: broad
feature/scaffold/web exploration is removed while reads, dependency repair,
static/build commands, terminal lifecycle, and browser verification remain.
The ordinary hard exhaustion and no-tools grace behavior are unchanged.

### 2. Landed mutation payload compaction

Pulse previously summarized ToolMessage output but replayed the complete
assistant-side `write_file`/`edit_file` arguments on every later request.
`compact_file_mutation_arguments` now redacts large payload fields from old,
successfully landed mutations on the request-only history copy. It preserves:

- tool name, call id, path, and call/result pairing;
- the newest successful mutation verbatim for immediate correction;
- every failed/truncated mutation verbatim for recovery; and
- the original checkpoint transcript without mutation.

This reduces re-billed input without deleting product files or increasing any
provider cap.

### 3. Deterministic workspace-integrity prerequisite

`src/context/workspace_integrity.py` adds a read-only, provider-free audit for
high-confidence source holes:

- unresolved relative JavaScript/TypeScript imports;
- unresolved common `@/` workspace aliases;
- bare packages absent from package dependency declarations (excluding Node
  built-ins and URL imports); and
- conservative undefined uppercase constants in embedded GLSL code.

This audit is additive. It cannot itself produce a PASS. Completion still
requires fresh executable/static evidence and, for rendered UI tasks, navigation,
non-empty snapshot, and meaningful screenshot receipts. Even a synthetically
passing UI receipt is rejected when the deterministic audit finds unresolved
references. The finish nudge lists the concrete findings for repair.

On the immutable Attempt-11 fixture the audit reports exactly the consequential
boundary:

```text
js/main.js: missing ../vendor/three/three.module.min.js
js/main.js: missing ../vendor/three/controls/OrbitControls.js
js/shaders.js: undefined MAX_STEPS_LOOP
```

## Provider-free verification

Focused repair and adjacent runtime suite:

```text
183 passed in 36.45s
```

Full Python runtime suite:

```text
1013 passed, 3 skipped, 4 failed in 213.41s
```

The same four known suite-order/cache/session-engine baseline failures remain:
one chunk-index background-thread assertion, one repo-map cache object-identity
assertion, and two session-engine registry/wiring assertions. No new failure was
introduced. Python compilation also passed.

## Windows validation

Two earlier evidence commits remain preserved as failures:

- `22b1f8fd` retried and overwrote a failed fixture command instead of stopping,
  so its final green result is not accepted;
- `b90cb579` correctly recorded `DETERMINISTIC_FAIL` after the one-shot runner
  could not import `src` from the `scripts/` launch path.

Runner fix `c6d9c11c` explicitly adds the repository root to `sys.path` and adds
a regression assertion without changing the 183-test count. The fresh one-shot
Windows R3 evidence commit `1b7ce9e1` is accepted after independent review:

```text
Focused tests:       183/183 passed in 261.97s
Fixture findings:      3/3 detected
Protocol tests:        7/7 passed in 14.27s
Protocol generation: current
Compilation:          PASS (9 modules)
Diff check:           PASS
Provider traffic:     0 probes / 0 requests
Verdict:              DETERMINISTIC_PASS
```

All ten manifest hashes independently match. Only the R3 evidence directory was
committed, repair `0370515c` and runner fix `c6d9c11c` are ancestors, no stage
was retried, and focused monitoring maintained approximately 30-second cadence.

## Qualification and status

This establishes provider-free Windows deterministic parity for the source
repair. It does not repair the immutable Attempt-11 product, prove a future
model will use the reserved capacity successfully, or establish browser/live
runtime/product PASS. Attempt 11 remains product **FAIL**. A live turn, provider
probe/request, PR merge, branch deletion, and Agentic UI work remain
unauthorized absent a future explicit decision.
