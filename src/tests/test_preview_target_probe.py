"""Pins for the preview.open reachability probe (src/tools/host_tools.py).

The desktop opens the Preview window unconditionally, so the receipt the
agent sees must say whether the framed dev server actually answers — a
white window taught as "opened: true" is how "reload is broken" happened.
"""
from __future__ import annotations

import socket
import socketserver
import threading

from src.tools.host_tools import _probe_preview_target


class _HelloHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            self.request.recv(1024)
            self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        except OSError:
            pass


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_probe_reports_a_listening_server_as_reachable() -> None:
    port = _free_port()
    with socketserver.TCPServer(("127.0.0.1", port), _HelloHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = _probe_preview_target(f"http://127.0.0.1:{port}/")
        finally:
            server.shutdown()
        assert result["reachable"] is True
        assert result["port"] == port


def test_probe_reports_a_closed_port_as_unreachable() -> None:
    port = _free_port()  # nobody is listening on it
    result = _probe_preview_target(f"http://127.0.0.1:{port}/", timeout=0.5)
    assert result["reachable"] is False
    assert "nothing is listening" in str(result["detail"])


def test_probe_rejects_non_http_targets_without_raising() -> None:
    for url in ("not-a-url", "ftp://example.invalid/x", "file:///C:/x.html"):
        result = _probe_preview_target(url)
        assert result["reachable"] is False


def test_probe_tries_the_loopback_twin_for_localhost() -> None:
    # A server bound only to 127.0.0.1 must still be found when the URL
    # says "localhost" (Windows resolves localhost to ::1 first).
    port = _free_port()
    with socketserver.TCPServer(("127.0.0.1", port), _HelloHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = _probe_preview_target(f"http://localhost:{port}/")
        finally:
            server.shutdown()
        assert result["reachable"] is True
