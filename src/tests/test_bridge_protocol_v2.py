"""Contract pins for the PulseAI IDE Bridge Protocol v2 inside the canonical fork."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from src.bridge.__main__ import BridgeServer
from src.bridge.protocol import CLIENT_METHODS, SERVER_EVENTS
from src.runtime.identity import TurnIdentity

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "src" / "bridge" / "protocol_v2.json"
GENERATED = (
    ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" /
    "pulseai" / "common" / "pulseAIProtocol.generated.ts"
)
PAYLOADS = GENERATED.with_name("pulseAIProtocol.ts")


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _tracked(rel: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", rel],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line.strip()]


def _frame_names(section: str) -> set[str]:
    return set(re.findall(r"readonly type: '([^']+)'", section))


def test_v2_manifest_covers_current_python_bridge_surface():
    data = _manifest()
    assert data["protocol"] == 2
    assert set(data["client_methods"]) == set(CLIENT_METHODS)
    assert set(data["server_events"]) == set(SERVER_EVENTS)


def test_v2_approval_identity_is_tool_id():
    data = _manifest()
    assert data["approval_identity_field"] == "tool_id"
    text = PAYLOADS.read_text(encoding="utf-8")
    safety = re.search(r"type: 'safety_reply'.*?PulseSessionRequest\)", text, re.S)
    assert safety is not None
    assert "readonly tool_id: string" in safety.group(0)
    assert "request_id" not in safety.group(0)


def test_generated_typescript_is_current():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_bridge_protocol.py"), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_handwritten_payload_union_covers_every_generated_name():
    text = PAYLOADS.read_text(encoding="utf-8")
    server, client = text.split("export type PulseClientMethod =", 1)
    assert _frame_names(server) == set(_manifest()["server_events"])
    assert _frame_names(client) == set(_manifest()["client_methods"])


def test_event_bus_projection_normalizes_stream_tool_and_approval_fields(tmp_path):
    identity = TurnIdentity.create(session_id="s1", workspace=str(tmp_path))
    token = BridgeServer._project_event(
        {"type": "message.agent.chunk", "event_id": "e1", "payload": {"chunk": "hello"}},
        identity,
    )
    assert token["type"] == "token" and token["text"] == "hello"

    started = BridgeServer._project_event({
        "type": "tool.call", "event_id": "e2",
        "payload": {"tool_id": "s1-call-7", "tool_name": "edit_file", "tool_args": {"path": "a.py"}},
    }, identity)
    assert started["tool_id"] == "call-7"
    assert started["name"] == "edit_file"
    assert started["arguments"] == {"path": "a.py"}

    approval = BridgeServer._project_event({
        "type": "tool.approval.request", "event_id": "e3",
        "payload": {
            "id": "call-7", "tool_name": "edit_file", "tool_args": {"path": "a.py"},
            "diff": {"path": "a.py", "old_text": "old", "new_text": "new"},
        },
    }, identity)
    assert approval["tool_id"] == "call-7"
    assert approval["name"] == "edit_file"
    assert approval["diff"]["new_text"] == "new"


def test_durable_replay_projection_emits_protocol_tool_frames():
    rows = [
        {
            "type": "tool.intent", "event_id": "e1", "session_id": "s", "turn_id": "t",
            "workspace_id": "w", "tool_call_id": "tool-1",
            "payload": {"tool_name": "read_file", "args": {"path": "README.md"}},
        },
        {
            "type": "tool.result", "event_id": "e2", "session_id": "s", "turn_id": "t",
            "workspace_id": "w", "tool_call_id": "tool-1",
            "payload": {"tool_name": "read_file", "status": "ok", "content": "done"},
        },
    ]
    projected = BridgeServer._project_stored_events(rows)
    assert [event["type"] for event in projected] == ["tool_call_start", "tool_call_end"]
    assert projected[0]["arguments"] == {"path": "README.md"}
    assert projected[1]["status"] == "ok" and projected[1]["result"] == "done"


def test_bridge_accepts_only_allowlisted_read_only_host_capabilities(tmp_path):
    frames = [
        {"type": "hello", "protocol": 2},
        {"type": "session_create", "session_id": "host-test", "workspace": str(tmp_path)},
        {
            "type": "host_capabilities_update", "session_id": "host-test",
            "workspace": str(tmp_path), "capabilities": [
                {"id": "diagnostics.markers", "availability": "available", "risk": "read"},
                {"id": "terminal.native", "availability": "available", "risk": "execute"},
            ],
        },
        {"type": "shutdown"},
    ]
    result = subprocess.run(
        [sys.executable, "-m", "src.bridge"], cwd=ROOT,
        input="".join(json.dumps(frame) + "\n" for frame in frames),
        text=True, capture_output=True, timeout=20,
        env={**os.environ, "PULSEAI_BRIDGE_RUNNER": "echo"},
    )
    assert result.returncode == 0, result.stderr
    output = [json.loads(line) for line in result.stdout.splitlines()]
    assert any(frame.get("host_capabilities_updated") == 1 for frame in output)


def test_selective_desktop_metadata_stays_tiny():
    desktop = ROOT / "desktop"
    metadata = [
        desktop / ".nvmrc",
        desktop / "README.md",
        desktop / "SELECTIVE_MANIFEST.json",
        desktop / "UPSTREAM_PIN",
    ]
    total = sum(path.stat().st_size for path in metadata if path.exists())
    assert total < 10_000, f"desktop metadata grew to {total:,} bytes"
    assert not (desktop / "node_modules").exists()
    assert not _tracked("desktop/vscode/node_modules/**"), "fork node_modules must never be committed"
    result = subprocess.run(
        ["git", "check-ignore", "--", "desktop/vscode/node_modules/x", "desktop/vscode/.vscode/x",
         "desktop/vscode/extensions/cpp/build/x"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    ignored = result.stdout.splitlines()
    assert "desktop/vscode/node_modules/x" in ignored
    assert "desktop/vscode/.vscode/x" in ignored
    assert "desktop/vscode/extensions/cpp/build/x" in ignored
    assert not (desktop / "vscode" / "extensions" / "pulseai").exists()
