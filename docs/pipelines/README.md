# Reference pipelines for multi-platform targets

These are **inert templates**: GitHub only runs workflows in
`.github/workflows/`, so nothing here fires by accident. Copy the file you need
into `.github/workflows/` and adjust the paths.

Each pipeline has the same three jobs, which is the whole point:

1. **Provision** the toolchain (JDK/SDK/NDK, Xcode, Rust, Flutter, Node) and
   cache it.
2. **Prove** the app with the *agent's own* pipeline — `src.targets.registry.run`
   — so CI consumes exactly the receipt the agent produces locally
   (`✅ TARGET VERIFICATION PASSED …`).
3. **Publish** evidence (`<workspace>/.crusorai/target-evidence/**`: screenshots,
   UI dumps, logs, receipts) as build artifacts, pass or fail.

| File | Targets | Runner | Notes |
|---|---|---|---|
| `android.yml` | native Android / Kotlin / Java | ubuntu-latest (KVM) | `ReactiveCircus/android-emulator-runner@v2`, API matrix, AVD snapshot cache |
| `ios.yml` | native iOS / SwiftUI | macos-14 | simulator + `xcodebuild`, optional TestFlight upload |
| `flutter.yml` | Flutter (android, ios, macOS, Windows, Linux) | matrix | five real platforms from one codebase |
| `react-native.yml` | React Native / Expo | ubuntu + macos | Metro must be up before a debug build is proven |
| `desktop-tauri.yml` | Tauri v2 | matrix (mac/linux/win) | `tauri-action` release + headless verify (xvfb) |
| `desktop-electron.yml` | Electron | matrix | CDP `_electron`/Playwright verification + electron-builder release |

Two rules these pipelines follow, both learned the hard way in this repo:

* **Never merge on a build alone.** `registry.run(...)` returns
  `⛔` (missing toolchain) / `❌` (failed stage) / `✅` (proved), and the job exits
  non-zero unless it is `✅`. A green compile is not a working app.
* **Always upload evidence.** A failed pipeline with a screenshot, a UI dump and
  a log slice is debuggable in one read; a failed pipeline with "exit 1" is not.
