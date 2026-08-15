"""Contract pins for the selective PulseAI IDE Bridge Protocol v2 overlay."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from src.bridge.protocol import CLIENT_METHODS, SERVER_EVENTS

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "src" / "bridge" / "protocol_v2.json"
GENERATED = (
    ROOT / "desktop" / "src" / "vs" / "workbench" / "contrib" /
    "pulseai" / "common" / "pulseAIProtocol.generated.ts"
)
PAYLOADS = GENERATED.with_name("pulseAIProtocol.ts")


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


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


def test_selective_desktop_overlay_stays_tiny():
    desktop = ROOT / "desktop"
    files = [path for path in desktop.rglob("*") if path.is_file()]
    assert files
    total = sum(path.stat().st_size for path in files)
    assert total < 1_000_000, f"selective desktop overlay grew to {total:,} bytes"
    assert not (desktop / "node_modules").exists()
    assert not (desktop / "extensions").exists()
