"""Lazy tools for read-only capabilities supplied by the Code OSS workbench."""
from __future__ import annotations

import json
import socket
import urllib.parse

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


def _probe_preview_target(url: str, timeout: float = 2.0) -> dict[str, object]:
    """Cheap reachability probe for a preview.open URL target.

    The desktop opens the window unconditionally, so the engine is the only
    side that can check whether the framed dev server actually answers before
    telling the agent "opened". A TCP connect is the signal that matters (a
    compile-broken server still answers HTTP; a dead one refuses the socket),
    and it stays fast enough to run inline in a tool call. Never raises.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return {"reachable": False, "detail": f"unparseable URL: {url!r}"}
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"reachable": False, "detail": f"not a probeable http(s) URL: {url!r}"}
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # Dev servers bind 127.0.0.1 and advertise "localhost" (or the reverse);
    # try the literal host first, then the loopback twin.
    hosts = [parsed.hostname]
    if parsed.hostname == "localhost":
        hosts.append("127.0.0.1")
    elif parsed.hostname == "127.0.0.1":
        hosts.append("localhost")
    for host in hosts:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return {"reachable": True, "host": host, "port": port}
        except OSError:
            continue
    return {
        "reachable": False,
        "detail": f"nothing is listening on {parsed.hostname}:{port} — "
        "the preview window opened, but the dev server behind it is down. "
        "Start/restart it (background), then call preview.open again.",
    }


@tool
def discover_host_capabilities(query: str, config: RunnableConfig) -> str:
    """Discover relevant read-only native editor capabilities.

    Returns compact availability metadata only. Use before invoking native
    diagnostics, symbols, references, editor context, search, SCM, or trust.
    An empty query lists all currently published read-only capabilities.
    """
    from src.runtime.host_capabilities import host_capability_broker

    session_id = str(config["configurable"].get("thread_id") or "default")
    items = host_capability_broker.discover(session_id, query)
    if not items:
        return "No matching native workbench capabilities are currently published."
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


@tool
def invoke_host_capability(
    capability_id: str, arguments: dict, config: RunnableConfig,
) -> str:
    """Invoke one published read-only native Code OSS capability.

    Allowed first-stage capabilities are workspace trust, active editor/dirty
    context, diagnostics, symbols, definitions, references, bounded workspace
    search, SCM state, and preview.open (opens the CrusorAI Preview window on
    the user's screen; optional `url` argument frames that URL, e.g. the dev
    server you just started — use it when the user asks to "show", "open" or
    "preview" the running app in the IDE). Mutation, execution, secrets,
    extension tools, and MCP tools are intentionally unavailable through this
    operation.

    For preview.open with a `url`, the receipt carries `target_reachable`:
    when it is false the window is open but shows nothing — start or repair
    the dev server FIRST, then invoke preview.open again. Do not report
    success to the user while `target_reachable` is false.
    """
    from src.runtime.host_capabilities import host_capability_broker

    configurable = config["configurable"]
    receipt = host_capability_broker.request(
        session_id=str(configurable.get("thread_id") or "default"),
        workspace=str(configurable.get("workspace") or "."),
        capability_id=capability_id,
        arguments=dict(arguments or {}),
    )
    # preview.open verification: the window opens unconditionally on the
    # desktop, so an unconditional {opened: true} taught the agent to stop
    # there while the framed app was down (white window, "reload broken").
    if capability_id == "preview.open":
        url = arguments.get("url")
        if isinstance(url, str) and url.strip():
            receipt["target_reachable"] = _probe_preview_target(url.strip())
        else:
            receipt["target_reachable"] = {
                "reachable": None,
                "detail": "no url argument — the window frames its own resolved target; "
                    "verify via the window's state chip, or re-invoke with an explicit url to probe it",
            }
    return json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), default=str)


@tool
def open_preview(url: str, config: RunnableConfig) -> str:
    """Open the live interactive Crusor Preview tab/window for the user.

    ALWAYS call this whenever you start or build any web application or dev server (e.g. Next.js, Vite, React)
    so the user can immediately see, interact with, and visually edit the running page in the IDE.
    Arguments:
      url: The local URL where the app is listening (e.g. 'http://localhost:3000' or 'http://localhost:5173').
    """
    return invoke_host_capability.func("preview.open", {"url": url}, config)


HOST_TOOLS = [discover_host_capabilities, invoke_host_capability, open_preview]
