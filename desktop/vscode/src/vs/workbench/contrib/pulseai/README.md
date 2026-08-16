# PulseAI Workbench Contribution

First-party Code OSS home for PulseAI IDE.

```text
pulseai/
├── browser/           Agent View, Pulse Manager, shared renderer/host, native adapters
├── common/            protocol, renderer, tool-catalog, capability, and worker contracts
├── electron-browser/  desktop utility-worker engine client and registration
└── node/              validated Python process owner and IPC server
```

The compact Agent `ViewPane` and wide Pulse Manager `EditorPane` mount one framework-neutral renderer backed by one singleton Protocol v2 event model. The renderer covers streaming conversation, the 34-tool family catalog, compact disclosures, approvals, plans, verification, telemetry, engine state, and dense composers. A web-safe no-process engine fallback keeps common hosts constructable; the desktop entrypoint replaces it with the utility-process implementation.

The IDE chrome stays VS Code Dark 2026 native-neutral; Pulse contributes semantic colors only (`media/pulseAI-tokens.css`: cyan for running/focus/primary actions, violet for delegation, green for verified, amber for approval/warning, red for failure/destructive). No global workbench chrome is recolored, so user color customizations and high-contrast themes remain authoritative. The renderer uses the same pulse-and-agent-node brand geometry as the packaged platform icons.

Native adapters expose dirty buffers, diagnostics, language providers, trust, diffs/bulk edits, workspace search, SCM, tests, tasks, and terminal execution. The renderer never imports Electron, Node, or those Code OSS internals. No extension manifest or activation event is permitted.
