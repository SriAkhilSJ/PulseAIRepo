"""Crusor Preview lab — the whole flow in one command, with no provider call.

    python preview-lab/lab_server.py            # http://127.0.0.1:8931/lab/
    python preview-lab/lab_server.py --port 9000 --host 0.0.0.0

What runs here
--------------
* a throwaway HTTP server for ``demo-app/`` — the stand-in for "the dev server the agent started";
* the REAL :class:`src.preview.server.PreviewServer` (proxy + injection) with lab routes mounted
  through its ``extra_handler`` hook;
* the REAL preview window chrome and the REAL injected overlay, served out of the desktop tree;
* the REAL :mod:`src.preview.prompt` to build the scoped turn text;
* a MOCK agent (:mod:`preview-lab.mock_agent`) that interprets the batch into a CSS override sheet
  instead of editing a project, because there is no provider and no project in the lab.

Open ``/lab/``, click **Open preview**, arm **Edit UI**, click elements, type fixes, **Review**,
**Send to Crusor** — the batch lands in the Agent composer, the mock agent applies it, and the
preview reloads with the change.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
import sys
import threading
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

LAB_ROOT = Path(__file__).resolve().parent
REPO_ROOT = LAB_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.preview.prompt import build_preview_prompt, build_prompt_frame  # noqa: E402
from src.preview.server import PreviewServer  # noqa: E402

DEMO_APP = LAB_ROOT / "demo-app"
RUNTIME = LAB_ROOT / ".runtime"
SESSION_ID = "lab-session-preview"
#: Same gate the IDE path exercises: registration needs this, so the lab cannot be turned into a
#: workspace file reader by a page in the user's browser (the lab binds a reachable interface).
RUN_SECRET = secrets.token_urlsafe(24)


def _load_mock_agent():
    """``preview-lab`` has a dash, so it is not an importable package — load the module by path."""
    spec = importlib.util.spec_from_file_location("crusor_preview_mock_agent", LAB_ROOT / "mock_agent.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load preview-lab/mock_agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOCK_AGENT = _load_mock_agent()


class DemoAppHandler(SimpleHTTPRequestHandler):
    """Serves the fixture app. ``preview-overrides.css`` comes from the lab runtime directory.

    That indirection is the point: the mock agent writes its edits OUTSIDE the committed fixture,
    so the repo stays clean and **Reset demo** is just "delete the runtime sheet".
    """

    protocol_version = "HTTP/1.1"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(DEMO_APP), **kwargs)

    def translate_path(self, path: str) -> str:
        clean = urllib.parse.urlsplit(path).path
        if clean.endswith("/" + MOCK_AGENT.OVERRIDE_STYLESHEET):
            return str(RUNTIME / MOCK_AGENT.OVERRIDE_STYLESHEET)
        return super().translate_path(path)

    def send_head(self):  # noqa: N802 - stdlib signature
        # A missing override sheet is normal (fresh lab) — serve empty CSS, not a 404 page.
        if self.path.endswith("/" + MOCK_AGENT.OVERRIDE_STYLESHEET):
            sheet = RUNTIME / MOCK_AGENT.OVERRIDE_STYLESHEET
            body = sheet.read_bytes() if sheet.is_file() else b"/* no preview fixes applied yet */\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return None
        return super().send_head()

    def end_headers(self) -> None:
        # The preview reloads after every mock turn; a cached fixture would hide the change.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - stdlib signature
        pass


def start_demo_app(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), DemoAppHandler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, name="crusor-preview-demo-app", daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{httpd.server_address[1]}"
    return httpd, origin


def _read_json(handler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, json.JSONDecodeError) as exc:
        return {"__error__": f"malformed JSON body: {exc}"}
    return payload if isinstance(payload, dict) else {"__error__": "body must be an object"}


def lab_routes(demo_app_origin: str):
    """``extra_handler`` for PreviewServer: the lab's own endpoints, mounted before its routing."""

    lab_assets = {"workbench.css": "text/css; charset=utf-8", "workbench.js": "application/javascript; charset=utf-8"}

    def handle(method: str, path: str, handler) -> bool:
        if path in {"/", "/lab", "/index.html"}:
            handler.send_response(302)
            handler.send_header("Location", "/lab/")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return True

        if path == "/lab/":
            body = (LAB_ROOT / "workbench.html").read_bytes()
            handler._send(200, body, "text/html; charset=utf-8")  # noqa: SLF001 - lab harness, same family
            return True

        if path.startswith("/lab/") and method in {"GET", "HEAD"}:
            name = path[len("/lab/"):]
            if name in lab_assets:
                body = (LAB_ROOT / name).read_bytes()
                handler._send(200, body, lab_assets[name])  # noqa: SLF001
                return True
            # Not a lab asset: fall through to the endpoint routes below.

        if path == "/lab/state" and method == "GET":
            handler._json(200, {  # noqa: SLF001
                # Empty origin == same-origin: the browser may be behind a reverse proxy, and only
                # it knows the public host. Relative URLs are always right.
                "proxyOrigin": "",
                "demoAppOrigin": demo_app_origin,
                "session": SESSION_ID,
                "secret": RUN_SECRET,
                "workspace": str(LAB_ROOT),
                "mockAgent": True,
                "targets": {
                    "url": demo_app_origin + "/",
                    "file": "demo-app/index.html",
                },
            })
            return True

        if path == "/lab/prompt" and method == "POST":
            payload = _read_json(handler)
            if "__error__" in payload:
                handler._json(400, {"ok": False, "error": payload["__error__"]})  # noqa: SLF001
                return True
            batch = payload.get("batch") or {}
            try:
                text = build_preview_prompt(batch)
                if not text:
                    raise ValueError("empty fix batch")
                frame = build_prompt_frame(
                    batch,
                    session_id=str(payload.get("session_id") or SESSION_ID),
                    # The lab stands in for a session bound to the fixture it previews.
                    workspace=str(DEMO_APP),
                    mode=str(payload.get("mode") or "agent"),
                )
            except ValueError as exc:
                handler._json(400, {"ok": False, "error": str(exc)})  # noqa: SLF001
                return True
            handler._json(200, {"ok": True, "text": text, "frame": frame, "chars": len(text)})  # noqa: SLF001
            return True

        if path == "/lab/agent/apply" and method == "POST":
            payload = _read_json(handler)
            if "__error__" in payload:
                handler._json(400, {"ok": False, "error": payload["__error__"]})  # noqa: SLF001
                return True
            receipt = MOCK_AGENT.apply_batch(payload.get("batch") or {}, RUNTIME)
            handler._json(200, receipt)  # noqa: SLF001
            return True

        if path == "/lab/reset" and method == "POST":
            handler._json(200, MOCK_AGENT.reset(RUNTIME))  # noqa: SLF001
            return True

        if path == "/lab/target/file" and method == "POST":
            # The second supported target kind: a static HTML file the agent wrote, no dev server.
            if not handler._authorised():  # noqa: SLF001 - lab harness, same family
                handler._json(403, {"ok": False, "error": "preview registration requires the run secret"})  # noqa: SLF001
                return True
            spec = handler.preview.register_file("demo-app/index.html", label="aurora-landing · workspace file")
            handler._json(200, {  # noqa: SLF001
                "ok": True, "token": spec.token, "kind": spec.kind, "label": spec.label,
                "previewUrl": handler.preview.proxied_url(spec),
            })
            return True

        return False

    return handle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crusor-preview-lab", description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="0.0.0.0", help="bind address (0.0.0.0 so the lab is reachable)")
    parser.add_argument("--port", type=int, default=8931)
    args = parser.parse_args(argv)

    RUNTIME.mkdir(parents=True, exist_ok=True)
    demo_httpd, demo_origin = start_demo_app()
    server = PreviewServer(
        LAB_ROOT,
        host=args.host,
        port=args.port,
        secret=RUN_SECRET,
        extra_handler=lab_routes(demo_origin),
    ).start()

    print("Crusor Preview lab")
    print(f"  workbench (open this) : {server.origin}/lab/")
    print(f"  preview window UI     : {server.origin}/crusor-preview/ui/")
    print(f"  demo app (target)     : {demo_origin}/")
    print(f"  runtime overrides     : {RUNTIME / MOCK_AGENT.OVERRIDE_STYLESHEET}")
    print("  mock agent            : preview-lab/mock_agent.py (rules, no provider call)")
    try:
        while True:
            threading.Event().wait(0.5)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        pass
    finally:
        server.stop()
        demo_httpd.shutdown()
        demo_httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
