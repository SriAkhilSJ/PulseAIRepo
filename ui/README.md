# PulseAI IDE UI Lab

Browser-testable source for the two PulseAI IDE product surfaces:

1. **Agent UI** — compact, current-workspace execution surface.
2. **Agent Manager** — wide, multi-workspace control plane.

The UI Lab is development tooling, not a separate web product. Production registration remains a first-party Code OSS workbench contribution under:

```text
src/vs/workbench/contrib/pulseai/
```

The contribution owns the editor view, manager editor, native Code OSS actions, and the Python sidecar. It does not use an extension manifest or the extension host.

## Run

```bash
npm install
npm run dev
```

Open the Vite URL and switch among **Agent UI**, **Agent Manager**, and the development-only **Tool Gallery**. Use **Replay stream** to exercise deterministic incremental rendering. Approval and tool disclosures are interactive. The Tool Gallery covers all 34 current runtime names and specialized renderer families; it is not a third production surface.

## Build

```bash
npm run build
```

## Integration boundary

The portable UI consumes a host contract rather than importing Code OSS services directly:

- Browser lab: deterministic mock/replay host
- Real browser development: WebSocket-to-stdio adapter
- PulseAI IDE: first-party `/contrib/pulseai/` workbench host

Editor-specific operations—native diffs, open/reveal file, diagnostics, terminal, SCM, notifications, storage, workspace trust, and process management—are performed by the contribution host.

## Product constraints

- Public product name: **PulseAI IDE**
- User-facing agent: **Pulse**
- No token/activity graph or node-canvas UI
- Usage is shown as direct numeric evidence
- Theme-aware colors; cyan is the Pulse state, not the error state
- Agent code never lives under `/extensions/`
