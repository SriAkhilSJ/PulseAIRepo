"""Minimal, local-only Chrome DevTools Protocol client.

Deliberately small and dependency-light: HTTP discovery over
``http://127.0.0.1:<port>`` and a ``websockets`` transport. The harness refuses
any non-loopback endpoint, so evidence can never be collected from a debugging
port exposed beyond the local machine.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


class CdpError(RuntimeError):
    pass


@dataclass
class CdpTarget:
    id: str
    type: str
    title: str
    url: str
    websocket_url: str
    browser_context_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "url": self.url,
            "websocket_origin": origin_of(self.websocket_url),
            "browser_context_id": self.browser_context_id,
        }


def origin_of(ws_url: str) -> str:
    """Return only scheme/host/port of a ws URL (never the random full path)."""
    try:
        parsed = urlparse(ws_url)
    except ValueError:
        return ""
    if not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def assert_loopback(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise CdpError(f"refusing non-loopback CDP endpoint {url!r} (host={host!r})")


def parse_targets(payload: str) -> list[CdpTarget]:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CdpError(f"malformed /json/list payload: {exc}") from exc
    if not isinstance(raw, list):
        raise CdpError("/json/list did not return a list")
    out: list[CdpTarget] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "page":
            continue
        out.append(CdpTarget(
            id=str(item.get("id") or ""),
            type=str(item.get("type") or ""),
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            websocket_url=str(item.get("webSocketDebuggerUrl") or ""),
            browser_context_id=str(item.get("browserContextId") or ""),
        ))
    return out


def pick_page_target(targets: list[CdpTarget], *, prefer_title: str = "", prefer_url: str = "") -> CdpTarget:
    """Choose the app's main workbench page (never a devtools/extension page)."""
    if not targets:
        raise CdpError("no page targets on the CDP endpoint")
    candidates = [t for t in targets if t.websocket_url]
    if not candidates:
        raise CdpError("no page target exposes a webSocketDebuggerUrl")
    if prefer_title:
        needle = prefer_title.lower()
        for target in candidates:
            if needle in target.title.lower():
                return target
    if prefer_url:
        needle = prefer_url.lower()
        for target in candidates:
            if needle in target.url.lower():
                return target
    for target in candidates:
        if "workbench" in target.url.lower() or target.url.startswith("vscode-file:"):
            return target
    return candidates[0]


def build_dom_snapshot_expression(selector: str) -> str:
    """Pure DOM snapshot for one selector — returns a JSON-serialisable object."""
    encoded = json.dumps(selector)
    return (
        "(() => {"
        f"const s = {encoded};"
        "const els = Array.from(document.querySelectorAll(s));"
        "if (!els.length) { return {selector: s, count: 0, visible: false, enabled: null, text: null}; }"
        "const el = els[0];"
        "const r = el.getBoundingClientRect();"
        "const style = window.getComputedStyle(el);"
        "const visible = Boolean(r.width || r.height) && style.display !== 'none' && style.visibility !== 'hidden';"
        "const disabled = el.disabled === true || el.getAttribute('aria-disabled') === 'true' || el.hasAttribute('disabled');"
        "return {selector: s, count: els.length, visible: visible, enabled: Boolean(visible && !disabled),"
        "  text: (el.textContent || '').trim().slice(0, 400),"
        "  tag: el.tagName, id: el.id || '', cls: String(el.className || '').slice(0, 200),"
        "  placeholder: el.getAttribute('placeholder') || '',"
        "  rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}};"
        "})()"
    )


RENDERER_INSTRUMENTATION = r"""
(() => {
  if (window.__crusoraiObs) { return {installed: false, reason: 'already'}; }
  const CAP = 200;
  const obs = {errors: [], rejects: [], consoleErrors: [], consoleWarns: [], installedAt: new Date().toISOString()};
  window.__crusoraiObs = obs;
  const push = (bucket, entry) => { try { bucket.push(entry); if (bucket.length > CAP) { bucket.shift(); } } catch (e) {} };
  window.addEventListener('error', (event) => {
    push(obs.errors, {
      kind: 'error',
      message: String(event && event.message || ''),
      source: String(event && event.filename || ''),
      line: event && event.lineno || 0,
      stack: event && event.error && String(event.error.stack || '').slice(0, 2000) || ''
    });
  }, true);
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event && event.reason;
    push(obs.rejects, {
      kind: 'unhandledrejection',
      message: String(reason && reason.message || reason || ''),
      stack: reason && String(reason.stack || '').slice(0, 2000) || ''
    });
  }, true);
  const wrap = (name, bucket) => {
    const original = console[name];
    if (typeof original !== 'function') { return; }
    console[name] = function () {
      try {
        const parts = Array.from(arguments).map((a) => {
          if (a instanceof Error) { return a.message + '\n' + String(a.stack || ''); }
          if (typeof a === 'string') { return a; }
          try { return JSON.stringify(a); } catch (e) { return String(a); }
        });
        push(bucket, {kind: name, message: parts.join(' ').slice(0, 2000), at: new Date().toISOString()});
      } catch (e) {}
      return original.apply(this, arguments);
    };
  };
  wrap('error', obs.consoleErrors);
  wrap('warn', obs.consoleWarns);
  return {installed: true};
})()
"""

#: Minimum bar for "this page is the Crusor desktop workbench, not a browser tab".
WORKBENCH_PROBE = r"""
(() => {
  const body = document.body;
  const classes = body ? String(body.className || '') : '';
  const hasWorkbench = Boolean(document.querySelector('.monaco-workbench'));
  const api = Boolean(window.vscode || window._VSCODE_);
  return {
    title: document.title,
    url: String(location.href),
    hasWorkbench: hasWorkbench,
    bodyClasses: classes.slice(0, 300),
    vscodeApiPresent: api,
    userAgent: navigator.userAgent,
    isElectron: /Electron/i.test(navigator.userAgent),
    devicePixelRatio: window.devicePixelRatio || 1,
    viewport: {w: window.innerWidth, h: window.innerHeight}
  };
})()
"""


class CdpClient:
    """One WebSocket connection to one page target."""

    def __init__(self, ws_url: str, *, timeout: float = 20.0) -> None:
        assert_loopback(ws_url)
        self.ws_url = ws_url
        self.timeout = timeout
        self._ws = None
        self._next_id = 1

    # -- transport ---------------------------------------------------------

    def connect(self) -> None:
        try:
            from websockets.sync.client import connect  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment guard
            raise CdpError("CDP requires the 'websockets' package (pip install websockets)") from exc
        try:
            self._ws = connect(self.ws_url, open_timeout=self.timeout, max_size=64 * 1024 * 1024)
        except Exception as exc:
            raise CdpError(f"CDP websocket connect failed: {exc}") from exc

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise CdpError("not connected to CDP")
        request_id = self._next_id
        self._next_id += 1
        payload = {"id": request_id, "method": method, "params": params or {}}
        self._ws.send(json.dumps(payload))
        budget = timeout if timeout is not None else self.timeout
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            remaining = max(0.5, deadline - time.monotonic())
            try:
                raw = self._ws.recv(timeout=remaining)
            except TimeoutError:
                break
            message = json.loads(raw)
            if message.get("id") != request_id:
                continue  # an event frame, not our reply
            if "error" in message:
                raise CdpError(f"CDP {method} failed: {message['error']}")
            return message.get("result") or {}
        raise CdpError(f"CDP {method} timed out after {budget}s")

    # -- conveniences ------------------------------------------------------

    def evaluate(self, expression: str, *, await_promise: bool = False, timeout: float | None = None) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
                "userGesture": False,
            },
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            text = str((details.get("exception") or {}).get("description") or details.get("text") or "evaluate failed")
            raise CdpError(f"renderer evaluate failed: {text[:500]}")
        return (result.get("result") or {}).get("value")

    def screenshot(self) -> str:
        result = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        data = result.get("data") or ""
        if not data:
            raise CdpError("Page.captureScreenshot returned no data")
        return data

    def dispatch_ctrl_chord(self, key: str, code: str, windows_virtual_key: int) -> None:
        """Send a real Ctrl+<key> chord to the actual renderer (UI action)."""
        base = {
            "modifiers": 2,  # Ctrl
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": windows_virtual_key,
            "nativeVirtualKeyCode": windows_virtual_key,
        }
        self.call("Input.dispatchKeyEvent", {"type": "keyDown", **base})
        self.call("Input.dispatchKeyEvent", {"type": "keyUp", **base})
