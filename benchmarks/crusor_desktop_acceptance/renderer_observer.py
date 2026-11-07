"""Renderer-side observability: identity, composer, console, screenshots.

All of this runs inside the ACTUAL Electron renderer over CDP. Nothing here
imitates renderer behaviour in Python: the DOM expression, the console hooks
and the key chord are executed by the real workbench JavaScript.

No prompt is typed and no turn is submitted by this module.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.crusor_desktop_acceptance.cdp_client import (
    CdpClient,
    CdpError,
    RENDERER_INSTRUMENTATION,
    WORKBENCH_PROBE,
    build_dom_snapshot_expression,
)

COMPOSER_SELECTOR = "textarea.crusorai-composer-input"
CRUSOR_PANEL_HINTS = (
    "[aria-label*='Crusor']",
    "[title*='Crusor']",
    "[id*='crusor']",
    "[class*='crusor']",
)


@dataclass
class RendererObservation:
    target: dict[str, Any] = field(default_factory=dict)
    workbench_ready: bool = False
    page_identity: dict[str, Any] = field(default_factory=dict)
    belongs_to_crusor: bool = False
    belongs_reason: str = ""
    composer: dict[str, Any] = field(default_factory=dict)
    instrumentation: dict[str, Any] = field(default_factory=dict)
    console: dict[str, Any] = field(default_factory=dict)
    screenshots: list[str] = field(default_factory=list)
    focus_attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "workbench_ready": self.workbench_ready,
            "page_identity": self.page_identity,
            "belongs_to_crusor": self.belongs_to_crusor,
            "belongs_reason": self.belongs_reason,
            "composer": self.composer,
            "instrumentation": self.instrumentation,
            "console": self.console,
            "screenshots": self.screenshots,
            "focus_attempts": self.focus_attempts,
        }


def page_belongs_to_crusor(probe: dict[str, Any], *, expected_name: str = "CrusorAI") -> tuple[bool, str]:
    """Decide from renderer-reported facts whether this is the real app."""
    if not isinstance(probe, dict) or not probe:
        return False, "workbench probe returned nothing"
    if not probe.get("hasWorkbench"):
        return False, "no .monaco-workbench root in the page"
    if not probe.get("isElectron"):
        return False, "navigator.userAgent is not Electron (this is not the desktop app)"
    url = str(probe.get("url") or "")
    if not url.startswith(("vscode-file:", "file:")):
        return False, f"page URL is not the app's local workbench ({url[:120]})"
    title = str(probe.get("title") or "")
    if expected_name.lower() in title.lower():
        return True, f"Electron workbench titled {title!r}"
    body = str(probe.get("bodyClasses") or "")
    if "crusor" in body.lower():
        return True, f"Electron workbench (branded body classes) titled {title!r}"
    return True, f"Electron local workbench titled {title!r} (brand not in title)"


def save_screenshot(client: CdpClient, path: Path) -> Path:
    data = client.screenshot()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(data))
    return path


def observe_composer(client: CdpClient) -> dict[str, Any]:
    return client.evaluate(build_dom_snapshot_expression(COMPOSER_SELECTOR)) or {
        "selector": COMPOSER_SELECTOR, "count": 0, "visible": False, "enabled": None, "text": None,
    }


def focus_crusor_panel(client: CdpClient, *, wait_s: float = 8.0) -> list[dict[str, Any]]:
    """Open the Crusor panel using the product's own UI affordances.

    Strategy 1: click an existing Crusor-labelled affordance in the DOM.
    Strategy 2: send the product's documented Ctrl+L chord (``crusorai.focus``).

    Both are real renderer interactions; neither types a prompt or submits.
    """
    attempts: list[dict[str, Any]] = []

    already = observe_composer(client)
    if int(already.get("count") or 0) > 0:
        attempts.append({"strategy": "already-open", "ok": True})
        return attempts

    # Strategy 1 — click a visible Crusor affordance if the workbench exposes one.
    click_expr = "(() => {" + (
        "const sels = %s;" % repr(list(CRUSOR_PANEL_HINTS)) +
        "for (const s of sels) {"
        "  const els = Array.from(document.querySelectorAll(s));"
        "  for (const el of els) {"
        "    const r = el.getBoundingClientRect();"
        "    if (r.width > 4 && r.height > 4 && r.x >= 0) {"
        "      try { el.click(); return {clicked: s, tag: el.tagName, label: (el.getAttribute('aria-label') || el.getAttribute('title') || '').slice(0,120)}; } catch (e) {}"
        "    }"
        "  }"
        "}"
        "return {clicked: null};"
        "})()"
    )
    try:
        clicked = client.evaluate(click_expr)
        attempts.append({"strategy": "dom-click", "result": clicked})
    except CdpError as exc:
        attempts.append({"strategy": "dom-click", "error": str(exc)})

    if _wait_for_composer(client, wait_s=2.0):
        attempts.append({"strategy": "dom-click", "ok": True})
        return attempts

    # Strategy 2 — product keybinding for crusorai.focus.
    try:
        client.dispatch_ctrl_chord("l", "KeyL", 76)
        attempts.append({"strategy": "ctrl+l", "result": "dispatched"})
    except CdpError as exc:
        attempts.append({"strategy": "ctrl+l", "error": str(exc)})

    ok = _wait_for_composer(client, wait_s=wait_s)
    attempts.append({"strategy": "ctrl+l", "ok": ok})
    return attempts


def _wait_for_composer(client: CdpClient, *, wait_s: float) -> bool:
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        snapshot = observe_composer(client)
        if int(snapshot.get("count") or 0) > 0:
            return True
        time.sleep(0.25)
    return False


def wait_for_workbench(client: CdpClient, *, timeout_s: float = 45.0) -> bool:
    """Wait until the renderer has actually built the workbench DOM.

    Chromium exposes the page target as soon as the document starts loading.
    Probing identity at that instant reads an empty title and no
    ``.monaco-workbench`` — which must never be mistaken for the real app.
    """
    deadline = time.monotonic() + timeout_s
    expression = (
        "(() => { const wb = document.querySelector('.monaco-workbench');"
        " return Boolean(wb) && document.readyState !== 'loading'; })()"
    )
    while time.monotonic() < deadline:
        try:
            if client.evaluate(expression) is True:
                return True
        except CdpError:
            pass
        time.sleep(0.25)
    return False


def observe_renderer(client: CdpClient, *, expected_name: str = "CrusorAI", screenshot_dir: Path | None = None) -> RendererObservation:
    observation = RendererObservation()

    observation.workbench_ready = wait_for_workbench(client)
    probe = client.evaluate(WORKBENCH_PROBE) or {}
    observation.page_identity = probe if isinstance(probe, dict) else {"raw": probe}
    observation.belongs_to_crusor, observation.belongs_reason = page_belongs_to_crusor(
        observation.page_identity, expected_name=expected_name
    )

    try:
        observation.instrumentation = client.evaluate(RENDERER_INSTRUMENTATION) or {}
    except CdpError as exc:
        observation.instrumentation = {"installed": False, "error": str(exc)}

    observation.focus_attempts = focus_crusor_panel(client)
    observation.composer = observe_composer(client)

    if screenshot_dir is not None:
        try:
            path = save_screenshot(client, screenshot_dir / "renderer-workbench.png")
            observation.screenshots.append(str(path))
        except CdpError:
            pass

    observation.console = collect_console(client)
    return observation


def collect_console(client: CdpClient) -> dict[str, Any]:
    """Drain the renderer-side console/exception buckets."""
    expr = r"""
    (() => {
      const obs = window.__crusoraiObs;
      if (!obs) { return {installed: false}; }
      const take = (bucket) => bucket.slice();
      const out = {
        installed: true,
        installedAt: obs.installedAt,
        errors: take(obs.errors),
        rejects: take(obs.rejects),
        consoleErrors: take(obs.consoleErrors),
        consoleWarns: take(obs.consoleWarns),
      };
      obs.errors.length = 0; obs.rejects.length = 0;
      obs.consoleErrors.length = 0; obs.consoleWarns.length = 0;
      return out;
    })()
    """
    try:
        return client.evaluate(expr) or {"installed": False}
    except CdpError as exc:
        return {"installed": False, "error": str(exc)}
