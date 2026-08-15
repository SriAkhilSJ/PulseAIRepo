# PulseAI IDE — Selective Code OSS Working Set

This directory is intentionally **not a full VS Code checkout** during UI design.

- Upstream commit: see `UPSTREAM_PIN`
- Product identity: `product.json`
- First-party feature territory: `src/vs/workbench/contrib/pulseai/`
- Desktop bundle entry point: `build/buildfile.ts`
- Required Node version: `.nvmrc`

Only files that PulseAI directly changes are copied here. Upstream reference files are read remotely at the pinned commit and are not vendored unless they must be modified. This prevents a 30,000-file checkout from exhausting the sandbox. `SELECTIVE_MANIFEST.json` pins the upstream and overlay SHA-256 receipts for every copied upstream file.

When the first full build milestone begins, the same pinned commit can be hydrated on the founder's machine. The selective files here overlay that checkout.

## Invariants

1. Pulse is registered from `src/vs/workbench/contrib/pulseai/`.
2. Pulse never lives under `/extensions/`.
3. `product.json` is the only branding edit.
4. `workbench.common.main.ts` registers the cross-platform UI contribution; `workbench.desktop.main.ts` separately registers the utility-process sidecar so web builds never load Electron APIs.
5. `build/buildfile.ts` emits `pulseAIWorkerMain` as a desktop-only optimized bundle entry point; string-addressed utility workers are not discovered from the workbench import graph.
6. Exactly four founder-approved upstream files are modified: product branding, two registration files, and that desktop worker bundle entry.
7. No `node_modules`, build output, Electron binaries, or full upstream source in this sandbox working set.
