"""CrusorAI Bridge — the only door between CrusorAI IDE and the engine.

The first-party Code OSS contribution (`contrib/crusorai`, committed inside
the canonical fork at `desktop/vscode/`) starts this module as a local
sidecar and exchanges newline-delimited JSON frames over stdio. Bridge
Protocol v2 covers sessions, streaming, tools, approvals, turn control,
verification, checkpoints, sub-agents, telemetry, and event replay. Legacy v1
handshakes remain accepted during the editor transition; each hello response
returns the negotiated version.

Canonical method/event names live in `protocol_v2.json` and generate the
TypeScript name contract consumed by the fork overlay.
"""
