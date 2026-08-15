# src/tools/browser_mcp.py
"""
Browser Tools — the agent's eyes (hermes browser_tool value).
================================================================

A lazy stdio MCP client over the globally-installed
`@modelcontextprotocol/server-puppeteer`. Exposes eight browser_* tools so
the agent can genuinely verify its own UI output:

    browser_navigate / browser_snapshot / browser_screenshot /
    browser_click / browser_type / browser_select / browser_hover /
    browser_evaluate

Why this exists (Test-2 retest, workspace_d): the D5 agent was TOLD to
"verify with the browser tools" but no browser tool was bound — the graph
shipped 22 tools and zero browser_* — so it faked verification with an
execute_code script that only printed instructions. A tool that exists and
runs a real browser is the only thing that closes that gap.

Design:
- Lazy: the MCP subprocess spawns on the first tool call, not at import.
- Long-lived: one stdio session on a daemon event-loop thread.
- Degenerate gracefully: any spawn/transport failure returns a clear error
  string to the model (D17 crash-net) instead of raising into the turn.
- Spawn is immune to the machine's broken npx/bin-links (LAB F9): we exec
  `node dist/index.js` directly via stdio stream, no npm shims involved.
"""

from __future__ import annotations

import asyncio
import base64
import os
import threading
import time

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

# mcp is imported LAZILY inside BrowserMCPSession._start (not at module
# import): on Windows the mcp package requires pywintypes (pywin32), and
# the whole engine must boot even when that optional stack is missing.
# The class docstring's "never raises into a turn" contract starts here.

# Globally-installed puppeteer MCP server. Keep the Windows lab default, but
# discover the standard Linux global-npm location so browser proof is not
# silently Windows-only. An explicit environment override always wins.
if os.name == "nt":
    _DEFAULT_SERVER_DIR = (
        r"C:\Users\Administrator\AppData\Roaming\npm"
        r"\node_modules\@modelcontextprotocol\server-puppeteer"
    )
    _DEFAULT_CACHE = r"D:\puppeteer-cache"
else:
    _DEFAULT_SERVER_DIR = "/usr/lib/node_modules/@modelcontextprotocol/server-puppeteer"
    _DEFAULT_CACHE = os.path.expanduser("~/.cache/puppeteer")
_SERVER_INDEX = os.environ.get(
    "PULSEAI_PUPPETEER_INDEX",
    os.path.join(_DEFAULT_SERVER_DIR, "dist", "index.js"),
)
_SERVER_DIR = os.path.dirname(os.path.dirname(_SERVER_INDEX))
_PUPPETEER_CACHE = os.environ.get("PUPPETEER_CACHE_DIR", _DEFAULT_CACHE)

_NAVIGATE_TIMEOUT = 180.0   # a first Next.js compile can take a while
_DEFAULT_TIMEOUT = 60.0


class BrowserMCPSession:
    """One stdio MCP session to the puppeteer server, driven from a
    background asyncio loop so sync tool wrappers can call it safely."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._agen = None
        self._ready = threading.Event()
        self._call_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._error: str | None = None

    # -- lifecycle ------------------------------------------------------

    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        with self._start_lock:
            if self._loop is not None:
                return
            loop = asyncio.new_event_loop()
            t = threading.Thread(
                target=loop.run_forever,
                name="browser-mcp-loop",
                daemon=True,
            )
            t.start()
            self._loop = loop
            self._thread = t

    def _start(self) -> None:
        self._ensure_loop()
        if self._session is not None:
            return

        # Lazy import — the mcp stack (and its Windows pywintypes
        # requirement) is optional; the engine must boot without it.
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def _go() -> None:
            params = StdioServerParameters(
                command="node",
                args=[_SERVER_INDEX],
                cwd=os.environ.get("PULSEAI_PUPPETEER_CWD", _SERVER_DIR),
                env={
                    **os.environ,
                    "PUPPETEER_CACHE_DIR": _PUPPETEER_CACHE,
                    # The MCP package defaults to headful mode when it is not
                    # running in Docker, which fails on headless Linux without
                    # an X server. Preserve explicit caller configuration.
                    "PUPPETEER_LAUNCH_OPTIONS": os.environ.get(
                        "PUPPETEER_LAUNCH_OPTIONS",
                        '{"headless":true}' if os.name != "nt" else "{}",
                    ),
                    # Server writes its rough HTML artifacts here; harmless.
                    "PUPPETEER_PROJECT_DIR": os.environ.get(
                        "PULSEAI_PUPPETEER_PROJECT_DIR", _SERVER_DIR
                    ),
                },
            )
            self._agen = stdio_client(params)
            read_stream, write_stream = await self._agen.__aenter__()
            self._session = ClientSession(read_stream, write_stream)
            await self._session.__aenter__()
            await self._session.initialize()

        fut = asyncio.run_coroutine_threadsafe(_go(), self._loop)
        try:
            fut.result(timeout=60.0)
        except Exception as exc:  # noqa: BLE001
            self._cleanup()
            self._error = (
                f"Browser unavailable: could not start the puppeteer MCP "
                f"server ({type(exc).__name__}: {exc}). Verify "
                f"@modelcontextprotocol/server-puppeteer is globally "
                f"installed and node is on PATH."
            )
        else:
            self._ready.set()

    def _cleanup(self) -> None:
        try:
            if self._session is not None:
                asyncio.run_coroutine_threadsafe(
                    self._session.__aexit__(None, None, None), self._loop
                ).result(timeout=5)
        except Exception:
            pass
        finally:
            self._session = None
        if self._agen is not None:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._agen.__aexit__(None, None, None), self._loop
                ).result(timeout=5)
            except Exception:
                pass
            self._agen = None

    # -- calls ----------------------------------------------------------

    def call_tool(self, name: str, args: dict, timeout: float) -> str:
        """Synchronously invoke a puppeteer_* tool. Never raises into the
        turn — returns an error string on any failure (D17 crash-net)."""
        with self._call_lock:
            if self._session is None:
                self._start()
            if self._session is None:
                return self._error or "Browser unavailable (start failed)."
            assert self._loop is not None

            async def _call() -> str:
                result = await self._session.call_tool(name, args)
                parts = []
                for block in getattr(result, "content", None) or []:
                    text = getattr(block, "text", None)
                    if text is not None:
                        parts.append(str(text))
                    data = getattr(block, "data", None)
                    if data is not None:
                        parts.append(_abbrev(data))
                return "\n".join(parts) or "(no output)"

            fut = asyncio.run_coroutine_threadsafe(_call(), self._loop)
            try:
                return fut.result(timeout=timeout)
            except asyncio.TimeoutError:
                return (
                    f"[browser:{name}] timed out after {int(timeout)}s — the "
                    f"page may still be loading; retry once or snapshot again."
                )
            except Exception as exc:  # noqa: BLE001
                return f"[browser:{name}] error: {type(exc).__name__}: {exc}"

    def shutdown(self) -> None:
        if self._session is None:
            return
        try:
            self._cleanup()
        except Exception:  # noqa: BLE001
            pass


_BROWSER = BrowserMCPSession()


def _abbrev(text: str) -> str:
    if len(text) <= 80:
        return text
    return f"<binary {len(text)} bytes>"


class _ServerUnavailable(Exception):
    pass


class _ToolError(Exception):
    pass


@tool
def browser_navigate(url: str, config: RunnableConfig) -> str:
    """Navigate the browser to a URL and wait for the page to load.

    Used to prove a running app actually renders. The result includes the
    page's current URL and its accessibility/text snapshot — if the page
    failed to serve (HTTP 500, route error, server down) that failure is
    visible here. Call browser_snapshot afterwards for the full text tree,
    then browser_screenshot for visual proof. For a dev server, navigate to
    the port the server reported (e.g. http://localhost:3000)."""
    out = _BROWSER.call_tool(
        "puppeteer_navigate",
        {"url": url},
        _NAVIGATE_TIMEOUT,
    )
    return _mark_status("browser_navigate", out)


@tool
def browser_snapshot(config: RunnableConfig) -> str:
    """Return what is currently rendered in the browser: URL, title, and
    the page's visible text. This is the agent's eyes — use it to confirm
    the UI actually rendered the expected content (empty state, typed
    message, streaming reply), not just that a server 'started'."""
    script = (
        "JSON.stringify({url: location.href, title: document.title, "
        "text: document.body ? document.body.innerText.slice(0, 12000) : ''})"
    )
    out = _BROWSER.call_tool("puppeteer_evaluate", {"script": script}, _DEFAULT_TIMEOUT)
    return _mark_status("browser_snapshot", out)


@tool
def browser_screenshot(name: str, config: RunnableConfig) -> str:
    """Capture a screenshot of the current page and save it to
    <workspace>/screenshots/<name>.png. Returns the saved relative path.
    Use after browser_snapshot to leave visual proof of what rendered."""
    out = _BROWSER.call_tool(
        "puppeteer_screenshot",
        {"encoded": True, "name": name or "page", "width": 1280, "height": 800},
        _DEFAULT_TIMEOUT,
    )
    uri = ""
    for line in out.splitlines():
        if line.startswith("data:image"):
            uri = line
            break
    if not uri:
        return _mark_status("browser_screenshot", out)
    try:
        b64 = uri.split(",", 1)[1]
        raw = base64.b64decode(b64)
        workspace = config["configurable"].get("workspace", ".")
        shot_dir = os.path.join(os.fspath(workspace), "screenshots")
        os.makedirs(shot_dir, exist_ok=True)
        safe = "".join(c for c in (name or "page") if c.isalnum() or c in "-_") or "page"
        path = os.path.join(shot_dir, f"{safe}.png")
        with open(path, "wb") as f:
            f.write(raw)
        from src.tools.visual_quality import analyze_screenshot, format_quality_receipt
        quality = analyze_screenshot(path)
        marker = "✅" if quality.get("passed") else "⚠️"
        return (
            f"{marker} Screenshot saved: {os.path.relpath(path, start=os.fspath(workspace))} "
            f"({len(raw)} bytes). {format_quality_receipt(quality)}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"[browser_screenshot] could not save image: {type(exc).__name__}: {exc}"


@tool
def browser_click(selector: str, config: RunnableConfig) -> str:
    """Click an element identified by a CSS selector on the current page."""
    return _mark_status(
        "browser_click", _BROWSER.call_tool("puppeteer_click", {"selector": selector}, _DEFAULT_TIMEOUT)
    )


@tool
def browser_type(selector: str, text: str, config: RunnableConfig) -> str:
    """Type text into an input field identified by a CSS selector. For
    React controlled inputs (e.g. a chat box) this fires proper input
    events so the app's state updates (hermes: the browser must behave like
    a real user)."""
    return _mark_status(
        "browser_type",
        _BROWSER.call_tool(
            "puppeteer_fill", {"selector": selector, "value": text}, _DEFAULT_TIMEOUT
        ),
    )


@tool
def browser_select(selector: str, value: str, config: RunnableConfig) -> str:
    """Select an option in a <select> dropdown on the current page."""
    return _mark_status(
        "browser_select",
        _BROWSER.call_tool("puppeteer_select", {"selector": selector, "value": value}, _DEFAULT_TIMEOUT),
    )


@tool
def browser_hover(selector: str, config: RunnableConfig) -> str:
    """Hover an element identified by a CSS selector on the current page."""
    return _mark_status(
        "browser_hover", _BROWSER.call_tool("puppeteer_hover", {"selector": selector}, _DEFAULT_TIMEOUT)
    )


@tool
def browser_evaluate(script: str, config: RunnableConfig) -> str:
    """Execute a JavaScript expression in the browser page context and
    return its result. Use for checks the other browser tools don't cover
    (e.g. read a React component's on-screen state, wait for an element)."""
    return _mark_status(
        "browser_evaluate",
        _BROWSER.call_tool("puppeteer_evaluate", {"script": script}, _DEFAULT_TIMEOUT),
    )


def _mark_status(name: str, out: str) -> str:
    """Prefix a live browser result (never fabricate one the model can't
    distinguish from its own memory — D17 crash-net discipline)."""
    return out


BROWSER_TOOLS = [
    browser_navigate,
    browser_snapshot,
    browser_screenshot,
    browser_click,
    browser_type,
    browser_select,
    browser_hover,
    browser_evaluate,
]