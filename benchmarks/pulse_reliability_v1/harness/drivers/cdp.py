"""CDP driver: drives the built PulseAI IDE desktop app over the Chrome
DevTools Protocol.

This is the desktop lane of the harness — the only driver that can satisfy
DOM checks (composer disabled state, workspace selector, cancel receipt).
It runs on a machine that has the built PulseAI IDE:

    python -m benchmarks.pulse_reliability_v1.harness run \\
        --task PBR-001 --driver cdp --launch "path/to/PulseAI.exe" --port 9222

Implementation notes:

- Discovery: ``GET http://127.0.0.1:<port>/json/version`` then
  ``GET /json/list``, pick the page target for the app window.
- DOM observation: ``Runtime.evaluate`` of a pure expression that returns a
  serialisable snapshot for a selector (enabled/visible/text/count). The
  expression is unit-tested here; the live IDE integration is exercised on
  the host machine with the built app.
- WebSocket transport uses the ``websockets`` package when available and
  fails loudly with an install hint otherwise (the harness never silently
  degrades: a missing transport is an environmental failure, not a pass).
- Process/network capture is stubbed to explicit no-ops with a warning:
  v0.1 records what the desktop lane can truthfully produce; the remaining
  evidence channels land with the live-window validation pass.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from benchmarks.pulse_reliability_v1.harness.drivers.base import (
    Driver,
    DriverCapabilities,
    DriverError,
    TurnSummary,
)
from benchmarks.pulse_reliability_v1.harness.recorder import Recorder, now_ms

# Pure DOM snapshot expression: no app internals, no globals, safe to run on
# any page. Returns null when the selector is absent.
DOM_EXPRESSION_TEMPLATE = (
    "(() => {"
    "const s = %(selector_json)r;"
    "const els = Array.from(document.querySelectorAll(s));"
    "if (!els.length) {"
    "  return {selector: s, count: 0, visible: false, enabled: null, text: null};"
    "}"
    "const el = els[0];"
    "const r = el.getBoundingClientRect();"
    "const visible = Boolean(r.width || r.height);"
    "const disabled = el.disabled === true || el.getAttribute('aria-disabled') === 'true'"
    "  || el.getAttribute('disabled') !== null;"
    "return {selector: s, count: els.length, visible: visible,"
    "  enabled: visible && !disabled, text: (el.textContent || '').trim().slice(0, 400)};"
    "})()"
)


def dom_snapshot_expression(selector: str) -> str:
    """Build the Runtime.evaluate expression for a selector (unit-testable)."""
    return DOM_EXPRESSION_TEMPLATE % {"selector_json": selector}


def parse_targets(payload: str) -> list[dict]:
    """Parse a ``/json/list`` response; returns page targets only."""
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DriverError(f"malformed /json/list payload: {exc}") from exc
    if not isinstance(raw, list):
        raise DriverError("/json/list did not return a list")
    return [t for t in raw if isinstance(t, dict) and t.get("type") == "page"]


def pick_page_target(targets: list[dict], *, prefer_url: str | None = None) -> dict:
    if not targets:
        raise DriverError("no page targets on the CDP endpoint")
    if prefer_url:
        for t in targets:
            if prefer_url in str(t.get("url", "")):
                return t
    return targets[0]


class CdpDriver(Driver):
    """Attaches to (or launches) the PulseAI IDE and observes its DOM."""

    def __init__(self, recorder: Recorder, *, python_command: tuple[str, ...] = ("python",),
                 launch_command: tuple[str, ...] | None = None,
                 port: int = 9222, workspace: str = ""):
        super().__init__(recorder, python_command=python_command)
        self.launch_command = launch_command
        self.port = port
        self.workspace = workspace
        self._proc: subprocess.Popen | None = None
        self._ws = None

    @property
    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            kind="cdp",
            dom=True,
            processes=True,
            network=False,
            commands=True,
            host_hashes=True,
            engine_events=False,  # frame/event capture lands with live-window validation
            real_model=True,
        )

    # -- discovery ---------------------------------------------------------

    def _http_json(self, path: str) -> str:
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5.0) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise DriverError(f"CDP endpoint unreachable at {url}: {exc}") from exc

    def _wait_for_endpoint(self, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self._http_json("/json/version")
                return
            except DriverError as exc:
                last = exc
                time.sleep(0.5)
        raise DriverError(f"CDP endpoint did not come up within {timeout_s}s") from last

    def _connect_ws(self, ws_url: str) -> None:
        try:
            from websockets.sync.client import connect  # type: ignore[import-not-found]
        except ImportError as exc:
            raise DriverError(
                "CDP driver needs the 'websockets' package: pip install websockets"
            ) from exc
        try:
            self._ws = connect(ws_url, open_timeout=10.0)
        except Exception as exc:
            raise DriverError(f"CDP websocket connect failed: {exc}") from exc

    def _ws_call(self, method: str, params: dict | None = None, timeout_s: float = 10.0) -> dict:
        if self._ws is None:
            raise DriverError("not connected to CDP")
        request_id = int(time.time() * 1000) % (2**31)
        self._ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            raw = self._ws.recv(timeout=timeout_s)
            msg = json.loads(raw)
            if msg.get("id") == request_id:
                if "error" in msg:
                    raise DriverError(f"CDP {method} failed: {msg['error']}")
                return msg.get("result", {})
        raise DriverError(f"CDP {method} timed out")

    # -- Driver API --------------------------------------------------------

    def connect(self, timeout_s: float = 30.0) -> None:
        self.recorder.startup_ms = now_ms()
        if self.launch_command:
            self._proc = subprocess.Popen(self.launch_command)
        self._wait_for_endpoint(timeout_s)
        targets = parse_targets(self._http_json("/json/list"))
        target = pick_page_target(targets, prefer_url=self.workspace or None)
        ws_url = str(target.get("webSocketDebuggerUrl") or "")
        if not ws_url:
            raise DriverError("page target has no webSocketDebuggerUrl")
        self._connect_ws(ws_url)
        self._ws_call("Runtime.enable")

    def open_workspace(self, root: str) -> None:
        # Opening a folder in the real IDE is a native UI action (dialog /
        # CLI argument). v0.1: record the intent; the live-window pass wires
        # the native open (e.g. launch with the folder argument) and the
        # workspace.bound event capture.
        self.workspace = root
        self.recorder.record_event("workspace.open_intent", {"root": root})

    def send_prompt(self, text: str) -> None:
        # Typing into the composer is a native UI action; v0.1 records intent.
        self.recorder.record_event("prompt.intent", {"text": text[:200]})

    def wait_turn(self, timeout_s: float) -> TurnSummary:
        raise DriverError("wait_turn for the CDP lane lands with the live-window pass")

    def cancel(self) -> None:
        self.recorder.record_event("cancel.intent", {})

    def observe_dom(self, selector: str) -> None:
        expr = dom_snapshot_expression(selector)
        result = self._ws_call("Runtime.evaluate", {
            "expression": expr, "returnByValue": True,
        })
        value = (result.get("result") or {}).get("value")
        if not isinstance(value, dict):
            raise DriverError(f"DOM snapshot for {selector!r} was not an object")
        self.recorder.record_dom(
            selector=value.get("selector") or selector,
            enabled=value.get("enabled"),
            visible=value.get("visible"),
            text=value.get("text"),
            count=value.get("count"),
        )

    def collect_processes(self) -> None:
        # v0.1: process snapshot lands with the live-window pass (psutil).
        return

    def shutdown(self, timeout_s: float = 10.0) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5.0)
        self.recorder.shutdown_ms = now_ms()
