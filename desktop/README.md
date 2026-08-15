# PulseAI IDE — Selective Code OSS Working Set

This directory is intentionally **not a full VS Code checkout** during UI design.

- Upstream commit: see `UPSTREAM_PIN`
- Product identity: `product.json`
- First-party feature territory: `vscode/src/vs/workbench/contrib/pulseai/`
- Desktop bundle entry point: `build/buildfile.ts`
- Branded platform resources: `resources/{darwin,linux,server,win32}/`
- Required Node version: `.nvmrc`

Only files that PulseAI directly changes are copied here. Upstream reference files are read remotely at the pinned commit and are not vendored unless they must be modified. This prevents a 30,000-file checkout from exhausting the sandbox. `SELECTIVE_MANIFEST.json` pins the upstream and overlay SHA-256 receipts for every copied upstream file.

When the first full build milestone begins, the same pinned commit can be hydrated on the founder's machine. The selective files here overlay that checkout.

## Invariants

1. Pulse is registered from `vscode/src/vs/workbench/contrib/pulseai/`.
2. Pulse never lives under `/extensions/`.
3. `product.json` is the only upstream source edit for identity; generated platform icon replacements are recorded separately under `brand_assets` in the manifest.
4. Workbench colors are contributed as theme-scoped configuration defaults from `/contrib/pulseai/`, never by rewriting a built-in theme extension or forcing global CSS.
5. `workbench.common.main.ts` registers the cross-platform UI contribution; `workbench.desktop.main.ts` separately registers the utility-process sidecar so web builds never load Electron APIs.
6. `build/buildfile.ts` emits `pulseAIWorkerMain` as a desktop-only optimized bundle entry point; string-addressed utility workers are not discovered from the workbench import graph.
7. Exactly four founder-approved upstream **source** files are modified: product branding, two registration files, and that desktop worker bundle entry. Eight platform icon files are intentional branding overlays, generated from `branding/pulseai-mark.svg`.
8. No `node_modules`, build output, Electron binaries, or full upstream source in this sandbox working set.
