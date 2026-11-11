# Native Module Repair — Launch Failure

## 1. Why this file exists

The first authorized LIVE12 launch failed in the Electron main process before a
workbench session existed. The cause was a missing native binding, not the
bridge, the ledger, or the agent.

## 2. Root cause

`desktop/vscode/node_modules/@vscode/policy-watcher` had no
`build/Release/vscode-policy-watcher.node`.

That module was absent because the dependency tree was restored with:

```text
npm ci --ignore-scripts
```

The `--ignore-scripts` flag was necessary because the machine has Visual Studio
18 while node-gyp supports VS 2022 and older. It installs JS packages but skips
every native `node-gyp` build, so all native addons that were previously built
disappeared.

The app imports `@vscode/policy-watcher` from
`NativePolicyService._updatePolicyDefinitions`, reached from
`ConfigurationService.initialize` during `CodeMain.startup`. The uncaught
binding error aborted startup before the workbench and CDP.

## 3. Repair

Prebuilt N-API binaries were copied from the locally installed Microsoft VS Code
(`C:\Users\Administrator\AppData\Local\Programs\Microsoft VS Code\a717861c07\resources\app\node_modules.asar.unpacked`)
into the matching paths under `desktop/vscode/node_modules`:

- `@vscode/policy-watcher/build/Release/vscode-policy-watcher.node`
- `@vscode/sqlite3/build/Release/vscode-sqlite3.node`
- `@vscode/spdlog/build/Release/spdlog.node`
- `@vscode/deviceid/build/Release/windows.node`
- `@vscode/windows-registry/build/Release/winregistry.node`
- `@vscode/windows-mutex/build/Release/CreateMutex.node`
- `@vscode/windows-ca-certs/build/Release/crypt32.node`
- `@vscode/native-watchdog/build/Release/watchdog.node`
- `vsda/build/Release/vsda.node` (package JS wrapper still absent)

Each restored module except `vsda` loads with `require()` under Node 24.

## 4. Scope

- `node_modules` is not part of the repository, the contribution source hash, or
  the desktop executable.
- No `src/`, `out/`, or `.build/electron/` file changed.
- No provider call, reservation, or spend occurred.
- `vsda` is unresolved; it is not on the early main-process crash path.

## 5. What is still needed

A full Electron launch smoke test. That requires an Electron session and
therefore a new explicit authorization; it was not performed automatically
after the abort.
