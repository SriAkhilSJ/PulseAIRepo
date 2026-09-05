"""Structural pins for the canonical-fork utility-process → Python sidecar chain."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
FORK = DESKTOP / "vscode"
PULSE = FORK / "src" / "vs" / "workbench" / "contrib" / "pulseai"


def _text(*parts: str) -> str:
    return PULSE.joinpath(*parts).read_text(encoding="utf-8")


def test_only_node_worker_imports_child_process():
    offenders = []
    for path in PULSE.rglob("*.ts"):
        text = path.read_text(encoding="utf-8")
        if "node:child_process" in text and "/node/" not in path.as_posix():
            offenders.append(path)
    assert offenders == []
    worker = _text("node", "pulseAIWorkerProcessService.ts")
    assert "shell: false" in worker
    assert "windowsHide: true" in worker


def test_worker_validates_frames_paths_and_bridge_presence():
    worker = _text("node", "pulseAIWorkerProcessService.ts")
    for receipt in (
        "MAX_FRAME_BYTES", "Buffer.byteLength", "frame.includes('\\n')",
        "JSON.parse(frame)", "isAbsolute(options.engineRoot)",
        # 2026-09-05: the bridge presence check became an OWNERSHIP resolver —
        # the requested root is used only when it truly owns
        # src/bridge/__main__.py; otherwise the worker walks UP to the repo
        # that does (a workspace change must not kill the engine).
        "resolveEngineDirectory(options.engineRoot",
        "function ownsBridge(root: string)",
        "existsSync(join(root, 'src', 'bridge', '__main__.py'))",
        "MAX_ENGINE_ROOT_UPWALK",
        # install-tree self-discovery (workspace outside the repo must work)
        "resolved from the install tree",
        # field 2026-09-05: the utility process loads this worker as ESM
        # (bootstrap-fork.ts `await import(VSCODE_ESM_ENTRYPOINT)`; tsconfig
        # module nodenext) — __dirname does NOT exist there, so self-location
        # falls back to FileAccess against _VSCODE_FILE_ROOT (set by
        # bootstrap-esm.ts). A `typeof __dirname`-only guard silently
        # disabled the walk: "up-walk and install tree both exhausted".
        "currentModuleDir",
        "FileAccess.asBrowserUri(MODULE_ID)",
        "Schemas.vscodeFileResource",
        "['-m', 'src.bridge']", "STOP_GRACE_MS",
    ):
        assert receipt in worker
    contract = _text("common", "pulseAIWorkerService.ts")
    assert "environment" not in contract, "renderer must not inject arbitrary child environment"


def test_compile_task_is_self_contained_in_tracked_gulpfile():
    # fecbf105 disaster class: the compile lived in build/gulpfile.ts, but
    # .gitignore's `desktop/vscode/build/*` silently excluded it from every
    # commit ("git add -A" skipped it without a warning) — the remote chain
    # NEVER had a working compile, and the sandbox snapshot kept dropping the
    # untracked file. The compile implementation must live in the TRACKED
    # gulpfile.mjs and must not import anything from the ignored build/ dir.
    gulpfile = (FORK / "gulpfile.mjs").read_text(encoding="utf-8")
    assert "build/gulpfile.ts" not in gulpfile
    assert "export async function compile" in gulpfile
    assert "tsconfig.json" in gulpfile and "tsc" in gulpfile
    assert "pulseai-spa" in gulpfile, "compile must copy the SPA media tree"
    tracked = subprocess.run(
        ["git", "ls-files", "--", "desktop/vscode/gulpfile.mjs"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    assert tracked == "desktop/vscode/gulpfile.mjs", tracked


def test_spa_iframe_uses_browser_uri_not_file_uri():
    # field 2026-09-05: the native workbench document is served from
    # vscode-file://vscode-app/<appRoot>/out/ (workbench.ts baseUrl), and a raw
    # file:// iframe from that origin is refused by Chromium ("Not allowed to
    # load local resource"). The SPA frame must ride FileAccess.asBrowserUri —
    # the document's OWN origin, admitted by frame-src 'self'.
    pane = _text("browser", "pulseAIViewPane.ts")
    assert "FileAccess.asBrowserUri(LOCAL_SPA_RESOURCE" in pane
    assert "asFileUri(LOCAL_SPA_RESOURCE" not in pane


def test_workbench_uses_existing_utility_process_framework():
    engine = _text("electron-browser", "pulseAIEngineService.ts")
    for receipt in (
        "IUtilityProcessWorkerWorkbenchService", "createWorker",
        "PULSE_AI_WORKER_MODULE_ID", "ProxyChannel.toService",
        "PULSE_AI_PROTOCOL_VERSION", "HANDSHAKE_TIMEOUT_MS",
        "worker.onDidTerminate", "processService.onDidWriteStderr",
        "await this.releaseWorker()", "PulseAIEngineState.Crashed",
    ):
        assert receipt in engine
    main = _text("node", "pulseAIWorkerMain.ts")
    assert "UtilityProcessServer" in main
    assert "PULSE_AI_WORKER_CHANNEL" in main


def test_desktop_registration_is_isolated_from_common_and_web():
    common_main = (FORK / "src" / "vs" / "workbench" / "workbench.common.main.ts").read_text()
    desktop_main = (FORK / "src" / "vs" / "workbench" / "workbench.desktop.main.ts").read_text()
    assert common_main.count("pulseAI.contribution.js") == 1
    assert "pulseAI.desktop.contribution.js" not in common_main
    assert desktop_main.count("pulseAI.desktop.contribution.js") == 1
    registration = _text("electron-browser", "pulseAI.desktop.contribution.ts")
    assert "registerSingleton(IPulseAIEngineService" in registration
    assert "pulseai.engineRoot" in registration
    assert "pulseai.pythonPath" in registration


def test_selective_manifest_has_exactly_five_upstream_edits():
    manifest = json.loads((DESKTOP / "SELECTIVE_MANIFEST.json").read_text())
    assert set(manifest["files"]) == {
        "build/buildfile.ts",
        "build/next/index.ts",
        "product.json",
        "src/vs/workbench/workbench.common.main.ts",
        "src/vs/workbench/workbench.desktop.main.ts",
    }
    assert all(item["modified"] for item in manifest["files"].values())


def test_optimized_desktop_bundle_has_the_pulse_worker_entrypoint():
    buildfile = (FORK / "build" / "buildfile.ts").read_text(encoding="utf-8")
    entry = "createModuleDescription('vs/workbench/contrib/pulseai/node/pulseAIWorkerMain')"
    desktop = buildfile.split("export const workbenchDesktop = [", 1)[1].split("];", 1)[0]
    server = buildfile.split("export const codeServer = [", 1)[1].split("];", 1)[0]
    assert desktop.count(entry) == 1
    assert entry not in server


def test_current_esbuild_bundle_has_the_pulse_worker_entrypoint():
    index = (FORK / "build" / "next" / "index.ts").read_text(encoding="utf-8")
    entry = "vs/workbench/contrib/pulseai/node/pulseAIWorkerMain"
    assert index.count(entry) == 1
    desktop = index.split("const desktopEntryPoints = [", 1)[1].split("];", 1)[0]
    assert desktop.count(entry) == 1
    for array_name in ("serverEntryPoints", "webEntryPoints", "webOnlyEntryPoints", "codeEntryPoints"):
        block = index.split(f"const {array_name} = [", 1)[1].split("];", 1)[0]
        assert entry not in block, f"{array_name} must not carry the Pulse worker"