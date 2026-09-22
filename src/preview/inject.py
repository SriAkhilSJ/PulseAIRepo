"""Crusor Preview — HTML injection for the inspect-and-fix overlay.

The preview window frames the UI the agent built. That document lives on an origin we do not
control (a dev server on localhost, or a static file out of the workspace), so the overlay cannot
be pushed into it from the parent frame — cross-origin documents are opaque. The honest way in is
**server-side injection**: the Crusor preview proxy (:mod:`src.preview.server`) rewrites the HTML
on the way through and adds the overlay script, after which the overlay and the preview window
talk over ``postMessage`` (which needs no shared origin).

Two things are injected, and nothing else:

``<base href="{proxy-prefix}/">``
    so every relative *and* root-relative subresource stays under the proxy prefix. The proxy
    forwards any path under that prefix to the target origin, which means asset URLs, lazy chunks
    and API calls all resolve without rewriting a single one of them. Skipped when the document
    already declares a base.

``<script src="…/crusor-preview-overlay.js">``
    the overlay itself, dependency-free classic JS, mounted as soon as ``documentElement`` exists.

Known limits (deliberate, not accidental):
* a target page that sets its own CSP meta is loosened only as far as our script needs;
* ``X-Frame-Options`` / CSP ``frame-ancestors`` are dropped from the *response headers* by the
  proxy — the browser enforces framing on headers, not on HTML;
* JS-level frame busters (``if (top !== self) top.location = …``) are not rewritten: patching
  arbitrary page JS with a regex is how previews get silently corrupted;
* HMR websockets are not proxied. The preview is for looking and clicking, not for hot-reload
  fidelity — use Reload after the agent lands a fix.

Pure stdlib, pure functions — pinned by ``src/tests/test_preview_inject.py``.
"""
from __future__ import annotations

import re
from html import escape
from typing import Final

__all__ = [
    "INJECT_MARKER",
    "has_overlay",
    "inject_overlay",
    "insert_base",
    "relax_csp_meta",
]

#: Idempotency marker. Injection must survive being applied twice (a reload of an already
#: proxied document, or a page that includes its own built copy).
INJECT_MARKER: Final = "crusor-preview-overlay"

# Requires a quoted href: a page whose COMMENT mentions "<base href>" (very common in
# agent-written HTML, and in our own fixtures) must not be mistaken for one that has it.
_BASE_TAG = re.compile(r"<base\s[^>]*href\s*=\s*[\"'][^\"']*[\"'][^>]*>", re.IGNORECASE)
_HEAD_OPEN = re.compile(r"<head[^>]*>", re.IGNORECASE)
_HTML_OPEN = re.compile(r"<html[^>]*>", re.IGNORECASE)
_META_CSP = re.compile(
    r'<meta[^>]+http-equiv\s*=\s*["\']?Content-Security-Policy["\']?[^>]*>',
    re.IGNORECASE,
)
_FIRST_SCRIPT = re.compile(r"<script[\s>]", re.IGNORECASE)


def has_overlay(html: str) -> bool:
    """True when the overlay is already present (inject is idempotent)."""
    return INJECT_MARKER in (html or "")


def insert_base(html: str, href: str) -> str:
    """Insert ``<base href>`` as the first child of ``<head>`` when the document has none.

    Without it, a page served from the proxy origin resolves ``assets/app.js`` and
    ``/api/data`` against the proxy instead of the target — the classic blank-preview failure.
    """
    if not html or not href:
        return html
    if _BASE_TAG.search(html):
        return html
    tag = f'<base href="{escape(href, quote=True)}" data-crusor-preview-base />'
    match = _HEAD_OPEN.search(html)
    if match:
        return html[: match.end()] + tag + html[match.end():]
    match = _HTML_OPEN.search(html)
    if match:
        return html[: match.end()] + f"<head>{tag}</head>" + html[match.end():]
    return f"<head>{tag}</head>" + html


def relax_csp_meta(html: str, *, script_src: str) -> str:
    """Widen a target page's own CSP meta just enough for the injected overlay.

    A dev-server page may ship ``script-src 'self'``; our script arrives from the proxy origin and
    would be refused. We append the proxy origin (never ``'unsafe-inline'``) to ``script-src`` and
    leave every other directive exactly as the project wrote it.
    """
    if not html or "<meta" not in html.lower():
        return html

    def patch(match: re.Match[str]) -> str:
        tag = match.group(0)
        content = re.search(r'content\s*=\s*"([^"]*)"|content\s*=\s*\'([^\']*)\'', tag, re.IGNORECASE)
        if not content:
            return tag
        policy = content.group(1) or content.group(2) or ""
        directives = [d.strip() for d in policy.split(";") if d.strip()]
        names = [d.split()[0].lower() for d in directives]
        if "script-src" in names:
            directives = [
                (d + " " + script_src) if d.split()[0].lower() == "script-src" and script_src not in d else d
                for d in directives
            ]
        else:
            directives.append(f"script-src {script_src}")
        patched = "; ".join(directives)
        return tag[: content.start(1) if content.group(1) is not None else content.start(2)] + patched + tag[
            content.end(1) if content.group(1) is not None else content.end(2):
        ]

    return _META_CSP.sub(patch, html, count=1)


def inject_overlay(
    html: str,
    *,
    overlay_src: str,
    base_href: str | None = None,
    script_origin: str | None = None,
    config: dict | None = None,
) -> str:
    """Inject the overlay (and, optionally, a ``<base>``) into an HTML document.

    ``overlay_src``    URL of ``crusor-preview-overlay.js`` as the framed page sees it.
    ``base_href``      proxy prefix to install as ``<base href>`` (``None`` keeps the document's).
    ``script_origin``  origin to append to an existing CSP ``script-src`` (``None`` = no CSP edit).
    ``config``         small JSON blob handed to the overlay before it boots (target label,
                       session id). Never contains secrets: it is visible in the page.
    """
    if not html:
        return html
    if not has_overlay(html):
        boot = ""
        if config:
            import json

            boot = (
                f'<script id="{INJECT_MARKER}-config" type="application/json">'
                + json.dumps(config, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
                + "</script>"
            )
        script = (
            f'{boot}<script id="{INJECT_MARKER}" src="{escape(overlay_src, quote=True)}" '
            'data-crusor-preview="1" defer></script>'
        )
        match = _HEAD_OPEN.search(html)
        if match:
            html = html[: match.end()] + script + html[match.end():]
        else:
            match = _FIRST_SCRIPT.search(html)
            if match:
                html = html[: match.start()] + script + html[match.start():]
            else:
                match = _HTML_OPEN.search(html)
                html = (html[: match.end()] + script + html[match.end():]) if match else script + html
    if base_href:
        html = insert_base(html, base_href)
    if script_origin:
        html = relax_csp_meta(html, script_src=script_origin)
    return html


def is_html(content_type: str | None, body: bytes | None = None) -> bool:
    """Should this response be treated as an injectable document?"""
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in {"text/html", "application/xhtml+xml"}:
        return True
    if ctype and ctype != "application/octet-stream":
        return False
    # No usable content type (some dev servers omit it for .html): sniff the first bytes.
    head = (body or b"")[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")
