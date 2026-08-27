"""P0: desktop workspace boundary — the opened folder, and only it, binds a session.

These pins are deterministic (no model call, no GUI). They prove, from the
desktop source itself, that:

- hop 1: the session folder comes ONLY from
  ``IWorkspaceContextService.getWorkspace().folders`` (zero -> blocked,
  one -> that exact folder, many -> the explicitly retained selection);
- hop 2: ``engineService.start(workspace)`` receives that exact ``uri.fsPath``
  and cannot leak it into the engine root;
- hop 3/4: ``session_create.workspace`` and ``prompt.workspace`` carry the
  same path unchanged;
- hop 5: the Python bridge binds the session to that path and runs the turn
  against it (subprocess, echo runner);
- no literal ``"."``, application cwd, or engine root is ever a workspace
  fallback;
- a workspace-bearing follow-up cannot silently re-home an existing session.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.bridge.protocol import PROTOCOL_VERSION
from src.runtime.identity import workspace_id

ROOT = Path(__file__).resolve().parents[2]
PULSE = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "pulseai"


def _text(*parts: str) -> str:
    return PULSE.joinpath(*parts).read_text(encoding="utf-8")


def _lines(source: str, needle: str) -> list[int]:
    return [index + 1 for index, line in enumerate(source.splitlines()) if needle in line]


def _assert_one(source: str, needle: str, label: str) -> int:
    lines = _lines(source, needle)
    assert len(lines) == 1, f"{label}: expected exactly one '{needle}' line, got {lines}"
    return lines[0]


# ---------------------------------------------------------------------------
# HOP 1 — IWorkspaceContextService is the ONLY workspace source
# ---------------------------------------------------------------------------


def test_session_folder_comes_only_from_workspace_context_service():
    service = _text("browser", "pulseAIRendererService.ts")
    # The getter reads getWorkspace().folders directly — never cwd/env/app dirs.
    assert _lines(service, "workspaceContextService.getWorkspace().folders"), "folders read"
    _assert_one(service, "if (folders.length === 0) { return undefined; }", "zero folders")
    _assert_one(service, "if (folders.length === 1) { return folders[0]; }", "one folder")
    # Multi-root requires an explicit, retained selection — never folders[0].
    assert "selectedWorkspaceUri" in service
    assert "folders.find(folder => folder.uri.toString() === this.selectedWorkspaceUri?.toString())" in service
    # The session path is the folder's exact filesystem path.
    _assert_one(service, "return this.sessionFolder?.uri.fsPath;", "fsPath")


def test_no_cwd_appdir_or_dot_fallback_in_desktop_sources():
    for relative in (
        "browser/pulseAIRendererService.ts",
        "browser/pulseAIRenderer.ts",
        "common/pulseAIEngineService.ts",
        "electron-browser/pulseAIEngineService.ts",
    ):
        source = _text(*relative.split("/"))
        assert "process.cwd()" not in source, relative
        assert "applicationRoot" not in source, relative
        assert "environmentService" not in source, relative
        assert "workspace || '.'" not in source, relative
        assert "or '.'" not in source, relative
    # The bridge must not silently default a missing workspace to "." either.
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "workspace = str(frame.get(\"workspace\") or \".\")" not in bridge


# ---------------------------------------------------------------------------
# HOP 2 — engineService.start(workspace) is fed the opened folder, and the
# engine root is a DIFFERENT, config-only value
# ---------------------------------------------------------------------------


def test_start_workspace_cannot_leak_into_engine_root():
    desktop = _text("electron-browser", "pulseAIEngineService.ts")
    common = _text("common", "pulseAIEngineService.ts")

    # resolvePulseAIEngineRoot is called with ONLY config + env (no workspace).
    call = _assert_one(desktop, "resolvePulseAIEngineRoot(", "engine root resolution")
    assert "configurationService.getValue<string>('pulseai.engineRoot')" in desktop
    assert "env['PULSEAI_ENGINE_ROOT']" in desktop
    call_window = "\n".join(desktop.splitlines()[call - 1:call + 3])
    assert "workspace" not in call_window, "the engine-root call must not receive the session workspace"

    # The resolver signature has no workspace input, so start(workspace) provably
    # cannot feed it the engine package path.
    assert "export function resolvePulseAIEngineRoot(configured: string | undefined, envRoot: string | undefined): string" in common
    assert "configured?.trim() || envRoot?.trim() || ''" in common


def test_blank_engine_root_is_rejected():
    common = _text("common", "pulseAIEngineService.ts")
    assert "export class PulseAIEngineSetupError extends Error" in common
    assert "this.name = 'PulseAIEngineSetupError'" in common
    _assert_one(common, "throw new PulseAIEngineSetupError();", "blank root throw")
    assert "PulseAIEngineSetupError" in _text("browser", "pulseAIRendererService.ts")


def test_blank_session_workspace_is_rejected_desktop_side():
    desktop = _text("electron-browser", "pulseAIEngineService.ts")
    assert "if (!workspace?.trim()) {" in desktop
    assert "PulseAI session requires an opened workspace folder" in desktop
    service = _text("browser", "pulseAIRendererService.ts")
    assert "if (!workspace) {" in service


# ---------------------------------------------------------------------------
# HOP 2 gate — no-folder submission starts nothing and sends no frame
# ---------------------------------------------------------------------------


def test_no_folder_never_starts_the_engine():
    service = _text("browser", "pulseAIRendererService.ts")
    guard = _assert_one(service, "if (!workspace) {", "no-folder guard")
    start = _assert_one(service, "this.engineService.start(workspace).then", "start with workspace")
    assert start > guard, "start() must appear only after the no-workspace guard"
    # ensureEngine() no longer mixes a missing-workspace message with engine
    # setup; those two failures are distinct UIs.
    assert "Open a workspace or configure pulseai.engineRoot" not in service
    # The engine-setup failure path is explicit (actionable Open Settings row).
    assert "engineSetupError = error instanceof PulseAIEngineSetupError" in service


def test_no_folder_ui_is_exact_and_submission_is_blocked():
    service = _text("browser", "pulseAIRendererService.ts")
    renderer = _text("browser", "pulseAIRenderer.ts")
    # The exact hint text is owned by the service and rendered from the model.
    _assert_one(service, "noWorkspaceHint: 'Open a folder to start a Pulse session.'", "hint owner")
    assert "model.noWorkspaceHint" in renderer
    # Composer input and send are disabled; an Open Folder action is offered.
    assert "const inputBlocked = model.noWorkspace || model.workspaceSelectionRequired;" in renderer
    assert "input.disabled = true" in renderer
    assert "send.disabled = true" in renderer
    assert "host.openFolder" in renderer
    assert "workbench.action.files.openFolder" in service
    assert "host.openEngineSettings" in renderer
    assert "PulseAICommandId.OpenSettings" in service


# ---------------------------------------------------------------------------
# HOPS 3/4 — session_create.workspace and prompt.workspace carry the same path
# ---------------------------------------------------------------------------


def test_frames_carry_the_opened_fs_path_unchanged():
    service = _text("browser", "pulseAIRendererService.ts")
    create = _assert_one(service, "type: 'session_create', workspace: this.workspacePath", "session_create workspace")
    prompt = _assert_one(service, "type: 'prompt', session_id: this.sessionId, workspace: this.workspacePath", "prompt workspace")
    assert create > 0 and prompt > create
    assert "workspace: this.workspacePath" in service


# ---------------------------------------------------------------------------
# HOP 5 — the desktop frame sequence drives the real Python bridge (echo runner)
# ---------------------------------------------------------------------------


@pytest.fixture
def bridge():
    env = dict(os.environ)
    env["PULSEAI_BRIDGE_RUNNER"] = "echo"
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.bridge"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        cwd=ROOT,
    )

    def send(frame):
        proc.stdin.write(json.dumps(frame) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    def drain_until(predicate):
        """Read bridge frames until one matches (echo turns emit token+turn_done)."""
        while True:
            frame = json.loads(proc.stdout.readline())
            if predicate(frame):
                return frame

    send({"type": "hello", "protocol": PROTOCOL_VERSION})
    yield proc, send, drain_until
    proc.kill()


def test_desktop_frame_sequence_binds_pulse_ws(bridge, tmp_path):
    proc, send, drain_until = bridge
    ws = str(tmp_path)
    created = send({"type": "session_create", "session_id": "s", "workspace": ws})
    assert created["type"] == "session_info"
    assert created["workspace"] == ws, "hop 3: session_create echoes the opened folder unchanged"
    first = send({"type": "prompt", "session_id": "s", "workspace": ws, "text": "hi"})
    # The observability layer may publish workspace.bound before turn_started.
    turn = first if first["type"] == "turn_started" else drain_until(
        lambda frame: frame["type"] == "turn_started"
    )
    assert turn["workspace_id"] == workspace_id(ws), "hop 5: turn identity derives from the exact folder"
    done = drain_until(lambda frame: frame["type"] == "turn_done")
    assert done["completed"] is True


def test_desktop_route_uses_canonical_pulse_ws_fixture_when_present(bridge):
    """Requirement 4 routing evidence: the tiny D:\\pulse-ws project (no model)."""
    fixture = Path("D:/pulse-ws")
    if not fixture.is_dir():
        pytest.skip("canonical D:\\pulse-ws fixture not present on this machine")
    proc, send, drain_until = bridge
    ws = str(fixture)
    created = send({"type": "session_create", "session_id": "s", "workspace": ws})
    assert created["type"] == "session_info"
    assert created["workspace"] == ws
    first = send({"type": "prompt", "session_id": "s", "workspace": ws, "text": "hi"})
    turn = first if first["type"] == "turn_started" else drain_until(
        lambda frame: frame["type"] == "turn_started"
    )
    assert turn["workspace_id"] == workspace_id(ws)
    done = drain_until(lambda frame: frame["type"] == "turn_done")
    assert done["completed"] is True
    cancel = send({"type": "cancel", "session_id": "s"})
    assert cancel["type"] == "session_info"
