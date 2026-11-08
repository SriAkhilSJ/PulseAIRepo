# Desktop Build Report

## 1. Environment

| Item | Value |
|---|---|
| Node | `v24.18.0` |
| npm used | `11.6.2` (`npx --yes npm@11.6.2`) |
| System npm | `12.0.2` (rejected by preinstall) |
| Electron | `42.8.1` |
| TypeScript | `@typescript/typescript6@6.0.2` (`bin/tsc6`) |
| Lockfile | unchanged (`package-lock.json` restored after install) |

## 2. Dependency restore

The existing `node_modules/electron` had a local `exports` map without a
`types` condition; `index.mjs` was a browser stub. The lockfile's registry
package has `types: electron.d.ts` and no `exports` map.

`npm install` with npm 11 was insufficient. `npm ci` restored the tree, but
native `node-gyp` builds failed because the box has Visual Studio **18** while
node-gyp supports VS 2022/2019. `npm ci --ignore-scripts` restored the JS/type
tree:

```text
added 1582 packages
```

After restore:

- `node_modules/electron/electron.d.ts` present;
- `node_modules/typescript/bin/tsc6` present;
- `node_modules/@types/trusted-types` present;
- package-lock unchanged.

The native build gap is a toolchain limitation and is documented; it does not
affect TypeScript compilation.

## 3. Full compile

```powershell
cd desktop\vscode
npm run compile
```

Result:

```text
[crusorai-compile] tsc finished
[crusorai-compile] resources copied: 731 files (css / ttf / wasm / html / media)
[crusorai-compile] done: out/ is ready
Finished 'compile' after 13 min
```

Exit: **0**. No TypeScript errors. `BUILD_INFO.json` was stamped with source
commit `7d4a4cc587bde12d7fc89d5c0714d2ef4ac406ee`.

## 4. Contribution bundle

```powershell
node scripts/emit-crusorai-bundle.mjs
```

Result:

```text
[emit] copied 8 media file(s)
[emit] DI check ok (11 DI-injected file(s) carry __param)
[emit] wrote 42 file(s)
```

The emitter recomputed `SOURCES_HASH` and `SOURCES_MANIFEST.json` from the
current contribution sources. The generated renderer bundle contains the Live11
submission fix.

## 5. Electron runtime rebuild

The repo's actual runtime packaging task is:

```powershell
npm run electron        # node build/lib/electron.ts
```

It deletes and rebuilds `.build/electron` from the pinned Electron 42.8.1
artifact. Backup and rebuild were performed without launching Electron.

Result:

- `.build/electron/CrusorAI.exe` rebuilt at `2026-11-08T07:29:24`;
- size 221,944,832 bytes;
- SHA-256 `49486b2e…c4fd6d4` — **identical to the pre-rebuild pinned artifact**
  (deterministic package);
- `version` file: `42.8.1`;
- 75 files in the rebuilt runtime tree.

The rebuild log is `electron_runtime_build.log`.

## 6. Artifact manifest

`BUILD_MANIFEST.json` records Git commit/branch/dirty state, Node/npm/Electron/
TypeScript versions, build command, source hash, manifest hash, renderer/worker
hashes, executable SHA-256, and build timestamp. See `ARTIFACT_PROVENANCE.md`.
