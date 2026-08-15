"""Structural pins for the canonical-fork utility-process → Python sidecar chain."""
from __future__ import annotations

import json
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
        "existsSync(join(options.engineRoot, 'src', 'bridge'))",
        "['-m', 'src.bridge']", "STOP_GRACE_MS",
    ):
        assert receipt in worker
    contract = _text("common", "pulseAIWorkerService.ts")
    assert "environment" not in contract, "renderer must not inject arbitrary child environment"


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


def test_selective_manifest_has_exactly_four_upstream_edits():
    manifest = json.loads((DESKTOP / "SELECTIVE_MANIFEST.json").read_text())
    assert set(manifest["files"]) == {
        "build/buildfile.ts",
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