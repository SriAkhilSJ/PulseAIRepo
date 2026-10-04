# Crusor Webview (CopilotKit host)

React + TypeScript + Vite SPA that hosts the CopilotKit `CopilotChat` surface
for Crusor. In the IDE it is framed by the workbench (the CopilotKit tab,
`crusorai.copilotWebview.*`); in development it runs standalone with HMR.

## Ports

| Process | Port | Started by |
|---|---|---|
| Vite dev server | `5173` | `npm run dev` |
| Copilot Runtime (`server.ts`) | `8200` | `npm run runtime` |
| Python AG-UI agent | `8123` | `uv run python -m uvicorn src.server:app --port 8123` |

The runtime reaches the agent through an AG-UI `HttpAgent` pointed at
`LANGGRAPH_DEPLOYMENT_URL` (default `http://localhost:8123/`). CopilotKit
Intelligence is **optional**: without `INTELLIGENCE_API_KEY` the runtime stays
in plain SSE mode and talks to the agent directly, so no CopilotKit Cloud
account is required. Vite proxies the relative `/api/copilotkit` to `:8200`
(override the upstream with `COPILOT_RUNTIME_ORIGIN`, the port with
`COPILOT_RUNTIME_PORT`), which is why the app works from any origin.

## Commands

```bash
npm ci
npm run dev        # Vite dev server :5173
npm run runtime    # Copilot Runtime :8200
npm run build      # tsc -b && vite build  (postbuild then copies into the fork)
npm run test       # vitest run — provider-free, no API key, no tokens spent
npm run lint       # oxlint
npm run preview    # vite preview
```

## Shipping a build into the IDE

A workbench document may only frame `frame-src 'self'`, so the built SPA has
to live *inside* the fork. `scripts/copy-into-vscode.mjs` (run automatically
after `npm run build`) copies `dist/` to:

- `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/media/crusorai-spa/`
  — the durable copy; the fork's `npm run compile` carries it into `out/`
- `desktop/vscode/out/.../media/crusorai-spa/` — written too when `out/` exists,
  so an already-built window picks up the new bundle without waiting for a
  recompile

The tab reads it at `crusorai.copilotWebview.url = "local"` (the default).

## End-to-end check

```bash
npx playwright install chromium
# requires :8123 + :8200 + :5173 all running
npx playwright test crusor-webview/e2e-verify.spec.ts
```

## Layout

| Path | Role |
|---|---|
| `server.ts` | CopilotRuntime + optional CopilotKitIntelligence, `HttpAgent` → Python AG-UI |
| `vite.config.ts` | dev port 5173, runtime proxy |
| `src/a2ui/` | catalog / definitions / renderers for the flat A2UI v0.9 card wire format (`{ id, component, ...props }`) |
| `src/__tests__/` | vitest component and render tests |

Wiring and terminal-by-terminal setup live in the root
[`README.md`](../README.md) § "Run the Crusor Webview (CopilotKit)".
