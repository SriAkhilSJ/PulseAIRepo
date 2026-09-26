"""Crusor Preview — local preview proxy (stdlib only).

Why a proxy exists at all
-------------------------
The Preview window frames the UI the agent built. To let the user *click an element and describe a
fix*, the inspect overlay has to run inside that document — and a cross-origin frame is opaque to
its parent, so the overlay cannot be pushed in from the workbench. The proxy is the seam that
makes injection possible for **any** target:

* ``kind="url"``  — a dev server the agent started (``http://localhost:5173``); responses are
  fetched and HTML documents are rewritten on the way through (:mod:`src.preview.inject`);
* ``kind="file"`` — a static ``.html`` file the agent wrote in the workspace, served straight from
  disk with the same injection. No dev server, no build step, no ``file://`` restrictions.

Everything under one capability token, on loopback, with framing headers stripped so the workbench
can host it.

Safety rails (all enforced here, not by convention)
---------------------------------------------------
* a random per-target token is required on every proxied path — an unguessable URL is the only
  thing standing between a browser tab and the workspace;
* ``url`` targets must resolve to loopback/link-local/private hosts unless ``allow_remote`` is set;
* ``file`` targets are confined to the workspace root (resolved, then prefix-checked, so ``..`` and
  symlink escapes are rejected);
* only ``GET``/``HEAD`` are proxied, and the proxy never follows a redirect off-host;
* registration is gated by a per-run **secret** (``--secret``/``--endpoint-session`` generates one).
  The preview window is served from the app's own origin, which in Chromium is *opaque*
  (``vscode-file://``), so its ``fetch`` to this proxy is cross-origin and needs CORS. Answering CORS
  is what makes ``Access-Control-Allow-Origin: *`` necessary, and ``*`` is what makes a secret
  necessary: without it, any page in the user's browser could register a target and then read files
  out of the workspace through the proxy. The secret never leaves the machine — it is published in the
  ``0600`` endpoint file (src/preview/endpoint.py) and handed to the preview window in its URL;
* upstream ``X-Frame-Options`` / ``Content-Security-Policy`` are dropped (they exist to stop
  *third parties* framing a site; this is the developer's own machine and their own dev server).

Run it standalone for a smoke test::

    python -m src.preview.server --workspace . --url http://localhost:5173 --endpoint-session demo

then open ``http://127.0.0.1:8931/crusor-preview/ui/?target=/p/<token>/`` (the token is printed when
the target is registered) or point the IDE at the published endpoint file.
"""
from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Final, NamedTuple

from .endpoint import clear_endpoint, prune_stale, write_endpoint
from .inject import inject_overlay, is_html

__all__ = ["PreviewServer", "TargetSpec", "REPO_ROOT", "PREVIEW_ASSET_ROOT", "main"]

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
PREVIEW_ASSET_ROOT: Final = (
    REPO_ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai"
    / "browser" / "media" / "crusor-preview"
)
OVERLAY_ASSET: Final = "overlay/crusor-preview-overlay.js"

_UI_PREFIX = "/crusor-preview/ui/"
_OVERLAY_PATH = "/crusor-preview/overlay/crusor-preview-overlay.js"
_HEALTH_PATH = "/crusor-preview/health"
_TARGET_PATH = "/crusor-preview/target"
_PROXY_PREFIX = "/p/"

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade", "content-encoding", "content-length",
}
#: Framing blockers. Dropped on proxied responses; see module docstring.
_FRAMING_HEADERS = {"x-frame-options", "content-security-policy", "content-security-policy-report-only"}

_MAX_BODY = 24 * 1024 * 1024
_FETCH_TIMEOUT = 20.0


class _StopRedirects(urllib.request.HTTPRedirectHandler):
    """Return the 3xx to the caller instead of following it.

    ``urllib`` follows redirects by default, which for a preview proxy means silently proxying — and
    injecting a script into — whatever host the dev server points at next. A dev-server redirect that
    stays on the target origin is re-issued through the proxy prefix (so injection survives); one that
    leaves the origin is refused, with the reason.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, D102 - stdlib hook
        return None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_StopRedirects)


class TargetSpec(NamedTuple):
    """One registered preview target."""

    token: str
    kind: str            # "url" | "file"
    url: str             # upstream origin+path for kind="url"; absolute path for kind="file"
    label: str
    session_id: str
    created_at: float


def _is_local_host(host: str) -> bool:
    """Loopback / link-local / private only, unless the caller opts into remote targets."""
    if not host:
        return False
    if host.lower() in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            host = socket.gethostbyname(host)
            address = ipaddress.ip_address(host)
        except (OSError, ValueError):
            return False
    return bool(address.is_loopback or address.is_link_local or address.is_private)


class _PreviewHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server sized for a browser, not a script.

    ``HTTPServer`` listens with a backlog of 5. A real page pulls dozens of subresources in parallel
    through this proxy, and when the accept queue overflows the kernel answers with RST — which the
    browser reports as a failed asset, i.e. a page that renders half-styled for no visible reason.
    Measured: 300 simultaneous connections lost ~4 of them at backlog 5, none at 128.
    """

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


class PreviewServer:
    """Loopback HTTP server that frames agent-built UI with the inspect overlay injected.

    ``extra_handler`` is the one extension point: it is called before routing and returns ``True``
    when it answered the request. The preview lab and the tests use it to mount demo pages without
    touching production routing.
    """

    def __init__(
        self,
        workspace: Path | str,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        asset_root: Path | str = PREVIEW_ASSET_ROOT,
        allow_remote: bool = False,
        secret: str = "",
        extra_handler: Callable[[str, str, "PreviewRequestHandler"], bool] | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.asset_root = Path(asset_root).resolve()
        self.allow_remote = allow_remote
        #: Required on ``POST /crusor-preview/target``. Empty disables the check, which is only
        #: appropriate for a proxy that nothing else can reach (the tests bind an ephemeral
        #: loopback port); the CLI and the lab always set one.
        self.secret = secret
        self.extra_handler = extra_handler
        self._targets: dict[str, TargetSpec] = {}
        self._lock = threading.Lock()
        self._httpd = _PreviewHTTPServer((host, port), PreviewRequestHandler)
        # The handler reaches the server state through the httpd object it is given.
        self._httpd.preview = self  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------------------------

    @property
    def host(self) -> str:
        return str(self._httpd.server_address[0])

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    @property
    def origin(self) -> str:
        """A usable origin for this server. ``0.0.0.0``/``::`` are bind addresses, not hosts."""
        host = self.host
        if host in {"0.0.0.0", "::", ""}:
            host = "127.0.0.1"
        return f"http://{host}:{self.port}"

    def start(self) -> "PreviewServer":
        if self._thread and self._thread.is_alive():
            return self
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="crusor-preview-proxy", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def serve_forever(self) -> None:
        self.start()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:  # pragma: no cover - interactive
            self.stop()

    # -- targets ------------------------------------------------------------------------------

    def register_url(self, url: str, *, label: str = "", session_id: str = "") -> TargetSpec:
        """Register a running dev server as a preview target."""
        parsed = urllib.parse.urlsplit(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"not an http(s) URL: {url!r}")
        if not self.allow_remote and not _is_local_host(parsed.hostname):
            raise ValueError(f"refusing to proxy a non-local target: {parsed.hostname}")
        normalized = urllib.parse.urlunsplit(parsed._replace(fragment=""))
        return self._register(TargetSpec(
            token=secrets.token_urlsafe(16), kind="url", url=normalized,
            label=label or normalized, session_id=session_id, created_at=time.time(),
        ))

    def register_file(self, relpath: str, *, label: str = "", session_id: str = "") -> TargetSpec:
        """Register a workspace file (the agent's static HTML) as a preview target."""
        target = self.resolve_workspace_path(relpath)
        if not target.is_file():
            raise FileNotFoundError(f"no such workspace file: {relpath}")
        return self._register(TargetSpec(
            token=secrets.token_urlsafe(16), kind="file", url=str(target),
            label=label or relpath, session_id=session_id, created_at=time.time(),
        ))

    def _register(self, spec: TargetSpec) -> TargetSpec:
        with self._lock:
            self._targets[spec.token] = spec
        return spec

    def target(self, token: str) -> TargetSpec | None:
        with self._lock:
            return self._targets.get(token)

    def forget(self, token: str) -> None:
        with self._lock:
            self._targets.pop(token, None)

    def resolve_workspace_path(self, relpath: str) -> Path:
        """Confine a workspace-relative path; rejects escapes and symlink tricks."""
        cleaned = str(relpath or "").strip().lstrip("/\\")
        candidate = (self.workspace / cleaned).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents:
            raise PermissionError(f"path escapes the workspace: {relpath!r}")
        return candidate

    def proxied_url(self, spec: TargetSpec, path: str = "") -> str:
        """The URL the preview window should load for a target."""
        suffix = path.lstrip("/")
        return f"{self.origin}{_PROXY_PREFIX}{spec.token}/{suffix}"


class PreviewRequestHandler(BaseHTTPRequestHandler):
    """Routing for the preview proxy. Stdlib only; no framework, no dependency."""

    server_version = "CrusorPreview/1"
    protocol_version = "HTTP/1.1"

    # -- plumbing -----------------------------------------------------------------------------

    @property
    def preview(self) -> PreviewServer:
        return self.server.preview  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - stdlib signature
        if os.environ.get("CRUSORAI_PREVIEW_QUIET", "1") != "1":
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        # Every JSON reply is CORS-readable. That is safe precisely because the read is not a
        # capability on its own: registration needs the secret, and a proxied path needs its token.
        self._send(
            status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8", _cors_headers(self.headers.get("Origin")),
        )

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib signature
        """Answer the preflight the preview window's cross-origin registration triggers.

        Chromium preflights a ``POST`` carrying ``Content-Type: application/json`` and our secret
        header, from the app's opaque origin. Without this the browser never sends the real request,
        and the window can only report "could not register this target" -- which is exactly the
        failure this handler exists to prevent.
        """
        self.send_response(204)
        for key, value in _cors_headers(self.headers.get("Origin"), preflight=True).items():
            self.send_header(key, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _drain_request_body(self) -> None:
        """Consume a request body that this reply is not going to read.

        A body left in the socket followed by a close makes TCP send RST instead of FIN, and the client
        can then see ECONNRESET *after* a perfectly good response — measured as 5 failures in 300
        refusals under load, i.e. a flaky client for no reason the client can see. On a keep-alive
        connection the same leftover bytes corrupt the NEXT request. Either way the fix is the same:
        read it and throw it away before answering.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        remaining = min(max(length, 0), _MAX_BODY)
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            # The peer gave up mid-body: nothing left to drain, and the reply still needs to go out.
            pass

    def _authorised(self) -> bool:
        """Is this registration request allowed to change the proxy's state?"""
        expected = self.preview.secret
        if not expected:
            return True
        supplied = self.headers.get("X-Crusor-Preview-Secret") or ""
        return hmac.compare_digest(supplied, expected)

    def _text(self, status: int, message: str) -> None:
        self._send(status, message.encode("utf-8"), "text/plain; charset=utf-8")

    def request_origin(self) -> str:
        """The origin the BROWSER sees, which behind a reverse proxy is not our bind address.

        Injected asset URLs are root-relative so they survive any proxy rewrite; this is only
        needed for the CSP ``script-src`` we widen on a target page that ships its own policy.
        """
        forwarded_proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
        scheme = forwarded_proto or "http"
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
        if not host:
            host = urllib.parse.urlsplit(self.preview.origin).netloc
        return f"{scheme}://{host}"

    # -- routes -------------------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        self._route()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib signature
        self._route()

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        path = urllib.parse.urlsplit(self.path).path
        if path == _TARGET_PATH:
            self._register_target()
            return
        if self.preview.extra_handler and self.preview.extra_handler("POST", path, self):
            return
        self._drain_request_body()
        self._text(404, "not found")

    def _route(self) -> None:
        split = urllib.parse.urlsplit(self.path)
        path = split.path
        if self.preview.extra_handler and self.preview.extra_handler(self.command, path, self):
            return
        if path == _HEALTH_PATH:
            self._json(200, {
                "ok": True, "service": "crusor-preview", "workspace": str(self.preview.workspace),
                "targets": len(self.preview._targets),  # noqa: SLF001 - same module family
            })
            return
        if path == _OVERLAY_PATH:
            self._serve_asset(OVERLAY_ASSET, "application/javascript; charset=utf-8")
            return
        if path.startswith(_UI_PREFIX):
            rel = path[len(_UI_PREFIX):] or "index.html"
            self._serve_asset(rel, None)
            return
        if path.startswith(_PROXY_PREFIX):
            self._serve_proxied(path[len(_PROXY_PREFIX):], split.query)
            return
        if path in {"/", "/crusor-preview", "/crusor-preview/"}:
            body = (
                b"<!doctype html><meta charset=utf-8><title>Crusor Preview</title>"
                b'<body style="background:#1f1f1f;color:#f1ece8;font:13px system-ui;padding:24px">'
                b"<h3>Crusor Preview proxy</h3><p>Load the preview window at "
                b'<a style="color:#fab283" href="' + _UI_PREFIX.encode() + b'">' + _UI_PREFIX.encode() + b"</a>.</p>"
            )
            self._send(200, body, "text/html; charset=utf-8")
            return
        self._text(404, "not found")

    # -- handlers ------------------------------------------------------------------------------

    def _register_target(self) -> None:
        if not self._authorised():
            # Before the reply, not after: see _drain_request_body.
            self._drain_request_body()
            self._json(403, {
                "ok": False,
                "error": "preview registration requires the run secret",
                "hint": "the secret is published in the IDE's endpoint file "
                        "(~/.crusorai/preview/<session>.json) and passed to the preview window by the "
                        "workbench; a page that is not the IDE's own preview window does not have it",
            })
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"ok": False, "error": f"malformed JSON body: {exc}"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"ok": False, "error": "body must be an object"})
            return
        try:
            if payload.get("url"):
                spec = self.preview.register_url(
                    str(payload["url"]), label=str(payload.get("label") or ""),
                    session_id=str(payload.get("session_id") or ""),
                )
            elif payload.get("file"):
                spec = self.preview.register_file(
                    str(payload["file"]), label=str(payload.get("label") or ""),
                    session_id=str(payload.get("session_id") or ""),
                )
            else:
                self._json(400, {"ok": False, "error": "provide either 'url' or 'file'"})
                return
        except (ValueError, FileNotFoundError, PermissionError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        origin = self.request_origin()
        self._json(200, {
            "ok": True, "token": spec.token, "kind": spec.kind, "label": spec.label,
            # Root-relative: correct from the browser's own origin, whatever proxies it.
            "previewUrl": f"{_PROXY_PREFIX}{spec.token}/",
            "overlayUrl": _OVERLAY_PATH,
            "uiUrl": _UI_PREFIX,
            "origin": origin,
            "serverOrigin": self.preview.origin,
        })

    def _serve_asset(self, rel: str, content_type: str | None) -> None:
        root = self.preview.asset_root
        candidate = (root / rel).resolve()
        if root not in candidate.parents and candidate != root:
            self._text(403, "forbidden")
            return
        if not candidate.is_file():
            self._text(404, f"no such asset: {rel}")
            return
        body = candidate.read_bytes()
        self._send(200, body, content_type or _guess_type(candidate.name))

    def _serve_proxied(self, remainder: str, query: str) -> None:
        token, _, rest = remainder.partition("/")
        spec = self.preview.target(token)
        if spec is None:
            self._text(404, "unknown or expired preview target")
            return
        if spec.kind == "file":
            self._serve_workspace_file(spec, rest)
        else:
            self._serve_upstream(spec, rest, query)

    def _serve_workspace_file(self, spec: TargetSpec, rest: str) -> None:
        base = Path(spec.url).parent
        # Percent-decoded before it becomes a path: `%2e%2e%2f` is a traversal, not a filename, and the
        # workspace check below is the only thing that decides. NUL bytes are never a valid path.
        rel = urllib.parse.unquote(rest or Path(spec.url).name)
        if "\x00" in rel:
            self._text(400, "bad path")
            return
        try:
            candidate = (base / rel).resolve()
        except (OSError, ValueError):
            self._text(400, "bad path")
            return
        workspace = self.preview.workspace
        if workspace not in candidate.parents and candidate != workspace:
            self._text(403, "outside the workspace")
            return
        if not candidate.is_file():
            self._text(404, f"no such file: {rel}")
            return
        body = candidate.read_bytes()
        content_type = _guess_type(candidate.name)
        if len(body) <= _MAX_BODY and is_html(content_type, body):
            body = self._inject(body.decode("utf-8", "replace"), spec, rest).encode("utf-8")
            content_type = "text/html; charset=utf-8"
        self._send(200, body, content_type)

    def _serve_upstream(self, spec: TargetSpec, rest: str, query: str) -> None:
        base = urllib.parse.urlsplit(spec.url)
        target_path = urllib.parse.urljoin(base.path or "/", "/" + rest)
        upstream = urllib.parse.urlunsplit((base.scheme, base.netloc, target_path, query, ""))
        request = urllib.request.Request(upstream, headers={
            "User-Agent": "CrusorPreview/1",
            "Accept": self.headers.get("Accept", "*/*"),
            "Accept-Language": self.headers.get("Accept-Language", "en"),
        })
        try:
            with _opener().open(request, timeout=_FETCH_TIMEOUT) as response:  # noqa: S310 - loopback-only by policy
                body = response.read(_MAX_BODY + 1)
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                headers = {
                    key: value for key, value in response.headers.items()
                    if key.lower() not in _HOP_BY_HOP and key.lower() not in _FRAMING_HEADERS
                }
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400 and exc.headers and exc.headers.get("Location"):
                self._relay_redirect(spec, upstream, exc.code, exc.headers["Location"])
                return
            body = exc.read(_MAX_BODY) if exc.fp else b""
            status = exc.code
            content_type = (exc.headers or {}).get("Content-Type", "text/plain")
            headers = {"Content-Security-Policy": ""}
            headers.pop("Content-Security-Policy")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            self._json(502, {
                "ok": False, "error": f"preview target unreachable: {reason}", "target": spec.url,
                "hint": "is the dev server still running? Crusor can restart it.",
            })
            return
        if len(body) > _MAX_BODY:
            self._json(413, {"ok": False, "error": "preview response too large to inject"})
            return
        if is_html(content_type, body):
            body = self._inject(body.decode("utf-8", "replace"), spec, rest).encode("utf-8")
            content_type = "text/html; charset=utf-8"
            headers.pop("Content-Security-Policy", None)
        self._send(status, body, content_type or "application/octet-stream", headers)

    def _relay_redirect(self, spec: TargetSpec, upstream: str, code: int, location: str) -> None:
        """Keep the browser inside the proxy: same-origin hops get the prefix, off-origin hops stop."""
        base = urllib.parse.urlsplit(spec.url)
        target_origin = f"{base.scheme}://{base.netloc}"
        resolved = urllib.parse.urljoin(upstream, location)
        parsed = urllib.parse.urlsplit(resolved)
        if f"{parsed.scheme}://{parsed.netloc}" != target_origin:
            self._json(502, {
                "ok": False,
                "error": f"the preview target redirected off-origin: {resolved}",
                "target": spec.url,
                "hint": "Crusor Preview injects the inspect overlay into the page it serves, so it "
                        "stays on the target origin. Open the other URL directly if you need it.",
            })
            return
        # A Location is an absolute path on OUR origin, so it needs the prefix and nothing else: an
        # earlier version tacked on the depth-climbing segments the <base href> needs, and `/p/<tok>/../x`
        # normalises to `/p/x` in the browser -- an unknown token, and a 404 for a page that exists.
        rest = parsed.path.lstrip("/")
        new_location = f"{_PROXY_PREFIX}{spec.token}/" + rest + (f"?{parsed.query}" if parsed.query else "")
        self.send_response(code)
        self.send_header("Location", new_location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _inject(self, html: str, spec: TargetSpec, rest: str) -> str:
        # Root of THIS document, so relative and root-relative assets both stay under the prefix
        # of the target they belong to (a nested route like /docs/intro must climb back out).
        depth = rest.strip("/").count("/")
        base_href = f"{_PROXY_PREFIX}{spec.token}/" + ("../" * depth)
        return inject_overlay(
            html,
            overlay_src=_OVERLAY_PATH,
            base_href=base_href,
            script_origin=self.request_origin(),
            config={
                "target": spec.label, "kind": spec.kind, "session": spec.session_id,
                "proxy": self.preview.origin,
            },
        )


def _cors_headers(origin: str | None, *, preflight: bool = False) -> dict[str, str]:
    """CORS for the API endpoints.

    ``*`` rather than an allow-list because the IDE's preview window has an *opaque* origin
    (``vscode-file://`` sends ``Origin: null``), which an allow-list cannot distinguish from any
    sandboxed iframe on the internet. Capability, not origin, is what protects this server: a run
    secret for registration, a per-target token for reading a proxied page.
    """
    headers = {"Access-Control-Allow-Origin": "*", "Vary": "Origin"}
    if preflight:
        headers.update({
            "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
            "Access-Control-Allow-Headers": "content-type, x-crusor-preview-secret",
            "Access-Control-Max-Age": "600",
        })
    return headers


def _guess_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return {
        ".html": "text/html; charset=utf-8",
        ".htm": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".map": "application/json; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }.get(suffix, "application/octet-stream")


def main(argv: list[str] | None = None) -> int:
    """CLI used by the IDE (and by anyone debugging a preview) to run the proxy by hand.

    ``--endpoint-session`` publishes ``$CRUSORAI_HOME/preview/<session>.json`` (see
    :mod:`src.preview.endpoint`) so the workbench can find this server without being told a port or
    a token, and the file is removed on exit: a stale endpoint sends the IDE to a dead origin.
    """
    parser = argparse.ArgumentParser(prog="crusor-preview", description="Crusor Preview proxy")
    parser.add_argument("--workspace", default=".", help="workspace root that file targets are confined to")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8931, help="0 picks a free port")
    parser.add_argument("--url", help="register a dev-server URL as a preview target")
    parser.add_argument("--file", help="register a workspace HTML file as a preview target")
    parser.add_argument("--endpoint-session", help="publish the handshake file for this session id")
    parser.add_argument(
        "--secret", default="",
        help="required on target registration; 'auto' (the default with --endpoint-session) generates one",
    )
    parser.add_argument("--prune-endpoints", action="store_true", help="drop stale handshake files and exit")
    parser.add_argument("--allow-remote", action="store_true", help="permit non-local upstream targets")
    args = parser.parse_args(argv)

    if args.prune_endpoints:
        removed = prune_stale()
        print(f"pruned {len(removed)} stale endpoint file(s)")
        return 0

    secret = args.secret
    if secret == "auto" or (not secret and args.endpoint_session):
        secret = secrets.token_urlsafe(24)
    server = PreviewServer(
        args.workspace, host=args.host, port=args.port,
        allow_remote=args.allow_remote, secret=secret,
    ).start()
    print(f"Crusor Preview proxy on {server.origin}")
    print(f"  preview window : {server.origin}{_UI_PREFIX}")
    if args.url:
        spec = server.register_url(args.url, session_id=args.endpoint_session or "")
        print(f"  target (url)   : {server.proxied_url(spec)}")
    if args.file:
        spec = server.register_file(args.file, session_id=args.endpoint_session or "")
        print(f"  target (file)  : {server.proxied_url(spec)}")

    if args.endpoint_session:
        path = write_endpoint(
            args.endpoint_session, origin=server.origin, token="", workspace=server.workspace,
            secret=secret, extra={"port": server.port},
        )
        print(f"  endpoint file  : {path}")
        # The endpoint names the server, not a target: each target carries its own capability token,
        # so the endpoint file alone grants no access to any page. It does carry the registration
        # secret, which is why it is written 0600 and lives under the user's own runtime home.

    try:
        server.serve_forever()
    finally:
        if args.endpoint_session:
            clear_endpoint(args.endpoint_session)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
