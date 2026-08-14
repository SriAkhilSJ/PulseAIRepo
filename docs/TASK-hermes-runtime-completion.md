# Task: Complete Hermes Runtime Values in PulseAI

**Status:** COMPLETE — ready for founder-supplied API-key live evaluation  
**Rule satisfied:** no live Retest-3 was run during architecture work.

## P0 — load-bearing runtime invariants

- [x] Explicit IDs: workspace, stable session, runtime session, turn, event, tool call, lineage.
- [x] Session-scoped event subscriptions and history replay.
- [x] Durable SQLite event journal: tool intent commits before execution; result commits before UI completion.
- [x] Pre-execution approval broker with diff payload, session matching, policy modes, and timeout-deny.
- [x] Persistent verification evidence: passed/failed/stale/unverified/unavailable, targeted/full.
- [x] Unified tool middleware for direct, parallel, and inner PTC calls.
- [x] Separate cancel, active-turn steer, and next-turn queue controls.
- [x] Foreground terminal commands observe hard session cancellation.
- [x] Real bridge prompt wiring; production path no longer returns `stub: true`.

## P1 — lifecycle and construction

- [x] Managed sub-agent handles: launch/status/wait/cancel/result.
- [x] Child capability subset enforcement, strict tool binding, signed handles, lifecycle events.
- [x] Runtime factory owns journal, verification, and control services; isolated instances supported.
- [x] Bridge session create/load/resume/list/fork and durable event replay.
- [x] Bridge checkpoint list/restore.
- [x] Bridge sub-agent launch/status/cancel/result.
- [x] Structured usage, verification, checkpoint, approval, sub-agent, and degraded-runtime events.
- [x] Dashboard defaults to loopback, explicit CORS origins, and requires a token for non-loopback bind.

## Verification

- [x] Behavior-contract tests for identities, isolation, approval, durability, verification, controls, factory, and child scope.
- [x] Bridge subprocess tests over real stdio using an injected local echo runner (no API key).
- [x] Focused runtime suite: **154 passed** during the first runtime pass; later expanded focused checks also green.
- [x] README-equivalent suite after runtime work: **589 passed, 1 upstream deprecation warning**.
- [x] No live provider call or Retest-3 run used to obtain these results.
- [ ] After this document: remove generated pytest/cache/venv directories, then wait for API key.

## Operational truth

- Cancel is immediate for the graph between iterations and for foreground terminal processes. An already in-flight provider HTTP request remains bounded by the existing 60-second provider timeout because LangChain providers do not expose one uniform cross-provider socket-abort API.
- The bridge test echo runner is enabled only by `PULSEAI_BRIDGE_RUNNER=echo`; production defaults to the real `stream_agent` path.
- `PULSEAI_PARALLEL_TOOLS=off` deliberately restores legacy ToolNode behavior for compatibility, including its historical race characteristics. Normal operation uses the durable conflict-aware path.
