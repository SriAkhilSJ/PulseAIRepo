"""Bind guard for the AG-UI endpoint (Phase 1, AGUI_A2UI_PLAN.md).

Pure stdlib logic so tests can import it without FastAPI/CopilotKit.
Mirrors the dashboard pattern (src/dashboard_server.py): loopback by
default, and a non-loopback bind is refused unless a token is configured.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8123


@dataclass(frozen=True)
class BindDecision:
    host: str
    port: int
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def resolve_bind(env: Mapping[str, str] | None = None) -> BindDecision:
    """Decide the AG-UI bind from the environment.

    CRUSORAI_HOST overrides the host (default loopback), CRUSORAI_PORT
    the port (default 8123). A non-loopback host without
    CRUSORAI_DASHBOARD_TOKEN is an error, never a silent public bind.
    """
    env = os.environ if env is None else env
    host = (env.get("CRUSORAI_HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST
    raw_port = (env.get("CRUSORAI_PORT") or "").strip()
    try:
        port = int(raw_port) if raw_port else DEFAULT_PORT
    except ValueError:
        return BindDecision(host, DEFAULT_PORT, f"CRUSORAI_PORT is not a number: {raw_port!r}")
    token = (env.get("CRUSORAI_DASHBOARD_TOKEN") or "").strip()
    if host not in LOOPBACK_HOSTS and not token:
        return BindDecision(
            host,
            port,
            "Refusing non-loopback AG-UI bind without CRUSORAI_DASHBOARD_TOKEN "
            f"(host={host!r}). Set the token, or bind 127.0.0.1.",
        )
    return BindDecision(host, port)


__all__ = ["BindDecision", "LOOPBACK_HOSTS", "resolve_bind"]
