# Agent Work — First Native PulseAI IDE Boot

This checklist is for validating PulseAI inside a **complete pinned Code OSS checkout**. Do this on a machine with enough disk space; do not expand the selective `PulseAIRepo/desktop/` directory into a complete fork.

## Goal

Prove this complete native path:

```text
Pulse Agent / Pulse Manager
  → shared native renderer
  → IPulseAIEngineService
  → Code OSS utility process
  → PulseAIWorkerProcessService
  → python -m src.bridge
  → real PulseAI Engine
```

## Fixed inputs

- PulseAI repository: `PulseAIRepo`
- Code OSS upstream: `https://github.com/microsoft/vscode`
- Required Code OSS commit: `6c27443ce6fdf6ac798c64025d45175e2e23c4b4`
- Required Node version: `24.18.0`
- Pulse contribution: `src/vs/workbench/contrib/pulseai/`
- Do not place Pulse under `/extensions/`.
- Do not modify additional upstream source files while diagnosing failures.

## 1. Prepare the machine

Recommended free space: **15 GB or more**.

Required tools:

- Git
- Node.js `24.18.0`
- npm from that Node installation
- Python compatible with PulseAI
- PulseAI Engine dependencies
- Native build tools required by Code OSS for your operating system

Confirm versions:

```bash
node --version
npm --version
python --version
git --version
```

Expected Node result:

```text
v24.18.0
```

## 2. Create a separate full Code OSS checkout

Choose paths outside the selective `desktop/` directory:

```bash
export PULSE_REPO=/absolute/path/to/PulseAIRepo
export VSCODE_ROOT=/absolute/path/to/pulseai-ide-full
```

Clone and pin Code OSS:

```bash
git clone https://github.com/microsoft/vscode.git "$VSCODE_ROOT"
cd "$VSCODE_ROOT"
git checkout 6c27443ce6fdf6ac798c64025d45175e2e23c4b4
git status --short
git rev-parse HEAD
```

`git status --short` must be empty before applying the Pulse overlay.

## 3. Verify the untouched upstream files

Run this before copying anything:

```bash
export PULSE_REPO VSCODE_ROOT
python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

pulse = Path(os.environ["PULSE_REPO"])
target = Path(os.environ["VSCODE_ROOT"])
manifest = json.loads((pulse / "desktop/SELECTIVE_MANIFEST.json").read_text())

for relative, receipt in manifest["files"].items():
    path = target / relative
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = receipt["upstream_sha256"]
    if actual != expected:
        raise SystemExit(f"UPSTREAM HASH MISMATCH: {relative}\nexpected {expected}\nactual   {actual}")
    print("upstream OK", relative)
PY
```

Do not apply the overlay if any hash differs. Re-check the pinned commit instead.

## 4. Apply the selective PulseAI overlay

```bash
cd "$VSCODE_ROOT"

cp "$PULSE_REPO/desktop/product.json" product.json
cp "$PULSE_REPO/desktop/build/buildfile.ts" build/buildfile.ts
cp "$PULSE_REPO/desktop/src/vs/workbench/workbench.common.main.ts" src/vs/workbench/workbench.common.main.ts
cp "$PULSE_REPO/desktop/src/vs/workbench/workbench.desktop.main.ts" src/vs/workbench/workbench.desktop.main.ts

rm -rf src/vs/workbench/contrib/pulseai
mkdir -p src/vs/workbench/contrib
cp -R "$PULSE_REPO/desktop/src/vs/workbench/contrib/pulseai" src/vs/workbench/contrib/pulseai

mkdir -p resources/darwin resources/linux resources/server resources/win32 resources/pulseai
cp "$PULSE_REPO/desktop/resources/darwin/code.icns" resources/darwin/code.icns
cp "$PULSE_REPO/desktop/resources/linux/code.png" resources/linux/code.png
cp "$PULSE_REPO/desktop/resources/server/code-192.png" resources/server/code-192.png
cp "$PULSE_REPO/desktop/resources/server/code-512.png" resources/server/code-512.png
cp "$PULSE_REPO/desktop/resources/server/favicon.ico" resources/server/favicon.ico
cp "$PULSE_REPO/desktop/resources/win32/code.ico" resources/win32/code.ico
cp "$PULSE_REPO/desktop/resources/win32/code_150x150.png" resources/win32/code_150x150.png
cp "$PULSE_REPO/desktop/resources/win32/code_70x70.png" resources/win32/code_70x70.png
cp "$PULSE_REPO/desktop/resources/pulseai/pulseai-mark.svg" resources/pulseai/pulseai-mark.svg
```

## 5. Verify the applied overlay

```bash
export PULSE_REPO VSCODE_ROOT
python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

pulse = Path(os.environ["PULSE_REPO"])
target = Path(os.environ["VSCODE_ROOT"])
manifest = json.loads((pulse / "desktop/SELECTIVE_MANIFEST.json").read_text())

for section in ("files", "brand_assets"):
    for relative, receipt in manifest[section].items():
        actual = hashlib.sha256((target / relative).read_bytes()).hexdigest()
        expected = receipt["overlay_sha256"]
        if actual != expected:
            raise SystemExit(f"OVERLAY HASH MISMATCH: {relative}\nexpected {expected}\nactual   {actual}")
        print("overlay OK", relative)
PY
```

## 6. Install Code OSS dependencies

```bash
cd "$VSCODE_ROOT"
npm install
```

Do not copy `node_modules` back into `PulseAIRepo/desktop/`.

## 7. Run the semantic checks

Start with the focused client type-check:

```bash
npm run typecheck-client
```

Then run the layer checks:

```bash
npm run valid-layers-check
```

Compile the desktop client:

```bash
npm run compile
```

Record the complete error output if any command fails. Do not hide errors with `--skipLibCheck` beyond the pinned script and do not add `any` casts merely to silence Code OSS APIs.

## 8. Verify optimized worker packaging

The Pulse utility worker is string-addressed and must be emitted as its own desktop entry point.

```bash
npm run gulp minify-vscode
```

Then check for the worker:

```bash
find out-vscode out-vscode-min -path '*pulseai*' -o -name 'pulseAIWorkerMain.js' 2>/dev/null
```

Required evidence:

- `pulseAIWorkerMain` exists in optimized desktop output.
- It is not emitted as a web or server entry point.
- `workbench.desktop.main` contains the desktop registration.
- Common/web bundles do not import `node:child_process` or Electron-only Pulse modules.

## 9. Configure the PulseAI Engine

In the launched IDE settings, set:

```json
{
  "pulseai.engineRoot": "/absolute/path/to/PulseAIRepo",
  "pulseai.pythonPath": "/absolute/path/to/python",
  "pulseai.autoStart": true
}
```

The engine root must be absolute and must contain `src/bridge/`.

Before launching Code OSS, verify the bridge directly:

```bash
cd "$PULSE_REPO"
printf '%s\n' '{"type":"hello","protocol":2}' | python -m src.bridge
```

Expected first response: a one-line JSON `hello` frame with protocol `2`.

## 10. Launch PulseAI IDE

Linux/macOS:

```bash
cd "$VSCODE_ROOT"
./scripts/code.sh
```

Windows PowerShell:

```powershell
cd $env:VSCODE_ROOT
.\scripts\code.bat
```

## 11. Visual acceptance checklist

- [ ] Window/product title says **PulseAI IDE**.
- [ ] PulseAI application icon appears in the window/taskbar/dock.
- [ ] Pulse cyan/navy chrome appears with Dark 2026 or Light 2026.
- [ ] High-contrast themes remain unchanged and usable.
- [ ] User color customizations still override Pulse defaults.
- [ ] Activity Bar contains **Pulse**.
- [ ] The compact Agent UI opens in the sidebar.
- [ ] **Pulse Manager** opens as an editor tab.
- [ ] Opening Pulse Manager does not close or replace source-code editors.
- [ ] Native File/Edit/Selection/View/Go/Run/Terminal/Help menus remain available.

## 12. Real-engine vertical slice

Run these in order:

- [ ] Open a trusted test workspace.
- [ ] Open the Pulse Agent view.
- [ ] Engine state moves `stopped → starting → ready`.
- [ ] Submit a simple prompt.
- [ ] Streaming text appears without losing composer focus.
- [ ] Tool rows update in place.
- [ ] Terminal disclosure shows command, bounded output, state, exit result, and duration.
- [ ] An edit approval shows **Review**, **Deny**, and **Allow**.
- [ ] **Review** opens a native diff using the engine's `old_text` and `new_text`.
- [ ] Approval resolves using the exact `tool_id`.
- [ ] Cancel shows `Stopping…` and ends with `Run cancelled` when `completed` is false.
- [ ] Stop or crash the Python process.
- [ ] Automatic restart uses bounded backoff.
- [ ] Session resume/replay does not duplicate event IDs or transcript rows.
- [ ] Pulse Manager and Agent show the same active session state.

## 13. Evidence to save

Save the following outside generated build directories or attach them to the implementation report:

1. `node --version`
2. `git rev-parse HEAD` from the full Code OSS checkout
3. Output of `npm run typecheck-client`
4. Output of `npm run valid-layers-check`
5. Output of `npm run compile`
6. Optimized worker path from `out-vscode-min`
7. Screenshot of Pulse Agent
8. Screenshot of Pulse Manager beside a source editor
9. Screenshot of the native approval diff
10. Utility worker and Python bridge logs for one successful turn
11. Crash/restart/replay evidence
12. Final `git diff --stat` from the full checkout

## 14. Failure rules

If something fails:

- Do not move Pulse into `/extensions/`.
- Do not spawn Python from browser/common renderer code.
- Do not remove workspace-trust or approval checks.
- Do not bypass Protocol v2 negotiation.
- Do not add broad upstream edits without approval.
- Do not copy the complete Code OSS checkout into `PulseAIRepo/desktop/`.
- Preserve the exact error, file, line, command, platform, and Node version.

## Completion gate

This job is complete only when:

1. Full Code OSS semantic checks pass.
2. The native desktop launches with PulseAI branding.
3. `pulseAIWorkerMain` exists in optimized output.
4. A real prompt streams through the utility-process/Python bridge.
5. Native approval diff, cancellation, restart, and replay all work.
6. The PulseAI engine focused suite remains green.
