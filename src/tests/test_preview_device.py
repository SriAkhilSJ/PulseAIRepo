"""Crusor Preview — the device pane, end to end over real sockets.

The pane exists to put a *phone* where a web page used to be, so these tests run a real
:class:`~src.preview.server.PreviewServer` and a fake ``adb`` on PATH, then assert the
properties the feature depends on:

* registration is secret-guarded and refuses honestly when there is nothing to mirror
  (``409`` with a sentence a human can act on, never a pane showing a black rectangle);
* the pane document points at absolute device URLs — the preview window frames it through
  ``/p/<token>/``, where a relative URL would be re-proxied instead of reaching the device;
* the frame stream is real ``multipart/x-mixed-replace`` and starts with a frame before it
  answers ``200`` (so "cannot stream" is a legible error, not an image that never loads);
* the inspect overlay is never injected into our own pane, while a normal target still gets it;
* normalized input maps to the right device pixels, and the adb argv actually run is the one
  ``input_commands`` said it would be.

``urllib``, like the rest of the preview tests: the runtime is stdlib-only by policy.
"""
from __future__ import annotations

import json
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from src.preview.device import DEVICE_PATH, DEVICE_PREFIX, input_commands
from src.preview.server import PreviewServer

TEST_SECRET = "device-pane-secret"
FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)

# A single fake adb that answers every command the pane uses. Frames come from a file
# ($FAKE_ADB_FRAME) and every input call is appended to $FAKE_ADB_LOG, so a test can assert
# the exact argv that ran instead of trusting the mapping twice.
_ADB_SCRIPT = """#!/bin/sh
if [ "$1" = "devices" ]; then
  printf 'List of devices attached\\n'
  printf '%s\\n' "$FAKE_ADB_DEVICES"
  exit 0
fi
# -s <serial> <command...>
shift 2
case "$*" in
  "shell getprop ro.product.model") printf '%s\\n' "${FAKE_ADB_MODEL:-Pixel 7}"; exit 0 ;;
  "shell wm size") printf 'Physical size: 1080x2400\\n'; exit 0 ;;
  "exec-out screencap -p") cat "$FAKE_ADB_FRAME"; exit 0 ;;
esac
printf '%s\\n' "$*" >> "$FAKE_ADB_LOG"
if [ -n "$FAKE_ADB_FAIL_INPUT" ]; then printf 'error: device offline\\n' >&2; exit 1; fi
exit 0
"""


class _Handle:
    """Minimal stand-in for ``ProxyHandle``: the tool only reads ``.origin``."""

    def __init__(self, origin: str) -> None:
        self.origin = origin


def _fake_adb(directory: Path, *, devices: list[str] | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "adb"
    path.write_text(_ADB_SCRIPT, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    lines = devices if devices is not None else [
        "emulator-5554          device product:sdk_gphone64_x86_64 model:Pixel_7 device:emu64xa transport_id:1",
    ]
    (directory / "devices.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def adb_host(tmp_path, monkeypatch):
    """A PATH with only our fake adb, and the env it needs."""
    bin_dir = tmp_path / "bin"
    _fake_adb(bin_dir)
    frame = tmp_path / "frame.png"
    frame.write_bytes(FAKE_PNG)
    log = tmp_path / "input.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("CRUSORAI_ADB", str(bin_dir / "adb"))
    monkeypatch.setenv("FAKE_ADB_FRAME", str(frame))
    monkeypatch.setenv("FAKE_ADB_LOG", str(log))
    monkeypatch.setenv("FAKE_ADB_DEVICES", (bin_dir / "devices.txt").read_text(encoding="utf-8").strip())
    monkeypatch.setenv("CRUSORAI_DEVICE_JPEG", "0")  # keep frames byte-identical to the fixture
    return {"bin": bin_dir, "log": log}


@pytest.fixture()
def server(tmp_path, adb_host):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instance = PreviewServer(workspace, host="127.0.0.1", port=0, secret=TEST_SECRET).start()
    yield instance
    instance.stop()


def _request(server: PreviewServer, path: str, *, method: str = "GET", body: dict | None = None,
             secret: str | None = None, timeout: float = 10.0):
    url = f"{server.origin}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if secret is not None:
        request.add_header("X-Crusor-Preview-Secret", secret)
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - loopback test server


def _register(server: PreviewServer, **payload) -> dict:
    with _request(server, DEVICE_PATH, method="POST", body=payload, secret=TEST_SECRET) as response:
        return json.loads(response.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# pure mapping: the part with a right answer
# --------------------------------------------------------------------------- #

def test_tap_and_swipe_map_normalized_points_to_device_pixels():
    commands, error = input_commands({"action": "tap", "x": 0.5, "y": 0.5}, width=1080, height=2400)
    assert error == "" and commands == [["shell", "input", "tap", "540", "1200"]]

    commands, error = input_commands(
        {"action": "swipe", "x": 0.1, "y": 0.9, "x2": 0.9, "y2": 0.1, "ms": 500},
        width=1080, height=2400,
    )
    assert error == ""
    assert commands == [["shell", "input", "swipe", "108", "2160", "972", "240", "500"]]


def test_input_rejects_out_of_range_and_unknown_actions():
    _, error = input_commands({"action": "tap", "x": 1.4, "y": 0.5}, width=1080, height=2400)
    assert "normalized" in error
    _, error = input_commands({"action": "tap", "x": 0.5, "y": 0.5}, width=0, height=0)
    assert "size is unknown" in error
    _, error = input_commands({"action": "fly"}, width=1080, height=2400)
    assert "unknown action" in error
    _, error = input_commands("not-an-object", width=1080, height=2400)
    assert "JSON object" in error


def test_text_escaping_survives_the_device_shell():
    commands, error = input_commands({"action": "text", "text": "Ada Lovelace & co"}, width=1, height=1)
    assert error == ""
    # Spaces become %s (a literal space ends the adb argument); shell metacharacters are escaped.
    assert commands == [["shell", "input", "text", "Ada%sLovelace%s\\&%sco"]]


def test_keys_map_to_stable_android_codes():
    commands, _ = input_commands({"action": "key", "key": "back"}, width=1, height=1)
    assert commands == [["shell", "input", "keyevent", "4"]]
    commands, _ = input_commands({"action": "key", "key": "26"}, width=1, height=1)
    assert commands == [["shell", "input", "keyevent", "26"]]
    _, error = input_commands({"action": "key", "key": "hyperspace"}, width=1, height=1)
    assert "unknown key" in error


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #

def test_registration_requires_the_secret(server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _request(server, DEVICE_PATH, method="POST", body={}, secret="wrong")
    assert excinfo.value.code == 403
    assert "secret" in json.loads(excinfo.value.read().decode("utf-8"))["error"]


def test_registration_mirrors_the_single_attached_device(server):
    payload = _register(server)
    assert payload["ok"] and payload["kind"] == "device"
    assert payload["serial"] == "emulator-5554"
    assert payload["model"] == "Pixel 7"
    assert (payload["width"], payload["height"]) == (1080, 2400)
    assert payload["paneUrl"] == f"{DEVICE_PREFIX}{payload['token']}/"


def test_registration_refuses_when_no_device_is_attached(server, adb_host, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_DEVICES", "")  # adb answers, nothing is plugged in
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _register(server)
    assert excinfo.value.code == 409  # not a client error: the host has nothing to mirror
    assert "no Android device or emulator is attached" in json.loads(excinfo.value.read().decode("utf-8"))["error"]


def test_registration_reports_an_unauthorized_device_by_name(server, adb_host, monkeypatch):
    monkeypatch.setenv(
        "FAKE_ADB_DEVICES",
        "ZY22ABC123            unauthorized usb:1-3 transport_id:7",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _register(server)
    error = json.loads(excinfo.value.read().decode("utf-8"))["error"]
    assert "ZY22ABC123 (unauthorized)" in error


def test_registration_without_adb_explains_the_install(server, monkeypatch):
    monkeypatch.setenv("PATH", "")           # nothing on PATH…
    monkeypatch.setenv("CRUSORAI_ADB", "")   # …and no override
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _register(server)
    assert excinfo.value.code == 409
    assert "adb is not installed" in json.loads(excinfo.value.read().decode("utf-8"))["error"]


# --------------------------------------------------------------------------- #
# the pane document
# --------------------------------------------------------------------------- #

def test_pane_document_uses_absolute_device_urls_and_leaks_no_secret(server):
    token = _register(server)["token"]
    with _request(server, f"{DEVICE_PREFIX}{token}/") as response:
        body = response.read().decode("utf-8")
        assert response.headers["Content-Type"].startswith("text/html")
    assert f'{DEVICE_PREFIX}{token}/stream' in body
    assert "emulator-5554" in body and "Pixel 7" in body
    assert TEST_SECRET not in body


def test_unknown_pane_token_is_a_404(server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _request(server, f"{DEVICE_PREFIX}not-a-real-token/")
    assert excinfo.value.code == 404


def test_pane_status_reports_geometry_and_errors(server):
    token = _register(server)["token"]
    with _request(server, f"{DEVICE_PREFIX}{token}/status") as response:
        status = json.loads(response.read().decode("utf-8"))
    assert status["serial"] == "emulator-5554"
    assert (status["width"], status["height"]) == (1080, 2400)
    assert status["last_error"] == ""
    assert status["viewers"] == 0


# --------------------------------------------------------------------------- #
# the stream
# --------------------------------------------------------------------------- #

def test_stream_starts_with_a_frame_and_is_a_multipart_stream(server):
    token = _register(server)["token"]
    request = urllib.request.Request(f"{server.origin}{DEVICE_PREFIX}{token}/stream")
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - loopback
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("multipart/x-mixed-replace")
        chunk = response.read(256)  # one part is enough: the boundary then the fixture bytes
    assert b"--crusordevice" in chunk
    assert FAKE_PNG[:8] in chunk  # the PNG signature survived the part framing


def test_stream_answers_a_readable_error_when_capture_fails(server, adb_host, monkeypatch):
    token = _register(server)["token"]
    monkeypatch.setenv("FAKE_ADB_FRAME", str(adb_host["bin"] / "missing.png"))
    request = urllib.request.Request(f"{server.origin}{DEVICE_PREFIX}{token}/stream")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=10)  # noqa: S310 - loopback
    assert excinfo.value.code == 503
    payload = json.loads(excinfo.value.read().decode("utf-8"))
    assert payload["ok"] is False and payload["hint"]


def test_single_frame_endpoint_serves_the_png(server):
    token = _register(server)["token"]
    with _request(server, f"{DEVICE_PREFIX}{token}/frame") as response:
        body = response.read()
        assert response.headers["Content-Type"] == "image/png"
    assert body == FAKE_PNG


# --------------------------------------------------------------------------- #
# input
# --------------------------------------------------------------------------- #

def test_pane_input_runs_the_adb_command_the_mapping_promised(server, adb_host):
    token = _register(server)["token"]
    with _request(server, f"{DEVICE_PREFIX}{token}/input", method="POST",
                  body={"action": "tap", "x": 0.5, "y": 0.5}) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["ok"] is True
    assert payload["ran"][0]["argv"] == ["shell", "input", "tap", "540", "1200"]
    assert "shell input tap 540 1200" in adb_host["log"].read_text(encoding="utf-8")


def test_pane_input_rejects_bad_coordinates_without_touching_the_device(server, adb_host):
    token = _register(server)["token"]
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _request(server, f"{DEVICE_PREFIX}{token}/input", method="POST",
                 body={"action": "tap", "x": 9, "y": 0})
    assert excinfo.value.code == 400
    assert adb_host["log"].read_text(encoding="utf-8") == ""


def test_pane_input_surfaces_a_failing_adb_command(server, adb_host, monkeypatch):
    token = _register(server)["token"]
    monkeypatch.setenv("FAKE_ADB_FAIL_INPUT", "1")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _request(server, f"{DEVICE_PREFIX}{token}/input", method="POST",
                 body={"action": "key", "key": "home"})
    assert excinfo.value.code == 502
    assert "offline" in json.loads(excinfo.value.read().decode("utf-8"))["error"]


def test_release_forgets_the_pane(server):
    token = _register(server)["token"]
    with _request(server, f"{DEVICE_PREFIX}{token}/release", method="POST", body={}) as response:
        assert json.loads(response.read().decode("utf-8"))["ok"] is True
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _request(server, f"{DEVICE_PREFIX}{token}/status")
    assert excinfo.value.code == 404


# --------------------------------------------------------------------------- #
# interaction with the web preview path
# --------------------------------------------------------------------------- #

def test_framing_a_device_pane_skips_the_inspect_overlay(server, tmp_path):
    """The window frames a pane by registering its URL — that document is already ours."""
    registered = _register(server)
    pane_url = f"{server.origin}{registered['paneUrl']}"
    with _request(server, "/crusor-preview/target", method="POST",
                  body={"url": pane_url, "label": "device"}, secret=TEST_SECRET) as response:
        proxied = json.loads(response.read().decode("utf-8"))["previewUrl"]
    with _request(server, proxied) as response:
        body = response.read().decode("utf-8")
    assert "crusor-preview-overlay" not in body   # no DOM inspector on a device mirror
    assert f"{DEVICE_PREFIX}{registered['token']}/stream" in body


def test_a_normal_target_still_gets_the_overlay(server):
    """The skip above must be a device-pane exception, never a global "stop injecting"."""
    page = Path(server.workspace) / "index.html"
    page.write_text("<!doctype html><html><body>hello</body></html>", encoding="utf-8")
    with _request(server, "/crusor-preview/target", method="POST",
                  body={"file": "index.html"}, secret=TEST_SECRET) as response:
        proxied = json.loads(response.read().decode("utf-8"))["previewUrl"]
    with _request(server, proxied) as response:
        body = response.read().decode("utf-8")
    assert "crusor-preview-overlay" in body


# --------------------------------------------------------------------------- #
# the agent tool
# --------------------------------------------------------------------------- #

def test_device_preview_tool_returns_a_pane_and_opens_the_ide_window(server, monkeypatch, tmp_path):
    from src.tools import target_tools

    calls: list[str] = []

    class FakeTool:
        @staticmethod
        def func(url, config):  # noqa: ANN001 - mirrors the langchain tool signature
            calls.append(url)
            return "✅ preview window opened"

    monkeypatch.setattr("src.preview.autostart.ensure_proxy", lambda workspace: _Handle(server.origin))
    monkeypatch.setattr("src.preview.endpoint.read_endpoint", lambda session: {"secret": TEST_SECRET})
    monkeypatch.setattr("src.tools.host_tools.open_preview", FakeTool)

    receipt = target_tools.device_preview.invoke(
        {"device": "", "label": "demo app"},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert receipt.startswith("🖥️ DEVICE PREVIEW")
    assert f"{DEVICE_PREFIX}" in receipt and "emulator-5554" in receipt
    assert "real input" in receipt
    assert calls and calls[0].startswith(server.origin)


def test_device_preview_tool_reports_a_mirror_less_host(server, monkeypatch, tmp_path, adb_host):
    from src.tools import target_tools

    monkeypatch.setenv("FAKE_ADB_DEVICES", "")  # proxy answers, host has nothing attached
    monkeypatch.setattr("src.preview.autostart.ensure_proxy", lambda workspace: _Handle(server.origin))
    monkeypatch.setattr("src.preview.endpoint.read_endpoint", lambda session: {"secret": TEST_SECRET})

    receipt = target_tools.device_preview.invoke(
        {"device": "", "label": ""}, config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert receipt.startswith("⛔") and "found nothing to mirror" in receipt


def test_device_preview_tool_reports_a_proxy_that_will_not_start(monkeypatch, tmp_path):
    from src.tools import target_tools

    monkeypatch.setattr("src.preview.autostart.ensure_proxy", lambda workspace: None)
    receipt = target_tools.device_preview.invoke(
        {"device": "", "label": ""}, config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert receipt.startswith("⛔") and "preview proxy" in receipt

