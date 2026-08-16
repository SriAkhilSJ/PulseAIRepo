# PulseAI IDE — Canonical Code OSS Fork

`PulseAIRepo/desktop/` tracks two things:

- **`vscode/`** — the canonical, vendored Code OSS checkout at the pinned commit. The full Pulse overlay is applied **in place**: `vscode/product.json`, `vscode/build/buildfile.ts`, and the branded platform resources under `vscode/resources/` are all committed as part of the fork.
- **Fork metadata** at `desktop/` root: `README.md`, `SELECTIVE_MANIFEST.json`, `UPSTREAM_PIN`, `.nvmrc`.

The build runs directly inside `vscode/`:

```bash
cd desktop/vscode
npm install
npm run typecheck-client
npm run valid-layers-check
npm run compile
npm run gulp minify-vscode
```

The pulseai worker entrypoint (`pulseAIWorkerMain`) is emitted as a desktop-only optimized bundle entry by **both** packaging paths: `vscode/build/buildfile.ts` (legacy gulp path) and `vscode/build/next/index.ts` (current esbuild path). String-addressed utility workers are not discovered from the workbench import graph, so each path lists the entry explicitly.

## Invariants

1. Pulse is registered from `vscode/src/vs/workbench/contrib/pulseai/`.
2. Pulse never lives under `/extensions/`.
3. `vscode/product.json` is the only upstream source edit for identity; platform icon replacements are recorded separately under `brand_assets` in the manifest.
4. Global Pulse workbench recoloring was removed (`browser/pulseAIBranding.ts`); the IDE chrome stays VS Code Dark 2026 native-neutral, and Pulse semantic color tokens are scoped to Pulse surfaces only.
5. `workbench.common.main.ts` registers the cross-platform UI contribution; `workbench.desktop.main.ts` separately registers the utility-process sidecar so web builds never load Electron APIs.
6. `vscode/build/buildfile.ts` (legacy gulp path) and `vscode/build/next/index.ts` (current esbuild path) each emit `pulseAIWorkerMain` as a desktop-only optimized bundle entry point; string-addressed utility workers are not discovered from the workbench import graph.
7. Exactly five upstream **source** files are modified in the fork: product branding, the two registration files, and the two desktop bundle entry files (`build/buildfile.ts` for the legacy gulp path, `build/next/index.ts` for the current esbuild path). Eight platform icon files are intentional branding overlays, generated from `branding/pulseai-mark.svg`.
8. Build outputs (`node_modules`, Electron binaries, `out-*`) produced inside `vscode/` are never committed — the vendored tree's nested `.gitignore` protects those.
