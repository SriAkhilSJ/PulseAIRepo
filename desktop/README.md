# CrusorAI IDE — Canonical Code OSS Fork

`PulseAIRepo/desktop/` tracks two things:

- **`vscode/`** — the canonical, vendored Code OSS checkout at the pinned commit. The full Crusor overlay is applied **in place**: `vscode/product.json`, `vscode/build/buildfile.ts`, and the branded platform resources under `vscode/resources/` are all committed as part of the fork.
- **Fork metadata** at `desktop/` root: `README.md`, `SELECTIVE_MANIFEST.json`, `UPSTREAM_PIN`, `.nvmrc`.

### The manifest receipts

`SELECTIVE_MANIFEST.json` records, for every file the overlay edits, the upstream hash it started
from, the hash of the overlay as committed, and the source each platform icon was generated from.
`src/tests/test_desktop_contrib_overlay.py` checks those receipts against the tree, so they must move
whenever a pinned file does.

**Never hand-edit the hashes.** Recompute them:

```bash
python scripts/refresh_selective_manifest.py           # check only; exits 1 on drift
python scripts/refresh_selective_manifest.py --write    # refresh, guarded
```

The tool refuses to write while an integrity problem is present — most importantly an overlay file
whose bytes have become identical to its recorded upstream, which means the fork's edit was lost and
refreshing the receipt would erase the evidence. It reads the LF-hashing rule from `.gitattributes`,
so a Windows checkout with `core.autocrlf=true` produces the same receipts.

The build runs directly inside `vscode/`:

```bash
cd desktop/vscode
npm install
npm run typecheck-client
npm run valid-layers-check
npm run compile
npm run gulp minify-vscode
```

The crusorai worker entrypoint (`crusorAIWorkerMain`) is emitted as a desktop-only optimized bundle entry by **both** packaging paths: `vscode/build/buildfile.ts` (legacy gulp path) and `vscode/build/next/index.ts` (current esbuild path). String-addressed utility workers are not discovered from the workbench import graph, so each path lists the entry explicitly.

## Branding & theme (Interface agent)

The fork ships **CrusorAI Dark** as the default color theme
(`extensions/theme-defaults/themes/crusorai-dark.json`), generated from upstream
`2026-dark.json` by `scripts/generate_crusorai_theme.py`. The theme uses a
cohesive grey palette (`#2d2d2d` / `#3c3c3c`) for buttons, badges, focus
borders, and links — matching the welcome screen card style.

`CrusorAI Dark` is registered and made default from
`extensions/theme-defaults/package.json` (`contributes.themes` +
`contributes.configurationDefaults`) — **additive, no upstream source file is
modified**, so invariant 7 still holds.

The empty-window welcome screen (`editorGroupWatermark.ts`) displays:
- CrusorAI logo (center, SVG rendered via `createElementNS` for TrustedTypes safety)
- "Crusor AI" title + "AI-Powered Code Intelligence" subtitle
- 4 action cards (Open Project, Open File, Clone from GitHub, New File)
- Recent Projects section from workbench history

**Copilot (`src/vs/workbench/contrib/chat/`, `extensions/copilot/`) is
deliberately untouched** — it is the reference implementation for Crusor's
integration work. Do not delete or edit it. See
`docs/DESIGN/COPILOT_INTEGRATION_ANALYSIS.md` and
`docs/DESIGN/FORK_REBRANDING.md` §5.

Remaining rebranding gaps are tracked in `docs/DESIGN/FORK_REBRANDING.md` §4.

## Invariants

1. Crusor is registered from `vscode/src/vs/workbench/contrib/crusorai/`.
2. Crusor never lives under `/extensions/`.
3. `vscode/product.json` is the only upstream source edit for identity; platform icon replacements are recorded separately under `brand_assets` in the manifest.
4. Global Crusor workbench recoloring was removed (`browser/crusorAIBranding.ts`); the IDE chrome stays VS Code Dark 2026 native-neutral, and Crusor semantic color tokens are scoped to Crusor surfaces only.
5. `workbench.common.main.ts` registers the cross-platform UI contribution; `workbench.desktop.main.ts` separately registers the utility-process sidecar so web builds never load Electron APIs.
6. `vscode/build/buildfile.ts` (legacy gulp path) and `vscode/build/next/index.ts` (current esbuild path) each emit `crusorAIWorkerMain` as a desktop-only optimized bundle entry point; string-addressed utility workers are not discovered from the workbench import graph.
7. Exactly five upstream **source** files are modified in the fork: product branding, the two registration files, and the two desktop bundle entry files (`build/buildfile.ts` for the legacy gulp path, `build/next/index.ts` for the current esbuild path). Eight platform icon files are intentional branding overlays, generated from `branding/crusorai-mark.svg`.
8. Build outputs (`node_modules`, Electron binaries, `out-*`) produced inside `vscode/` are never committed — the vendored tree's nested `.gitignore` protects those, with **one deliberate exception**: the compiled Crusor panel `out/vs/workbench/contrib/crusorai/**` is tracked (nested `.gitignore:16-23`, minus `browser/media/crusorai-spa/`) so a fresh checkout boots a working panel instead of a silently missing one. `npm run compile` re-emits it, and since 2026-10-03 the task also re-emits any torn `.js` a flaky disk wrote (first 4 KB kept, the rest NUL-filled) rather than shipping a file that throws `SyntaxError` at runtime.
