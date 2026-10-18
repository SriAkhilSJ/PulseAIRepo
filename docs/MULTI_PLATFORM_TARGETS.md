# Multi-platform delivery: mobile, desktop, and Android targets for the Crusor agent

Status: **implemented in this repo** (target layer + agent surface + hermetic tests); the
Windows Android CLI/emulator setup still needs a native-machine run, and the
external tooling choices and CI pipelines below remain templates.
Audience: whoever has to make the agent box a mobile/desktop app with the same
confidence it currently boxes a website.

---

## 0. TL;DR

The agent's current contract is *"a UI task is done when a real browser rendered
it and the receipt says so."* `src/targets/` generalizes exactly that contract to
**android, ios, flutter, react-native, desktop (electron), and tauri** — same
shape, same verdict rules, one entry point:

```python
from src.targets import registry
from src.targets.runner import TargetRequest

receipt = registry.run(workspace, "android", TargetRequest(mode="verify"))
print(receipt.to_text())      # ✅ / ❌ / ⛔ TARGET VERIFICATION … and receipt.passed
```

Six things make that work, all of them deliberate:

| Layer | File(s) | Job |
|---|---|---|
| Detection | `src/targets/detect.py` | "What kind of app is this workspace?" (manifest/PBX/`pubspec`/`expo`/`tauri.conf`) |
| Toolchain doctor | `src/targets/toolchain.py` | Exact missing binary, per-OS install hint, before any long build starts |
| Providers | `src/targets/providers/*.py` | Per-platform stage plans (build → install → launch → prove → cleanup) |
| Runner | `src/targets/runner.py` | Sequential stages, timeouts, process reaping, cleanup always runs |
| Evidence/probes | `src/targets/evidence.py`, `probes.py` | Screenshots, UI dumps, logs, foreground/window/CDP liveness — hashed, on disk |
| Agent surface | `src/tools/target_tools.py` | 9 tools (`verify_target_app`, `device_*`, …) bound only to mobile/desktop postures |

Two rules are enforced by tests (`src/tests/test_target_pipeline.py`, 45 tests):

1. **A green build is not a working app.** `mode="build"` receipts are labelled
   static/typecheck evidence only.
2. **Proof is platform-specific.** A successful `verify_target_app` receipt
   counts as static+typecheck+navigate+snapshot+screenshot for the target it
   proved (android/ios/flutter/react-native/desktop) — but a **web** target
   receipt does *not* replace browser proof, and the receipt always names the
   platform it was produced on (`src/graphs/gates.py::_target_receipt_proves_render`).

---

## 1. What the repo already had, and the gap

| Capability | Website (before) | Multi-platform (now) |
|---|---|---|
| Create | terminal create commands (`create-next-app` / `flutter create` / `create-expo-app` / `create-tauri-app`) — scaffold tools deleted 2026-10-18 |
| Build | `run_terminal` + `npm run build` | `build_target` (per-target argv, timeout multiplier) |
| Prove render | `verify_ui_workspace` / `verify_ui_routes` (browser receipt) | `verify_target_app` (device/window receipt) |
| Interact | browser tools (CDP) | `device_action`, `device_screenshot`, `device_ui`, `device_logs` |
| Toolchain | implicit (Node is assumed) | `check_target_toolchains` → `⛔ … UNAVAILABLE` + install commands |
| CI | not in repo (`.github/workflows/` absent) | templates in `docs/pipelines/` |

The gap was never "run `gradle assembleDebug`". It was: *the agent must know
which target it is building, must refuse to burn 10 minutes on a missing SDK,
must prove the app actually opened on a device, and must not claim success from a
compile log.* That is what this layer adds.

---

## 2. Architecture

### 2.1 One receipt, three verdicts

```
🧭 TARGET PLAN        dry run, nothing executed (never passed=True)
⛔ ... UNAVAILABLE    missing toolchain — carries per-tool Install: lines
❌ ... FAILED         a required stage failed (log tail included)
✅ ... PASSED         every required stage passed and a probe proved the app ran
```

Probes are deterministic Python (`Stage.handler`), never model judgement:
`foreground_is_app` (the resumed activity *is* our package), `window_open` +
`cdp_ready` (a real window answered on the debugging port), `process_alive`
(zombie-aware), `screenshot_quality` (not a blank frame), `logcat_scan` (crash
findings fail the receipt), `assertions` (declared text present in the live UI
dump).

### 2.2 Where it plugs into the agent

* `src/agents/runtime_profile.py` — `CAP_MOBILE_APP` / `CAP_DESKTOP_APP` with
  trigger-word lists (`profile names: mobile_engineering, desktop_engineering,
  multi_platform_engineering`). Bare "app"/`app.py` is deliberately *not* a
  trigger.
* `src/tools/toolsets.py` — `_TARGET_TOOLS`, `_TARGET_SCAFFOLD_TOOLS`,
  `_MOBILE_DEVICE_TOOLS`; "build an android app" now resolves 45 tools
  (vs 13 for a plain chat turn).
* `src/graphs/chat_graph.py` — 67 bound tools, target tools included.
* `src/graphs/gates.py` — `verify_target_app` ✅ counts as
  static+typecheck+navigate+snapshot+screenshot for **its own** platform;
  `build_target` ✅ counts as static+typecheck only.
* `src/graphs/progress_helpers.py` — `⛔`/`🧭` receipts map to `OUTCOME_SKIP`,
  so a missing emulator never triggers a repair loop.
* `src/graphs/parallel_tools.py` — all target tools serialize (one device and
  one workspace per plan).
* `scripts/targets_doctor.py` — the human/CI entry point:
  `python -m scripts.targets_doctor` (full report),
  `… --workspace app --target android --plan`, `… --require android` (exit 1).

### 2.3 The device pane (implemented — `src/preview/device.py`)

The web preview answers "does the page render?" by framing a dev server with the
inspect overlay injected. A phone has no URL to frame, so the proxy now serves the
same window a **live device mirror** — one more kind of preview target, no second
channel, no new dependency:

```
POST /crusor-preview/device                 register a pane (secret) -> {token, paneUrl}
GET  /crusor-preview/device/<token>/        pane document: toolbar + mirror
GET  /crusor-preview/device/<token>/stream  multipart/x-mixed-replace frames (0.5–10 fps)
GET  /crusor-preview/device/<token>/frame   one frame (PNG/JPEG)
GET  /crusor-preview/device/<token>/status  serial, model, size, fps, viewers, last error
POST /crusor-preview/device/<token>/input   normalized tap/swipe/text/key/rotate
POST /crusor-preview/device/<token>/release tear the pane down
```

The agent's `device_preview` tool does the whole thing in one call: ensure the
proxy (`src/preview/autostart`), register the pane, then `preview.open` the pane
URL so the Crusor Preview window appears next to the web preview.

Three properties make it honest rather than a demo:

* **Real input.** Taps, swipes and typing inside the pane are `adb shell input …`
  on the device; coordinates are normalized in the browser and mapped to real
  device pixels server-side, so a pane scaled to a corner still hits the right
  spot.
* **A stream that explains itself.** The first frame decides the status code:
  a pane that can stream answers `200` and keeps replacing the image, one that
  cannot answers a readable `503`/`409` that the pane turns into "adb is not
  installed", "no device attached", "device offline". No black rectangle.
* **The overlay stays off the mirror.** The preview window frames a pane by
  registering its URL, so the document arrives back through `/p/<token>/` — the
  proxy detects that self-request and skips the inspect overlay (which inspects a
  DOM, and a device screen is not one). A normal web target still gets it.

**Frames, not screen casting.** `adb exec-out screencap -p` yields a few frames per
second; they are transcoded to JPEG when Pillow is present (a tenth of the bytes).
For a smooth 30–60 fps pane, the upgrade path is scrcpy's video socket
(`scrcpy --no-audio --serial <s>`) or the emulator's WebRTC endpoint
(`android.emulation.control.v2.Rtc` + `google/android-emulator-container-scripts`),
decoded in the pane by a WASM player. That is a deliberate phase-3 decision, not a
missing piece.

### 2.4 The other surfaces the same design unlocks

* **iOS simulator** → `xcrun simctl io booted screenshot` for frames;
  `simctl io booted recordVideo` if you want motion (macOS-only, as ever).
* **Desktop** → the window already exposes CDP (`--remote-debugging-port`), so the
  pane can be the app's own webview instead of a screenshot stream.
* **Physical devices / other platforms** → the MCP/CLI device layer in §4.1,
  streamed through the same routes.

---

## 3. Setup

### 3.1 Agent-side (nothing to install to try it)

```bash
python -m scripts.targets_doctor                      # host + per-target readiness
python -m scripts.targets_doctor --plan -w app -t android
python -m scripts.targets_doctor --require android     # CI gate, exit 1 if not ready
```

### 3.2 Host toolchains

The doctor prints the exact per-OS line; this is the same table in one place.

| Target | Linux | macOS | Windows |
|---|---|---|---|
| Android | OpenJDK 21 + Android CLI SDK packages; `/dev/kvm` for a fast AVD | OpenJDK 21 + Android CLI SDK packages | OpenJDK 21 + Android CLI SDK packages — **no Android Studio required** |
| iOS simulator/build | — (needs macOS) | Full Xcode + `xcode-select --install`, CocoaPods when the project has a Podfile | — (use macOS CI/cloud for build + Simulator) |
| iOS physical device | Prebuilt IPA + `pymobiledevice3` (build still needs macOS) | Xcode is the supported build/test path | Prebuilt IPA + `pymobiledevice3` (build still needs macOS) |
| Flutter | Flutter SDK + Android or Xcode toolchain per selected target | same | same |
| React Native | Node + JDK 21 + Android SDK; Watchman optional | + Xcode + CocoaPods for iOS | + Android CLI SDK for Android; no Studio needed |
| Tauri | `cargo` (rustup) + `libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev` | rustup + Xcode CLT | rustup + Microsoft C++ Build Tools + WebView2 (bundled on Win 11) |
| Electron | Node + `libgtk-3-0 libnss3 libasound2t64` (headless: `xvfb`) | Node | Node |
| Emulator without a desktop | `/dev/kvm` + headless flag (`CRUSORAI_EMULATOR_HEADLESS=1`) | — | Hyper-V/WHPX or another supported Windows hypervisor |

### 3.3 Windows + Android emulator, without Android Studio

Android Studio is **not required**. Google's Android CLI is the agent-facing SDK
manager and app deployer; the normal Android SDK command-line tools still provide
`adb`, `emulator.exe`, and `avdmanager.bat`. On Windows, Android CLI's own AVD
subcommand is [currently disabled](https://developer.android.com/tools/agents/android-cli#known-issues),
so this plan creates/starts the AVD using the SDK tools directly. The resolver
looks in `ANDROID_HOME` / `ANDROID_SDK_ROOT` and `%LOCALAPPDATA%\Android\Sdk`;
no PATH edits are required for those SDK binaries.

The setup follows Google's [Android CLI install guide](https://developer.android.com/tools/agents/android-cli/download),
[`android sdk install`](https://developer.android.com/tools/agents/android-cli/commands/sdk_install),
[`android run`](https://developer.android.com/tools/agents/android-cli/commands/run), and
[`android layout`](https://developer.android.com/tools/agents/android-cli/commands/layout)
reference. `android run --apks=… --device=…` consumes the APK Gradle produced; it
is not a replacement for compiling the workspace with Gradle.

> **Validation status:** command flags were checked against Google's current docs and
> the setup planner is unit-tested, but this route has **not** yet run on a native
> Windows machine or emulator. Treat it as unverified until `--require android`,
> `adb devices -l`, and a real `verify_target_app` receipt succeed.

Ask the doctor for the host-specific block:

```powershell
python -m scripts.targets_doctor --setup android
```

The Windows route is:

```powershell
# First shell: install Java 21 and Google's agent-facing Android CLI.
winget install --id Microsoft.OpenJDK.21 --exact
winget install --id Google.AndroidCLI --exact
# Close/reopen PowerShell after winget, then continue in the new shell.

$sdk = "$env:LOCALAPPDATA\Android\Sdk"
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
[Environment]::SetEnvironmentVariable("ANDROID_HOME", $sdk, "User")
[Environment]::SetEnvironmentVariable("ANDROID_SDK_ROOT", $sdk, "User")

android "--sdk=$sdk" init
android "--sdk=$sdk" sdk install platform-tools emulator cmdline-tools/latest platforms/android-35 build-tools/35.0.0 system-images/android-35/google_apis/x86_64
& "$sdk\cmdline-tools\latest\bin\sdkmanager.bat" --licenses
echo no | & "$sdk\cmdline-tools\latest\bin\avdmanager.bat" create avd -n crusor -k "system-images;android-35;google_apis;x86_64" -d pixel_7

# The Android CLI emulator subcommand is currently disabled on Windows.
# The agent boots this same AVD with emulator.exe; check acceleration here:
& "$sdk\emulator\emulator.exe" -accel-check
python -m scripts.targets_doctor --require android
```

If acceleration is unavailable, enable **one** Windows hypervisor path (WHPX is
compatible with Hyper-V/WSL2/Docker Desktop), reboot, and re-check:

```powershell
# Run as Administrator; reboot after this finishes.
dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart
```

Android CLI's `android run` adapter is optional: Gradle still compiles the app;
when Android CLI is installed, the provider uses it to deploy and launch the
already-built APK, then independently checks that the package owns the foreground
window. Set `CRUSORAI_ANDROID_RUNNER=adb` to pin the existing direct-ADB path.

Then check the plan and request the first real proof:

```powershell
python -m scripts.targets_doctor -w . -t android --plan     # plan only; nothing executed
# In the IDE: "build and verify this Android app"
```

The agent boots the AVD itself when none is attached (`CRUSORAI_AVD` picks a
specific one, `CRUSORAI_EMULATOR_HEADLESS=1` for CI, `CRUSORAI_EMULATOR_EPHEMERAL=1`
to discard it afterwards). The real device receipt is the required checkpoint
before UI-flow automation is enabled.

### 3.4 New-project creation

There are no scaffold tools (deleted 2026-10-18 — founder: "the terminal
does the job", field-proven by a full `create-next-app` run under the
approval dock). The agent creates projects through the terminal with
explicit flags (`npx create-next-app@latest <name> --yes ...`,
`flutter create`, `create-expo-app`, `create-tauri-app`); the normal
permission rules ask before the command runs, and `detect_targets` /
`verify_target_app` work on the result unchanged.

---

## 4. The repositories worth building on

Star counts were read on **2026-10-12** — use them as a popularity signal, not a
ranking. Licence is the thing to check before shipping a dependency.

### 4.1 Agent-native device control (the layer that makes "prove it" real)

| Repo | ★ | Why it matters here |
|---|---|---|
| [callstack/agent-device](https://github.com/callstack/agent-device) | 4,980 | **Best fit.** CLI + `agent-device mcp` stdio server + typed Node API (`createAgentDeviceClient()`). Accessibility-tree snapshots (`@e2 [button] "Add"`) instead of screenshot guessing; per-worktree device claims so parallel agents don't fight over one emulator; exports strict Maestro YAML; iOS/Android/HarmonyOS + tvOS/Android TV + web/macOS/Linux. Needs Node ≥ 22.12 (web: 24+); diagnose with `agent-device doctor`. |
| [software-mansion/argent](https://github.com/software-mansion/argent) | 3,016 | `npx @swmansion/argent@latest init` — drives iOS simulators, Android emulators/devices, Apple/Android/Fire TV **and Electron/Chromium** from one tool; record-and-replay, OCR/font-aware visual regression, profiling through Hermes/React DevTools/Instruments/Perfetto. **Licence caution:** Apache-2.0 source but proprietary binaries (`simulator-server`, `ax-service`, `.dylib`) and telemetry (opt-out available) — read before bundling. |
| [mobile-next/mobile-mcp](https://github.com/mobile-next/mobile-mcp) | 9,029 | The mature MCP for real iOS/Android devices; good fallback if you want a plain MCP server with no Node 22 constraint. |
| [trycua/cua](https://github.com/trycua/cua) | 29,432 | Cross-OS computer-use drivers/fleets + benchmarks; relevant only if you want the agent to *operate* arbitrary desktop UIs, not just its own apps. |
| [appium/appium-mcp](https://github.com/appium/appium-mcp) | 498 | Bridges the existing Appium ecosystem into MCP — useful if you already have Appium grids. |
| [lycorp-jp/sim-use](https://github.com/lycorp-jp/sim-use) | 1,411 | iOS-simulator-focused agent control; a lighter alternative for the Apple-only path. |

Recommendation: **agent-device as the default device layer**, `mobile-mcp` as the
explicit fallback, Appium only if the team already owns Appium infrastructure.

### 4.2 Emulators and CI device infrastructure

| Repo | ★ | Notes |
|---|---|---|
| [ReactiveCircus/android-emulator-runner](https://github.com/ReactiveCircus/android-emulator-runner) | 1,301 | The de-facto GitHub Action (`@v2`): `api-level`, `target: google_apis`, `arch: x86_64`, `disable-animations`, AVD snapshot caching. Used by both Android pipelines below. Needs KVM on the runner (ubuntu-latest has it). |
| [google/android-emulator-container-scripts](https://github.com/google/android-emulator-container-scripts) | 2,098 | Headless emulator in Docker/K8s, ADB on `:5555`, **WebRTC streaming** (`android.emulation.control.v2.Rtc` gRPC + Python gateway + React client) — the cleanest path to an in-IDE live device pane. Requires `/dev/kvm`. |
| [budtmo/docker-android](https://github.com/budtmo/docker-android) | 15,964 | Batteries-included emulator image with noVNC and an MCP server; fastest local "give me an emulator" story. |
| [remote-android/redroid-doc](https://github.com/remote-android/redroid-doc) | 6,947 | Docs-only, last pushed 2026-05-17 — the quietest of these; fine for GPU-less, binary-translated Android, not a first choice for a product pipeline. |

### 4.3 iOS without a Mac (honest options)

[xtool-org/xtool](https://github.com/xtool-org/xtool) (7,188★) with
[doronz88/pymobiledevice3](https://github.com/doronz88/pymobiledevice3)
(2,862★) can compile/sign/install Swift/SwiftUI apps and IPAs **from Linux to a
physical iPhone** — it needs an Apple ID plus one `Xcode.xip` for the iOS SDK.
The **iOS Simulator still requires macOS**; there is no honest substitute. For
CI, budget macOS runners (`macos-14`) or a cloud Mac (see §5.2).

### 4.4 Test frameworks (choose per target, don't stack all of them)

| Repo | ★ | Use it for |
|---|---|---|
| [mobile-dev-inc/maestro](https://github.com/mobile-dev-inc/maestro) | 16,022 | YAML flows that read like the app; `maestro test --format junit --output report.xml` drops into any CI; `mobile-dev-inc/action-maestro-cloud@v1` for hosted devices. The natural regression layer *above* our receipts. |
| [appium](https://github.com/appium/appium) + [appium-flutter-driver](https://github.com/appium/appium-flutter-driver) | 22,062 / 539 | Deep native/Flutter automation when Maestro's YAML is not enough (custom drivers, W3C grid). |
| [Airtest](https://github.com/AirtestProject/Airtest) | 9,598 | Image-recognition-driven cross-platform automation; robust to unusual UIs, less deterministic in CI. |
| [playwright](https://github.com/microsoft/playwright) | 97,516 | `_electron` launch + CDP assertions for Electron, and the existing web receipt path. |
| [webdriverio](https://github.com/webdriverio/webdriverio) | 9,844 | W3C WebDriver client alternative for Electron/Tauri (via `tauri-driver`). |
| [flutter](https://github.com/flutter/flutter) / [expo](https://github.com/expo/expo) | 179,857 / 52,659 | The frameworks themselves (`flutter test --reporter expanded`, `expo start`) — first-class in the providers. |

### 4.5 Desktop toolkits and release actions

| Repo | ★ | Notes |
|---|---|---|
| [tauri-apps/tauri](https://github.com/tauri-apps/tauri) | 111,790 | Rust shell + system webview → 3–10 MB installers; `tauri build` is the same command on all three OSes. |
| [tauri-apps/tauri-action](https://github.com/tauri-apps/tauri-action) | 1,617 | Official release action: macOS `aarch64`/`x86_64` matrix, updater signing key, CodeMagic-style notarization env vars. ~18–25 min end-to-end. |
| [electron/electron](https://github.com/electron/electron) + [electron/forge](https://github.com/electron/forge) | 123,286 / 7,154 | Heaviest binaries, but the CDP surface makes verification trivial and the ecosystem is unmatched. |
| [wailsapp/wails](https://github.com/wailsapp/wails) | 36,524 | Go + webview, smallest toolchain of the three if your team is Go-shaped. |
| [blackboardsh/electrobun](https://github.com/blackboardsh/electrobun) | 12,908 | Newer, aggressively small Electron alternative — interesting, still young for production pipelines. |

---

## 5. Pipelines

Copy-ready workflow templates live in [`docs/pipelines/`](pipelines/) (they are
inert until copied into `.github/workflows/`). Each one ends with the same
non-negotiable step: run `src.targets.registry` and **fail the job unless the
receipt is `✅`**, then upload `.crusorai/target-evidence/**` as an artifact.

```yaml
- name: Build + install + launch + PROVE (one receipt)
  script: |
    python - <<'PY'
    import sys
    from src.targets import registry
    from src.targets.runner import TargetRequest
    receipt = registry.run(".", "android", TargetRequest(mode="verify"))
    print(receipt.to_text())
    sys.exit(0 if receipt.passed else 1)
    PY
```

### 5.1 Android — `docs/pipelines/android.yml`

`ubuntu-latest` (KVM) → JDK 21 → AVD snapshot cache → `android-emulator-runner@v2`
(`api-level: [34]`, `target: google_apis`, `-no-window -gpu swiftshader_indirect`) →
receipt → optional instrumented `mode="test"` job → evidence artifact.
Time: ~12–20 min cold, ~6–9 min with the AVD cache. Maestro JUnit variant is in
`docs/pipelines/react-native.yml`.

### 5.2 iOS — `docs/pipelines/ios.yml`

`macos-14` → `latest-stable` Xcode → derived-data/CocoaPods cache → `simctl`
boot + `xcodebuild` → receipt → optional `xcresult` upload. TestFlight upload
belongs in a tag job using App Store Connect **API keys** (`--apiKey`/`--apiIssuer`),
never certificates committed to the repo. Time: ~15–30 min. Cheaper cloud-Mac
alternatives if self-hosted: MacStadium, Scaleway Apple silicon, Codemagic,
Bitrise, Xcode Cloud.

### 5.3 Flutter — `docs/pipelines/flutter.yml`

`subosito/flutter-action@v2` (channel + cache) × one job per real platform:
android (emulator), ios (`macos-14`), desktop matrix
(`ubuntu-latest` + ninja/GTK/xvfb, `windows-latest`, `macos-14`), plus
`flutter test`. One codebase, five verified targets, one receipt per job.

### 5.4 React Native / Expo — `docs/pipelines/react-native.yml`

Android (emulator runner) and iOS (`macos-14` + CocoaPods) jobs; the RN provider
starts **Metro first** and waits for `/status` before installing — a debug build
without a packager is a guaranteed red screen, and the pipeline now fails for
that reason instead of the developer discovering it. Third job runs Maestro flows
when `maestro/**` exists: `maestro test --format junit --output report.xml`.

### 5.5 Desktop — `docs/pipelines/desktop-tauri.yml`, `docs/pipelines/desktop-electron.yml`

* **Tauri:** Linux needs `libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev
  xvfb`; verify on all three OSes, then a tag-triggered `tauri-action@v0` release
  matrix (`macos-14` aarch64/x86_64, `ubuntu-22.04`, `windows-latest`) with
  `TAURI_SIGNING_PRIVATE_KEY(_PASSWORD)` + Apple signing/notarization env vars.
* **Electron:** verify via CDP (`process_alive` + `window_open` + `cdp_ready`;
  Playwright `_electron` smoke alongside), then `electron-builder --publish always`
  per OS with the usual `CSC_LINK` / `WIN_CSC_LINK` secrets.

### 5.6 What CI must never do

* Treat `npm run build` / `gradlew assembleDebug` / `cargo build` as proof.
* Install an emulator per job without caching the AVD (cold boots dominate cost).
* Leave the emulator booted after the job (`CRUSORAI_EMULATOR_EPHEMERAL=1`).
* Upload a failure without the screenshot + UI dump + log slice beside it.

---

## 6. Rollout plan

| Phase | Content | Acceptance |
|---|---|---|
| 1 | **Done (code-level; native host proof pending).** Target layer, 9 runtime tools, capability/toolsets/gates wiring, scaffolders, doctor CLI; 45 pipeline + 19 environment + 12 scaffold + 21 toolset tests | Those focused suites pass; `--require` refuses a bare host; Windows Android setup still needs a real emulator receipt |
| 2 | **Done (first cut).** Device mirror in the preview proxy + `device_preview` tool: live screen, real taps, honest errors | `src/tests/test_preview_device.py` (24 tests) green; verified live against the real CLI proxy — register → pane → multipart stream → normalized tap landing as `adb shell input tap 540 1200` |
| 3 | 30–60 fps pane: scrcpy video socket or emulator WebRTC (WASM decoder in the pane); iOS `simctl` frames; device list + restart controls in the IDE panel | Smooth mirror, < 1 s input latency |
| 4 | Pipelines for the platform the team actually ships (start with Android; add desktop next) | A PR that breaks the app fails CI with a screenshot, not a stack trace |
| 5 | Device layer bake-off: `agent-device` vs `mobile-mcp` on your real app; adopt one, keep the other behind a flag | Same task solved twice; pick on flake rate and token cost |
| 6 | iOS: macOS runners for simulator proofs; `xtool`+`pymobiledevice3` only for physical-device smoke from Linux | `⛔` on Linux for simulator jobs, honest `ios-device` path available |
| 7 | Maestro/Playwright regression suites layered above receipts; evidence retention policy | JUnit reports attached to PRs; 14-day artifact retention |

---

### 6.1 What still needs desktop-side work (and what does not)

The pane works today with **no TypeScript changes**: the agent registers the device
and hands `preview.open` an http URL, which is exactly the path the preview window
already supports. The desktop agent is only needed for the polish, in this order:

1. **A device chip in the preview window** — show `serial · model · 1080×2400 · fps`
   in the window's own toolbar when the framed target is a `/crusor-preview/device/`
   URL, instead of the generic URL field. (`crusorAIPreviewService.ts`,
   `media/crusor-preview/*`.)
2. **Reach the pane without an agent turn** — a "Phone" entry in the Preview tab's
   target list that calls `POST /crusor-preview/device` with the endpoint secret and
   frames the returned `paneUrl` directly (skipping the self-proxy hop).
3. **Pane-aware status** — map `{ok:false}` from `/status` to the window's red
   "Preview target down" affordance, so "device offline" looks the same as "dev
   server down" and the fix hint comes from the pane payload.
4. **A `kind: 'device'` target** — the honest long-term shape: the pane becomes a
   first-class target kind (`register_device`) instead of a URL the window frames
   through `/p/<token>/`. Small, and it removes the remaining special case in
   `_serve_upstream`.

Everything in 1–4 needs `npm run compile` inside `desktop/vscode`, so it is
desktop-agent work by definition; the Python side is already done and tested.

## 7. Honest limits

* **iOS Simulator ⇒ macOS.** No container, no Linux trick. Physical-device
  smoke from Linux is real (xtool + pymobiledevice3) but not a substitute.
* **Android emulator ⇒ `/dev/kvm`.** Without nested virtualization, expect
  `-no-accel` to be unusably slow; use a physical device or cloud farm.
* **Webview proof is not uniform.** CDP assertions are available on Windows
  (WebView2) and Electron (Chromium); WKWebView (macOS Tauri) and WebKitGTK
  (Linux Tauri) have no equivalent — those receipts prove process liveness and
  say so in their notes instead of pretending to inspect the DOM.
* **Signing is a process, not a flag.** Codesigning/notarization/store uploads
  need real credentials and should live in tag-triggered jobs with secrets.
* **Licence check before bundling.** `argent` ships proprietary binaries;
  emulator images and Maestro/Appium have their own terms. The target layer
  itself has no new runtime dependency beyond what this repo already uses.
