# Artifact Provenance

## 1. Build identity

| Item | Value |
|---|---|
| Source commit | `7d4a4cc587bde12d7fc89d5c0714d2ef4ac406ee` |
| Branch | `feat/prompt-cache-stabilization` |
| Build command | `npm run compile` |
| Build time | 2026-11-08T15:15:00Z (13 min) |
| Node | `v24.18.0` |
| npm used for install | `11.6.2` |
| System npm | `12.0.2` |
| Electron | `42.8.1` |
| TypeScript | `6.0.2` |
| Working tree | dirty only from unrelated pre-existing changes + pending evidence commit; contribution source hash exact |

## 2. Contribution source hash

Recipe mirrors `scripts/emit-crusorai-bundle.mjs` byte-for-byte: relative POSIX
paths, NUL separators, CRLF→LF bytes, emitter last.

```text
computed = 465a6bb15486775bb643684173b2dbb626d6e936c3e1797488c77d25a0c476a5
shipped  = 465a6bb15486775bb643684173b2dbb626d6e936c3e1797488c77d25a0c476a5
match    = true
files    = 50
```

`SOURCES_MANIFEST.json`:

- 50/50 source files match;
- missing: 0;
- unexpected: 0;
- mismatched: 0.

## 3. Bundles

| Artifact | SHA-256 |
|---|---|
| Renderer service | `e3bf434b969a8e62279042d693708151dbe19941b973a66cc94a8920ac910394` |
| Worker main | `05f842f4743c7a16df28751c20415b039f585100cad809798ee31a4eebd54683` |
| `CrusorAI.exe` | `49486b2ef4d940bdbf9985811a8ed2c808551d6e1353d1b3cf3a4c5b8c4fd6d4` |

Executable: 221,944,832 bytes, Electron 42.8.1. It was rebuilt with
`npm run electron` and is byte-identical to the pinned pre-rebuild artifact.

## 4. Entry points and resources

- `build/buildfile.ts` registers
  `vs/workbench/contrib/crusorai/node/crusorAIWorkerMain`.
- `build/next/index.ts` registers it in the desktop entry list.
- It is **not** in the web entry points.
- 6 preview html/css/js files in `contrib/crusorai/browser/media` are present
  and byte-identical in `out`.
- Native worker output `out/.../node/crusorAIWorkerMain.js` exists.

## 5. Evidence

Raw manifest: `BUILD_MANIFEST.json`.
Verifier: `verify_artifact_provenance.py` (exits 0).
Build log: `desktop_compile.log`.
Emitter log: `desktop_emit_bundle.log`.
Runtime rebuild log: `electron_runtime_build.log`.
