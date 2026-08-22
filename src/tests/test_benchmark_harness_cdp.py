"""CDP driver integration tests against a mock Chrome DevTools endpoint.

The built PulseAI IDE cannot exist in a fresh checkout (build artifacts are
gitignored by design), so the live app is tested on the founder's machine.
What CAN be proven anywhere is that the CDP driver speaks the protocol
correctly: this suite stands up a real HTTP + WebSocket mock of the IDE's
debug endpoint and drives the driver through connect / DOM observation /
launch / unreachable-endpoint failure — over actual wire traffic.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from benchmarks.pulse_reliability_v1.harness.drivers.base import DriverError
from benchmarks.pulse_reliability_v1.harness.drivers.cdp import CdpDriver
from benchmarks.pulse_reliability_v1.harness.recorder import Recorder

REPO_ROOT = Path(__file__).resolve().parents[2]
_TEST_DIR = str(Path(__file__).resolve().parent)
_REPO_ROOT = str(Path(__file__).resolve().parents[2])

# ---------------------------------------------------------------------------
# Mock CDP endpoint (real HTTP + WebSocket on 127.0.0.1)
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_mock_cdp(http_port: int, ws_port: int, workspace_url: str = "file:///C:/bench-ws") -> None:
    """Run the mock CDP endpoint in the current process (blocks forever).

    Serves /json/version + /json/list over HTTP (discovery) and answers
    Runtime.enable / Runtime.evaluate over WebSocket with canned PulseAI DOM
    snapshots. The advertised WebSocket URL points at ``ws_port`` — a real
    browser serves both from one port via HTTP upgrade; the mock uses two
    listeners because stdlib http.server cannot upgrade. The driver only
    trusts the advertised URL, so the shape it exercises is identical.
    """
    import websockets.sync.server as ws_server

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/json/version":
                body = json.dumps({
                    "Browser": "PulseAI/1.0 (mock)",
                    "webSocketDebuggerUrl": f"ws://127.0.0.1:{ws_port}/devtools/browser/1",
                }).encode("utf-8")
            elif self.path == "/json/list":
                body = json.dumps([{
                    "type": "page",
                    "url": workspace_url,
                    "webSocketDebuggerUrl": f"ws://127.0.0.1:{ws_port}/devtools/page/1",
                }]).encode("utf-8")
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # silence
            pass

    def respond(conn) -> None:
        for raw in conn:
            msg = json.loads(raw)
            mid = msg.get("id")
            method = msg.get("method")
            if method == "Runtime.evaluate":
                expr = str((msg.get("params") or {}).get("expression") or "")
                if "pulseai-composer-input" in expr:
                    value = {"selector": "textarea.pulseai-composer-input", "count": 1,
                             "visible": True, "enabled": False, "text": ""}
                elif "pulseai-composer-hint" in expr:
                    value = {"selector": ".pulseai-composer-hint", "count": 1,
                             "visible": True, "enabled": None,
                             "text": "Open a folder to start a Pulse session."}
                else:
                    value = {"selector": "unknown", "count": 0,
                             "visible": False, "enabled": None, "text": None}
                conn.send(json.dumps({
                    "id": mid,
                    "result": {"result": {"type": "object", "value": value}},
                }))
            else:
                conn.send(json.dumps({"id": mid, "result": {}}))

    httpd = HTTPServer(("127.0.0.1", http_port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    with ws_server.serve(respond, "127.0.0.1", ws_port) as server:
        server.serve_forever()


class MockCdp:
    """Context manager that runs the mock endpoint in a child process."""

    def __init__(self, workspace_url: str = "file:///C:/bench-ws"):
        self.port = _free_port()
        self.ws_port = _free_port()
        self.workspace_url = workspace_url
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "MockCdp":
        script = (
            "import sys;"
            f"sys.path.insert(0, {_TEST_DIR!r});"
            f"sys.path.insert(0, {_REPO_ROOT!r});"
            f"import test_benchmark_harness_cdp as m;"
            f"m.run_mock_cdp({self.port}, {self.ws_port}, {self.workspace_url!r})"
        )
        self.proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.3):
                    return self
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("mock CDP endpoint did not come up")

    def __exit__(self, *exc) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()


@pytest.fixture()
def mock_cdp():
    with MockCdp() as mock:
        yield mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cdp_connect_and_observe_dom(mock_cdp):
    rec = Recorder()
    driver = CdpDriver(rec, port=mock_cdp.port)
    driver.connect(timeout_s=10.0)
    assert rec.startup_ms is not None

    driver.observe_dom("textarea.pulseai-composer-input")
    driver.observe_dom(".pulseai-composer-hint")

    by_selector = {d.selector: d for d in rec.dom}
    assert by_selector["textarea.pulseai-composer-input"].enabled is False
    assert by_selector["textarea.pulseai-composer-input"].visible is True
    assert by_selector[".pulseai-composer-hint"].text == "Open a folder to start a Pulse session."
    driver.shutdown()


def test_cdp_prefer_workspace_target(mock_cdp):
    rec = Recorder()
    driver = CdpDriver(rec, port=mock_cdp.port, workspace="C:/bench-ws")
    driver.connect(timeout_s=10.0)  # pick_page_target prefers the workspace URL
    driver.observe_dom(".pulseai-composer-hint")
    assert any(d.selector == ".pulseai-composer-hint" for d in rec.dom)
    driver.shutdown()


def test_cdp_unreachable_endpoint_fails_loudly():
    rec = Recorder()
    port = _free_port()  # nothing listens here
    driver = CdpDriver(rec, port=port)
    with pytest.raises(DriverError, match="CDP endpoint did not come up"):
        driver.connect(timeout_s=2.0)


def test_pbr001_cdp_end_to_end_passes_against_mock(mock_cdp, tmp_path, monkeypatch):
    """The full PBR-001 task on the cdp lane, graded by the evaluator.

    This is exactly what runs on the founder's machine against the built
    IDE: connect → observe composer + hint DOM → no prompt frames → grade.
    A PASS here proves the desktop pipeline is wired end-to-end; only the
    live app remains for the real run.
    """
    monkeypatch.chdir(tmp_path)  # keep artifacts out of the repo's bench-results
    from benchmarks.pulse_reliability_v1.harness.orchestrator import run_task

    record, result, run_dir = run_task(
        task_id="PBR-001", driver_kind="cdp", workspace=str(tmp_path),
        suite_path=str(REPO_ROOT / "benchmarks/pulse_reliability_v1/manifest.json"),
        python_command=(sys.executable,),
        port=mock_cdp.port,
        run_id="test-pbr001-cdp-mock",
    )
    by_id = {c.check_id: c for c in result.checks}
    assert by_id["composer-disabled"].classification.value == "passed"
    assert by_id["no-workspace-hint"].classification.value == "passed"
    assert by_id["no-prompt-frame"].classification.value == "passed"
    assert result.outcome.value == "passed"
    assert result.hard_failure is None


def test_cdp_launch_command_spawns_and_connects(tmp_path):
    """--launch spawns the IDE launcher; the driver waits, attaches, observes."""
    launcher = tmp_path / "mock_launch.py"
    launcher.write_text(
        "import sys\n"
        f"sys.path.insert(0, {_TEST_DIR!r})\n"
        f"sys.path.insert(0, {_REPO_ROOT!r})\n"
        "import test_benchmark_harness_cdp as m\n"
        "m.run_mock_cdp(int(sys.argv[1]), int(sys.argv[2]))\n",
        encoding="utf-8",
    )
    port = _free_port()
    ws_port = _free_port()
    rec = Recorder()
    driver = CdpDriver(
        rec, port=port,
        launch_command=(sys.executable, str(launcher), str(port), str(ws_port)),
    )
    driver.connect(timeout_s=10.0)
    assert driver._proc is not None  # the launch command really ran
    driver.observe_dom("textarea.pulseai-composer-input")
    assert any(d.selector == "textarea.pulseai-composer-input" for d in rec.dom)
    driver.shutdown()
    assert driver._proc.poll() is not None  # terminated cleanly
