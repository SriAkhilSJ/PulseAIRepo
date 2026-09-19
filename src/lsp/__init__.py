"""Language Server Protocol (LSP) integration for PulseAI.

PulseAI runs full language servers (pyright, gopls, rust-analyzer,
typescript-language-server, etc.) as subprocesses and pipes their
``textDocument/publishDiagnostics`` output into the post-write lint
delta filter used by ``write_file`` and ``edit_file``.

LSP is **gated on git workspace detection** — if the agent's cwd is
inside a git repository, LSP runs against that workspace; otherwise the
file_operations layer falls back to its existing in-process syntax
checks.

Public API:

    from src.lsp import get_service

    svc = get_service()
    if svc and svc.enabled_for(path):
        await svc.touch_file(path)
        diags = svc.diagnostics_for(path)
"""
from __future__ import annotations

import atexit
import logging
import threading
from typing import Optional

from src.lsp.manager import LSPService

logger = logging.getLogger("src.lsp")

_service: Optional[LSPService] = None
_atexit_registered = False
_service_lock = threading.Lock()


def get_service() -> Optional[LSPService]:
    """Return the process-wide LSP service singleton, or None when disabled.

    The service is created lazily on first call.  ``None`` is returned
    when LSP is disabled in config, when no workspace can be detected,
    or when the platform doesn't support subprocess-based LSP servers.
    """
    global _service, _atexit_registered
    if _service is not None:
        return _service if _service.is_active() else None
    with _service_lock:
        if _service is not None:
            return _service if _service.is_active() else None
        _service = LSPService.create_from_config()
        if not _atexit_registered:
            atexit.register(_atexit_shutdown)
            _atexit_registered = True
    return _service if (_service is not None and _service.is_active()) else None


def warmup(file_path: Optional[str] = None) -> None:
    """Trigger background warmup of LSP services."""
    svc = get_service()
    if svc is not None:
        svc.warmup(file_path)


def shutdown_service() -> None:
    """Tear down the LSP service if one was started."""
    global _service
    with _service_lock:
        svc = _service
        _service = None
    if svc is not None:
        try:
            svc.shutdown()
        except Exception as e:
            logger.debug("LSP shutdown error: %s", e)


def _atexit_shutdown() -> None:
    try:
        shutdown_service()
    except Exception as e:
        logger.debug("atexit LSP shutdown failed: %s", e)


__all__ = ["get_service", "shutdown_service", "warmup", "LSPService"]
