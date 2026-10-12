# Platform verification (web, desktop, Android, iOS, Flutter, React Native)

The agent verifies more than websites. The runtime detects the project type
from its files and runs that platform's own build, unit-test, and end-to-end UI
test commands through the normal terminal tool (approvals and hardline guards
still apply).

| Platform | Detected from | Build | Unit tests | End-to-end UI |
|---|---|---|---|---|
| web | package.json with a web framework, or index.html | npm build script | npm test | Playwright |
| electron | package.json depends on electron | npm build script | npm test | Playwright (_electron) |
| tauri | src-tauri/tauri.conf.json | cargo check | cargo test | Playwright (web frontend) |
| flutter | pubspec.yaml with flutter SDK | flutter analyze | flutter test | flutter integration_test |
| react_native | react-native or expo dependency | tsc --noEmit | npm test | Maestro (.maestro/) or npm e2e script |
| android | Gradle com.android.application | gradle assembleDebug | testDebugUnitTest | connectedDebugAndroidTest or Maestro |
| ios | *.xcodeproj (macOS only) | xcodebuild build | xcodebuild test | XCUITest target |
| desktop_python | PySide/PyQt/customtkinter in requirements | compileall | pytest | pytest tests/e2e |

## Tools

- `detect_platforms` — list detected projects and their commands.
- `build_project(platform=)` — ✅/❌ PLATFORM BUILD receipt.
- `test_project(platform=)` — ✅/❌ PLATFORM TESTS receipt.
- `run_ui_e2e(platform=)` — ✅/❌ UI E2E receipt. Fails with a pointer to
  `scaffold_ui_e2e` when no suite exists.
- `scaffold_ui_e2e(platform=)` — writes a starter suite (Playwright config and
  smoke test, Maestro flow, or Flutter integration test). Never overwrites files.

## Completion gate

- Web and desktop frontends: a passing `run_ui_e2e` counts as browser proof.
- Native apps (Android, iOS, Flutter, React Native, Python desktop): a UI task
  needs a passing `run_ui_e2e`; a browser cannot drive these apps.
- A failed or skipped receipt never counts as passing.

## Requirements on the machine

Missing tools are reported by name (e.g. `'flutter' is not on PATH`).
Android end-to-end tests need an emulator or connected device. iOS builds need
macOS with Xcode.

## Tests

`src/tests/test_platform_verification.py` covers detection, recipes, scaffolding,
receipts, missing-prerequisite handling, and the gate rules.
