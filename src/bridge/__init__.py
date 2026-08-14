"""PulseAI bridge (P2 M1) — the ONLY door between the fork and the engine.

The VS Code fork (PulseCode, contrib/pulse) spawns this module as a
sidecar process and talks newline-delimited JSON-RPC over stdio. The
engine's internals stay frozen at 437 green; everything the fork can
ask for flows through this file's protocol v1.

Protocol v1 (frozen, see docs/P2-roadmap.md Phase 0.4):
  client -> engine : hello | prompt | safety_reply | shutdown
  engine -> client : hello | token | tool_call_start | tool_call_end
                     | safety_request | telemetry | turn_done
                     | checkpoint_event | echo | error
"""
