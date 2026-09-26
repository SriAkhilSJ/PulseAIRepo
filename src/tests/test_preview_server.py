"""Crusor Preview — the proxy, end to end over real sockets.

The proxy is the one component that cannot be exercised by unit-testing a pure function: it exists
to talk HTTP to a dev server the user is running. So these tests run two real servers on loopback —
a stub "dev server" and the preview proxy — and assert the properties the feature depends on:

* an HTML response arrives at the frame **with the overlay injected** (otherwise the preview renders
  but nothing is clickable);
* the target page's ``X-Frame-Options`` / CSP are dropped from the response (otherwise the frame is
  refused by the browser and the window shows nothing at all);
* the capability token is required, and workspace file targets cannot escape the workspace (the
  preview is reachable from a browser; it must not become a file-read gadget);
* a dev server that has gone away produces a legible 502 with a hint, not a blank frame.

``urllib`` rather than ``requests``: the runtime is stdlib-only by policy, and these tests keep the
proxy honest by using the same constraint.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.preview.server import OVERLAY_ASSET, PreviewServer

INDEX_HTML = (
	"<!DOCTYPE html><html><head><title>agent-built</title>"
	"<link rel=stylesheet href=/assets/app.css></head>"
	"<body><h1>Agent built this</h1><script src=/assets/app.js></script></body></html>"
)


class StubDevServer(BaseHTTPRequestHandler):
	"""Stands in for `vite`/`next dev`: HTML with framing headers a dev server would not normally send."""

	protocol_version = "HTTP/1.1"
	hits: list[str] = []

	def log_message(self, fmt, *args):  # noqa: A003, ANN001 - stdlib signature
		pass

	def do_GET(self) -> None:  # noqa: N802 - stdlib signature
		StubDevServer.hits.append(self.path)
		if self.path.startswith("/assets/app.css"):
			body = b"h1{color:red}"
			self.send_response(200)
			self.send_header("Content-Type", "text/css")
		elif self.path.startswith("/assets/app.js"):
			body = b"console.log('hi')"
			self.send_response(200)
			self.send_header("Content-Type", "application/javascript")
		elif self.path.startswith("/redirects-inside"):
			self.send_response(302)
			self.send_header("Location", "/assets/app.css")
			self.send_header("Content-Length", "0")
			self.end_headers()
			return
		elif self.path.startswith("/redirects-away"):
			self.send_response(302)
			self.send_header("Location", "https://example.com/")
			self.send_header("Content-Length", "0")
			self.end_headers()
			return
		else:
			body = INDEX_HTML.encode()
			self.send_response(200)
			self.send_header("Content-Type", "text/html; charset=utf-8")
			# The headers a framework dev server ships to stop being framed by strangers.
			self.send_header("X-Frame-Options", "DENY")
			self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		if self.command != "HEAD":
			self.wfile.write(body)


@pytest.fixture(scope="module")
def dev_server():
	httpd = ThreadingHTTPServer(("127.0.0.1", 0), StubDevServer)
	httpd.daemon_threads = True
	threading.Thread(target=httpd.serve_forever, daemon=True).start()
	yield f"http://127.0.0.1:{httpd.server_address[1]}"
	httpd.shutdown()
	httpd.server_close()


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> Path:
	root = tmp_path_factory.mktemp("preview-workspace")
	(root / "index.html").write_text(INDEX_HTML, encoding="utf-8")
	(root / "app.css").write_text("h1{}", encoding="utf-8")
	(root / "secret").mkdir()
	(root / "secret" / "keys.txt").write_text("nope", encoding="utf-8")
	return root


TEST_SECRET = "test-secret-not-a-real-one"


@pytest.fixture(scope="module")
def proxy(workspace: Path):
	# Runs WITH a secret, because that is how the CLI starts it (`--endpoint-session` generates one) and
	# the gate is the only thing standing between a web page and the workspace through this proxy.
	server = PreviewServer(workspace, host="127.0.0.1", port=0, secret=TEST_SECRET).start()
	yield server
	server.stop()


def get(url: str, *, timeout: float = 10.0):
	try:
		with urllib.request.urlopen(url, timeout=timeout) as response:
			return response.status, dict(response.headers), response.read()
	except urllib.error.HTTPError as exc:
		return exc.code, dict(exc.headers or {}), exc.read()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
	"""Observe a 3xx instead of consuming it — the redirect IS the behaviour under test here."""

	def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 - stdlib hook
		return None


def get_noredirect(url: str, *, timeout: float = 10.0):
	try:
		with urllib.request.build_opener(_NoRedirect).open(url, timeout=timeout) as response:
			return response.status, dict(response.headers), response.read()
	except urllib.error.HTTPError as exc:
		return exc.code, dict(exc.headers or {}), exc.read()


def post(url: str, payload: dict, *, timeout: float = 10.0, secret: str | None = None, origin: str | None = None):
	headers = {"Content-Type": "application/json"}
	if secret:
		headers["X-Crusor-Preview-Secret"] = secret
	if origin:
		headers["Origin"] = origin
	request = urllib.request.Request(url, method="POST", data=json.dumps(payload).encode(), headers=headers)
	try:
		with urllib.request.urlopen(request, timeout=timeout) as response:
			return response.status, json.loads(response.read().decode() or "{}")
	except urllib.error.HTTPError as exc:
		return exc.code, json.loads(exc.read().decode() or "{}")


def preflight(url: str, *, timeout: float = 10.0):
	"""Exactly what Chromium sends before the preview window's cross-origin registration POST."""
	request = urllib.request.Request(url, method="OPTIONS", headers={
		"Origin": "null",
		"Access-Control-Request-Method": "POST",
		"Access-Control-Request-Headers": "content-type,x-crusor-preview-secret",
	})
	try:
		with urllib.request.urlopen(request, timeout=timeout) as response:
			return response.status, dict(response.headers)
	except urllib.error.HTTPError as exc:
		return exc.code, dict(exc.headers or {})


def register(proxy: PreviewServer, **payload) -> dict:
	status, body = post(f"{proxy.origin}/crusor-preview/target", payload, secret=TEST_SECRET)
	assert status == 200, body
	return body


def test_health_reports_the_workspace(proxy: PreviewServer, workspace: Path) -> None:
	status, _, body = get(f"{proxy.origin}/crusor-preview/health")
	assert status == 200
	assert json.loads(body)["workspace"] == str(workspace)


def test_url_target_is_injected_and_framable(proxy: PreviewServer, dev_server: str) -> None:
	target = register(proxy, url=dev_server + "/", label="stub app")
	assert target["previewUrl"].startswith("/p/"), "root-relative so any proxy in front of us still works"

	status, headers, body = get(proxy.origin + target["previewUrl"])
	html = body.decode()
	assert status == 200
	assert "x-frame-options" not in {key.lower() for key in headers}, "the frame would be refused"
	assert "content-security-policy" not in {key.lower() for key in headers}
	assert 'id="crusor-preview-overlay"' in html
	assert "crusor-preview-overlay-config" in html
	assert '<base href="/p/' in html and 'data-crusor-preview-base' in html
	assert "Agent built this" in html, "the page itself is untouched"


def test_proxied_subresources_are_forwarded(proxy: PreviewServer, dev_server: str) -> None:
	target = register(proxy, url=dev_server + "/")
	prefix = target["previewUrl"]
	status, headers, body = get(proxy.origin + prefix + "assets/app.css")
	assert (status, headers["Content-Type"]) == (200, "text/css")
	assert body == b"h1{color:red}"
	status, headers, body = get(proxy.origin + prefix + "assets/app.js")
	assert status == 200 and body.startswith(b"console.log")
	assert b"crusor-preview-overlay" not in body, "only documents are rewritten"


def test_a_same_origin_redirect_stays_inside_the_proxy(proxy: PreviewServer, dev_server: str) -> None:
	# Relayed rather than followed: the browser re-requests through the prefix, so the next document
	# is injected too (a followed redirect would hand back the dev server's own origin, uninstrumented).
	target = register(proxy, url=dev_server + "/")
	status, headers, _ = get_noredirect(proxy.origin + target["previewUrl"] + "redirects-inside")
	assert status == 302
	location = headers["Location"]
	assert location.startswith("/p/"), location
	assert location.endswith("/assets/app.css"), location
	assert "/../" not in location, "a Location is an absolute path: no depth-climbing segments"

	# And the relayed hop really does serve the file, injected-or-not as appropriate.
	status, headers, body = get(proxy.origin + location)
	assert status == 200 and headers["Content-Type"].startswith("text/css")
	assert body == b"h1{color:red}"


def test_a_redirect_off_origin_is_refused_with_a_reason(proxy: PreviewServer, dev_server: str) -> None:
	# The preview injects a script into the page it serves; following the dev server to a third party
	# would silently instrument somebody else's site. Refuse, and say why in words the UI can show.
	target = register(proxy, url=dev_server + "/")
	status, _, body = get(proxy.origin + target["previewUrl"] + "redirects-away")
	assert status == 502
	payload = json.loads(body)
	assert "redirected off-origin" in payload["error"]
	assert "example.com" in payload["error"]
	assert payload["hint"]


def test_unknown_token_is_refused(proxy: PreviewServer) -> None:
	status, _, body = get(f"{proxy.origin}/p/not-a-real-token/")
	assert status == 404
	assert b"unknown" in body.lower() or b"expired" in body.lower()


def test_file_target_is_served_from_the_workspace_with_the_overlay(proxy: PreviewServer) -> None:
	target = register(proxy, file="index.html", label="workspace page")
	assert target["kind"] == "file"
	status, _, body = get(proxy.origin + target["previewUrl"])
	html = body.decode()
	assert status == 200
	assert 'id="crusor-preview-overlay"' in html
	assert "Agent built this" in html
	status, headers, body = get(proxy.origin + target["previewUrl"] + "app.css")
	assert status == 200 and headers["Content-Type"].startswith("text/css")


def test_file_targets_cannot_escape_the_workspace(proxy: PreviewServer) -> None:
	status, body = post(f"{proxy.origin}/crusor-preview/target", {"file": "../../etc/passwd"}, secret=TEST_SECRET)
	assert status == 400
	assert "workspace" in body["error"]
	status, body = post(f"{proxy.origin}/crusor-preview/target", {"file": "missing.html"}, secret=TEST_SECRET)
	assert status == 400

	# The deliberate boundary: a registered page may pull its own subresources from anywhere inside the
	# workspace (that is how a real page loads its assets), but never from outside it — and a traversal
	# disguised as an escape sequence is decoded before it is judged, not treated as a filename.
	target = register(proxy, file="index.html", label="workspace page")
	status, _, body = get(proxy.origin + target["previewUrl"] + "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd")
	assert status in {403, 404}, "traversal out of the workspace must be refused"
	assert b"root:" not in body
	status, _, body = get(proxy.origin + target["previewUrl"] + "app.css")
	assert status == 200, "a sibling inside the workspace is a normal subresource"


def test_remote_targets_are_refused_by_default(proxy: PreviewServer) -> None:
	status, body = post(f"{proxy.origin}/crusor-preview/target", {"url": "https://example.com/"}, secret=TEST_SECRET)
	assert status == 400
	assert "non-local" in body["error"]


def test_registration_validates_its_input(proxy: PreviewServer) -> None:
	status, body = post(f"{proxy.origin}/crusor-preview/target", {"url": "not-a-url"}, secret=TEST_SECRET)
	assert status == 400 and "http" in body["error"]
	status, body = post(f"{proxy.origin}/crusor-preview/target", {}, secret=TEST_SECRET)
	assert status == 400 and "url" in body["error"]
	status, body = post(f"{proxy.origin}/crusor-preview/target", {"file": "missing.html"}, secret=TEST_SECRET)
	assert status == 400 and "no such workspace file" in body["error"]


def test_a_dead_dev_server_produces_a_legible_error(proxy: PreviewServer) -> None:
	# Port 1 on loopback: nothing listens there, which is exactly the "user stopped the dev server"
	# case. The frame must be told why, in words, with the target named.
	target = register(proxy, url="http://127.0.0.1:1/", label="gone")
	status, _, body = get(proxy.origin + target["previewUrl"])
	assert status == 502
	payload = json.loads(body)
	assert "unreachable" in payload["error"]
	assert payload["hint"]


def test_overlay_and_window_assets_are_shipped_from_the_desktop_tree(proxy: PreviewServer) -> None:
	status, headers, body = get(f"{proxy.origin}/crusor-preview/overlay/crusor-preview-overlay.js")
	assert status == 200
	assert "javascript" in headers["Content-Type"]
	assert b"__crusorPreviewOverlay" in body

	for asset in ("", "preview.css", "preview.js"):
		status, _, body = get(f"{proxy.origin}/crusor-preview/ui/{asset}")
		assert status == 200, asset
		assert body, asset

	assert Path(OVERLAY_ASSET).name == "crusor-preview-overlay.js"


def test_asset_traversal_is_refused(proxy: PreviewServer) -> None:
	status, _, _ = get(f"{proxy.origin}/crusor-preview/ui/../../../package.json")
	assert status in {403, 404}


def test_preflight_answer_lets_the_preview_window_register(proxy: PreviewServer) -> None:
	"""Chromium preflights the window's registration POST (opaque origin, JSON body, custom header).

	Without a preflight answer the browser never sends the real request, and the preview window can
	only say "could not register this target" — the feature would look broken on first launch.
	"""
	status, headers = preflight(f"{proxy.origin}/crusor-preview/target")
	assert status in {200, 204}
	assert headers["Access-Control-Allow-Origin"] == "*"
	assert "POST" in headers["Access-Control-Allow-Methods"]
	allowed = headers["Access-Control-Allow-Headers"].lower()
	assert "content-type" in allowed
	assert "x-crusor-preview-secret" in allowed, "the secret header must be allowed or the POST is blocked"
	assert int(headers["Access-Control-Max-Age"]) > 0


def test_registration_replies_are_readable_cross_origin(proxy: PreviewServer, dev_server: str) -> None:
	# The window is served from the app's opaque origin (vscode-file://), so `*` is the only value that
	# works: a specific origin cannot be echoed back to "null" without also matching hostile sandboxes.
	status, headers, _ = get(f"{proxy.origin}/crusor-preview/health")
	assert status == 200 and headers["Access-Control-Allow-Origin"] == "*"

	request = urllib.request.Request(
		f"{proxy.origin}/crusor-preview/target", method="POST",
		data=json.dumps({"url": dev_server + "/"}).encode(),
		headers={
			"Content-Type": "application/json",
			"X-Crusor-Preview-Secret": TEST_SECRET,
			"Origin": "null",  # what the app's opaque (vscode-file://) origin sends
		},
	)
	with urllib.request.urlopen(request, timeout=10) as response:
		assert response.status == 200
		assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_registration_without_the_run_secret_is_refused(proxy: PreviewServer, dev_server: str) -> None:
	# The attack this stops: any page in the user's browser POSTs a file target and then reads it back
	# through the proxy. The secret is published only in the 0600 endpoint file and the window's URL.
	status, body = post(f"{proxy.origin}/crusor-preview/target", {"url": dev_server + "/"})
	assert status == 403
	assert "secret" in body["error"]
	assert "endpoint file" in body["hint"]

	status, body = post(f"{proxy.origin}/crusor-preview/target", {"url": dev_server + "/"}, secret="wrong")
	assert status == 403, "a wrong secret is not a secret"


def test_proxied_pages_still_need_their_token_not_the_secret(proxy: PreviewServer, dev_server: str) -> None:
	"""Two different capabilities: the secret registers a target, the token reads one."""
	target = register(proxy, url=dev_server + "/")
	status, _, body = get(proxy.origin + target["previewUrl"])          # no secret on this request
	assert status == 200 and b"Agent built this" in body
	status, _, _ = get(f"{proxy.origin}/p/{'x' * 22}/")
	assert status == 404
