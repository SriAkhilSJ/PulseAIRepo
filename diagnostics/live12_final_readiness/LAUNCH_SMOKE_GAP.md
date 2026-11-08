# Launch Smoke Gap

## What the readiness evidence covered

- Full TypeScript compile (`npm run compile`, exit 0).
- Contribution bundle emission and 50/50 source hashes.
- Native worker registration and preview assets.
- `CrusorAI.exe` hash and version.
- 366 provider-free tests.

## What it did not cover

Starting the desktop app. The first authorized LIVE12 attempt did exactly that
and failed in the Electron main process before any workbench session:

```text
Error: Could not locate the bindings file
  @vscode/policy-watcher/build/Release/vscode-policy-watcher.node
  at NativePolicyService._updatePolicyDefinitions
  at ConfigurationService.initialize
  at CodeMain.initServices
  at CodeMain.startup
```

`npm ci --ignore-scripts` had installed the JS tree but skipped every native
build. The compile does not exercise those addons; the launch does.

## Repair

Eight native binaries were restored from the locally installed Microsoft VS Code
(`a717861c07`), which uses N-API and loads under Electron 42 / Node 24:

`policy-watcher`, `sqlite3`, `spdlog`, `deviceid`, `windows-registry`,
`windows-mutex`, `windows-ca-certs`, `native-watchdog`.

`vsda` remains unresolved (package wrapper absent); it is used by the sign
service / extension host, not the early startup path.

## Status

The repair is **not** proven by a launch. The failed attempt is preserved at
`diagnostics/live12_run_20261108_085953/`. A new Electron session requires a new
explicit authorization; no automatic retry was performed.

## Lesson for the readiness matrix

A desktop acceptance readiness gate must include an actual process launch to a
ready workbench, not only a compile and artifact hashes. That gate is now listed
as failed-then-repaired in `ACCEPTANCE_MATRIX.md`.
