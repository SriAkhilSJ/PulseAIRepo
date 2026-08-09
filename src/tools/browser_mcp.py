"""Puppeteer MCP browser tools — the agent's eyes (hermes-style browser_tool).

Spawns the @modelcontextprotocol/server-puppeteer subprocess lazily on first
use and speaks MCP JSON-RPC over stdio, exposing a small set of browser
tools (navigate / snapshot / screenshot / click / type / select / hover /
eval). Degrades gracefully: if the server or a browser binary is missing,
the tools return an explanatory string instead of raising, so the agent can
adapt.

The server is spawned via `node <path-to-dist/index.js>` directly — never
through `npx` — so it is immune to the machine's `bin-links=false` problem.
"""

import functools
import json
import shutil
import subprocess
import threading
import uuid

from langchain_core.tools import tool

_SERVER_JS = (
    r"C:\Users\Administrator\AppData\Roaming\npm\node_modules"
    r"\@modelcontextprotocol\server-puppeteer\dist\index.js"
)

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_buf = b""
_started = False

# Accessibility-ish snapshot of the current page (the installed puppeteer
# server has no snapshot tool, so we synthesize one via evaluate).
_SNAPSHOT_JS = """(() => {
  const title = document.title;
  const text = (document.body ? document.body.innerText : '').slice(0, 3000);
  const links = [...document.querySelectorAll('a')].map(a => a.href).slice(0, 10);
  const buttons = [...document.querySelectorAll('button')].map(
    b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(0, 10);
  const inputs = [...document.querySelectorAll('input, textarea, select')].map(
    i => i.tagName.toLowerCase() + (i.name || i.id || '')).slice(0, 10);
  return JSON.stringify({ title, text, links, buttons, inputs });
})()"""


def _available() -> str | None:
    """Return None if usable, else a human reason why not."""
    import os
    if not os.path.exists(_SERVER_JS):
        return (
            "browser tools unavailable: puppeteer MCP server not found at "
            f"{_SERVER_JS} (install: npm i -g @modelcontextprotocol/server-puppeteer)"
        )
    if shutil.which("node") is None:
        return "browser tools unavailable: node not found on PATH"
    return None


def _send(payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8") + b"\n"
    assert _proc is not None and _proc.stdin is not None
    _proc.stdin.write(data)
    _proc.stdin.flush()


def _read_frame(timeout: float = 60.0) -> dict | None:
    """Read one JSON-RPC frame from stdout, handling chunked reads."""
    global _buf
    assert _proc is not None and _proc.stdout is not None
    import time
    deadline = time.time() + timeout
    while True:
        while b"\n" in _buf:
            line, _buf = _buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                return json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue  # partial/corrupt frame — skip
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError("browser MCP server timed out")
        chunk = _proc.stdout.read1(4096)
        if not chunk:
            raise ConnectionError("browser MCP server closed stdout")
        _buf += chunk


def _request(payload: dict, timeout: float = 120.0) -> dict:
    _send(payload)
    rid = payload["id"]
    while True:
        frame = _read_frame(timeout)
        if frame.get("id") == rid:
            if "error" in frame:
                raise RuntimeError(f"browser MCP error: {frame['error']}")
            return frame
        # ignore notifications / other ids


def _start() -> None:
    global _proc, _buf, _started
    with _lock:
        if _started and _proc and _proc.poll() is None:
            return
        reason = _available()
        if reason:
            raise RuntimeError(reason)
        _proc = subprocess.Popen(
            [shutil.which("node") or "node", _SERVER_JS],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        _buf = b""
        for proto in ("2024-11-05", "2025-03-26", "2025-06-18"):
            try:
                _request({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": proto,
                        "capabilities": {},
                        "clientInfo": {"name": "pulseai", "version": "1.0"},
                    },
                }, timeout=20.0)
                break
            except Exception:
                continue
        else:
            raise RuntimeError("browser MCP server rejected all protocol versions")
        _send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        _started = True


def _call_tool(name: str, args: dict | None = None) -> str:
    _start()
    resp = _request({
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4().int)[:12],
        "method": "tools/call",
        "params": {"name": name, "arguments": args or {}},
    })
    result = resp.get("result") or {}
    if result.get("isError"):
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        return f"browser tool error: {'\n'.join(texts)}"
    return "\n".join(
        c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"
    )


def _browser_tool(fn):
    """Expose `fn` as a langchain tool that degrades to an explanatory
    message on any failure instead of raising."""
    @tool
    @functools.wraps(fn)  # keeps the real signature (url, selector, ...)
    def _wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            return f"browser tool failed: {exc}"
    return _wrapped


@_browser_tool
def browser_navigate(url: str) -> str:
    """Open a URL in the browser. USE to view a running frontend (dev
    server, localhost) or any web page the agent needs to see. Then use
    browser_snapshot or browser_screenshot to inspect the result."""
    return _call_tool("puppeteer_navigate", {"url": url})


@_browser_tool
def browser_snapshot() -> str:
    """Return the current page as a text summary (title, visible text,
    links, buttons, inputs). USE after browser_navigate to read what the
    page shows without needing a screenshot."""
    return _call_tool("puppeteer_evaluate", {"script": _SNAPSHOT_JS})


@_browser_tool
def browser_screenshot(name: str = "page") -> str:
    """Save a PNG screenshot of the current page to ./screenshots/<name>.png
    and return the path. USE to visually verify a rendered UI; then read
    the file. Optional: selector, width, height."""
    return _call_tool("puppeteer_screenshot", {"name": name})


@_browser_tool
def browser_click(selector: str) -> str:
    """Click the element matching the CSS selector (e.g. '#submit')."""
    return _call_tool("puppeteer_click", {"selector": selector})


@_browser_tool
def browser_type(selector: str, text: str) -> str:
    """Fill the input matching the CSS selector with the given text."""
    return _call_tool("puppeteer_fill", {"selector": selector, "value": text})


@_browser_tool
def browser_select_option(selector: str, value: str) -> str:
    """Select an option by value in a <select> matching the CSS selector."""
    return _call_tool("puppeteer_select", {"selector": selector, "value": value})


@_browser_tool
def browser_hover(selector: str) -> str:
    """Hover over the element matching the CSS selector (e.g. to trigger a
    Spotlight or reveal effect)."""
    return _call_tool("puppeteer_hover", {"selector": selector})


@_browser_tool
def browser_evaluate(script: str) -> str:
    """Run JavaScript in the page and return its value. USE for checks the
    DOM summary cannot show (computed styles, fetch calls, app state).
    Prefer read-only expressions that return JSON-serializable values."""
    return _call_tool("puppeteer_evaluate", {"script": script})


BROWSER_TOOLS = [
    browser_navigate,
    browser_snapshot,
    browser_screenshot,
    browser_click,
    browser_type,
    browser_select_option,
    browser_hover,
    browser_evaluate,
]
