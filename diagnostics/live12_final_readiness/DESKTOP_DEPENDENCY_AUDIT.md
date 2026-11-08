# Desktop Dependency Audit

## 1. Pinned environment

| Item | Value |
|---|---|
| Node | `v24.18.0` (matches `.nvmrc`) |
| System npm | `12.0.2` |
| Required npm | `<12.0.0` (`build/npm/preinstall.ts`) |
| npm used | `11.6.2` via `npx --yes npm@11.6.2` |
| Electron | `42.8.1` |
| TypeScript | `@typescript/typescript6@6.0.2` (`bin/tsc6`) |
| Lockfile | `desktop/vscode/package-lock.json` |
| Package manager | npm (`package-lock.json`; no yarn) |

The repo's preinstall rejects npm >= 12; the install must run with npm 11.
`npx npm@11` alone still inherits the outer `npm_config_user_agent`, so the
install command additionally set:

```text
npm_config_user_agent=npm/11.6.2 node/v24.18.0 win32 x64 workspaces/false
```

## 2. What was wrong

The first full compile failed with 346 TypeScript errors, all centered on the
`electron` module:

```text
TS7016 Could not find a declaration file for module 'electron'
TS2503 Cannot find namespace 'Electron'
```

The installed `node_modules/electron/package.json` had a local `exports` map
without a `types` condition, and `index.mjs` was a browser stub. The package's
real `electron.d.ts` was present but unreachable under
`moduleResolution: nodenext`.

Registry metadata for `electron@42.8.1` has `types: electron.d.ts` and no
`exports` map. The checked-in lockfile is correct; the local `node_modules`
copy had been modified.

## 3. Restore

1. `npm install` with npm 11 was rejected/insufficient:
   - preinstall requires `<12`; first attempt used npm 12 and failed;
   - second attempt with npm 11 user agent passed version check but required
     Visual Studio's C++ toolchain; the box has VS 18, while node-gyp supports
     VS 2022 and older.
2. `npm ci` restored the lockfile tree but native `node-gyp` builds failed for
   the same VS 18/2022 mismatch (`@vscode/fs-copyfile`).
3. `npm ci --ignore-scripts` restored the JS/type dependency tree successfully:

```text
added 1582 packages in 1m
```

After restore:

- `node_modules/electron/package.json` has `types: electron.d.ts` and no
  `exports` map;
- `node_modules/electron/electron.d.ts` exists;
- `node_modules/typescript/bin/tsc6` exists;
- `node_modules/@types/trusted-types` exists;
- package-lock and package.json are unchanged.

The native module build gap is a **toolchain environment limitation** (VS 18 vs
node-gyp's supported VS 2022). It does not affect TypeScript compilation of the
desktop app. It is recorded as a limitation, not hidden.

## 4. Compile

The full compile is run with the repo's command:

```powershell
cd desktop\vscode
npm run compile
```

Result recorded in `DESKTOP_BUILD_REPORT.md` / `desktop_compile.log`.
